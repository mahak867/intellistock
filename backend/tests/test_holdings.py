"""Corporate actions applied to holdings, and XIRR against NIFTY 50, through the API (SQLite, fake prices)."""
import asyncio
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core import database
from backend.data import providers
from backend.models.db_models import Base, PortfolioEntry, User
from backend.services import holdings_service as H

ME, OTHER = "5f0c2a9e-3b7d-4c1e-9a2f-7d8e6b5a4c3d", "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api.routes.auth import get_current_user

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'h.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, class_=AsyncSession)() as s:
            s.add_all([User(id=ME, email="me@example.com", full_name="m", hashed_password="x"), User(id=OTHER, email="o@example.com", full_name="o", hashed_password="x")])
            await s.flush()
            s.add(PortfolioEntry(user_id=ME, ticker="TCS", exchange="NSE", quantity=10, avg_buy_price=1000, buy_date=datetime(2023, 1, 2, tzinfo=timezone.utc)))
            s.add(PortfolioEntry(user_id=ME, ticker="NEWCO", exchange="NSE", quantity=5, avg_buy_price=100, buy_date=datetime.now(timezone.utc)))
            await s.commit()

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    idx = pd.bdate_range("2022-06-01", "2026-12-31")
    nifty = pd.Series(np.linspace(18000, 24000, len(idx)), index=idx)
    monkeypatch.setattr(providers, "index_series", lambda name="NIFTY 50": nifty)

    def prices(sym, days=260):
        px = {"TCS": 260.0, "NEWCO": 110.0}[sym]
        df = pd.DataFrame({"open": px, "high": px, "low": px, "close": px, "volume": 1.0}, index=pd.bdate_range(end="2026-10-30", periods=5))
        return providers.Prices(df, "nse", None)

    monkeypatch.setattr(providers, "get_prices", prices)
    who = {"sub": ME}
    app.dependency_overrides[get_current_user] = lambda: who
    c = TestClient(app)
    c.who = who
    yield c
    app.dependency_overrides.clear()
    asyncio.run(eng.dispose())


def test_actions_adjust_portfolio_and_dividends_count(api):
    for a in ({"ticker": "TCS", "kind": "split", "ex_date": "2024-03-01", "ratio_new": 10, "ratio_old": 2},
              {"ticker": "tcs", "kind": "dividend", "ex_date": "2024-06-01", "amount": 4},
              {"ticker": "TCS", "kind": "bonus", "ex_date": "2025-01-10", "ratio_new": 1, "ratio_old": 1}):
        r = api.post("/api/v1/users/corporate-actions", json=a)
        assert r.status_code == 201, r.text
    assert api.post("/api/v1/users/corporate-actions", json={"ticker": "TCS", "kind": "bonus", "ex_date": "2025-01-10", "ratio_new": 1, "ratio_old": 1}).status_code == 409
    p = {x["ticker"]: x for x in api.get("/api/v1/users/portfolio").json()["portfolio"]}
    assert p["TCS"]["quantity"] == 100 and p["TCS"]["avg_buy_price"] == 100 and p["TCS"]["raw_quantity"] == 10
    assert p["TCS"]["dividends_received"] == 200.0  # Rs 4 on 50 shares (after the split, before the bonus)
    assert p["NEWCO"]["quantity"] == 5 and p["NEWCO"]["adjustments"] == []


def test_performance_xirr_vs_nifty(api):
    api.post("/api/v1/users/corporate-actions", json={"ticker": "TCS", "kind": "split", "ex_date": "2024-03-01", "ratio_new": 10, "ratio_old": 1})
    r = api.get("/api/v1/users/portfolio/performance")
    assert r.status_code == 200, r.text
    j = r.json()
    rows = {x["ticker"]: x for x in j["holdings"]}
    assert rows["TCS"]["value"] == 26000 and rows["TCS"]["invested"] == 10000  # 100 shares at 260
    assert rows["TCS"]["xirr"] > 20 and rows["TCS"]["nifty_xirr"] is not None and rows["TCS"]["nifty_xirr"] < rows["TCS"]["xirr"]
    assert rows["NEWCO"]["xirr"] is None and "under a year" in rows["NEWCO"]["note"]
    assert j["total"]["invested"] == 10500 and j["total"]["xirr"] is not None and j["real_prices"] is True


@pytest.mark.parametrize("bad", [
    {"ticker": "TCS", "kind": "dividend", "ex_date": "2024-06-01"},
    {"ticker": "TCS", "kind": "split", "ex_date": "2024-06-01", "ratio_new": 2, "ratio_old": 10},
    {"ticker": "TCS", "kind": "bonus", "ex_date": "2024-06-01", "ratio_new": 1},
    {"ticker": "TCS", "kind": "rights", "ex_date": "2024-06-01", "amount": 1},
    {"ticker": "T CS", "kind": "dividend", "ex_date": "2024-06-01", "amount": 1},
    {"ticker": "TCS", "kind": "dividend", "ex_date": "1900-01-01", "amount": 1},
    {"ticker": "TCS", "kind": "dividend", "ex_date": "2024-06-01", "amount": -3},
])
def test_bad_actions_rejected(api, bad):
    assert api.post("/api/v1/users/corporate-actions", json=bad).status_code == 422


def test_actions_are_private_and_deletable(api):
    aid = api.post("/api/v1/users/corporate-actions", json={"ticker": "TCS", "kind": "dividend", "ex_date": "2024-06-01", "amount": 4}).json()["id"]
    api.who["sub"] = OTHER
    assert api.get("/api/v1/users/corporate-actions").json()["actions"] == []
    assert api.delete(f"/api/v1/users/corporate-actions/{aid}").status_code == 404
    api.who["sub"] = ME
    assert api.delete(f"/api/v1/users/corporate-actions/{aid}").status_code == 204
    assert api.get("/api/v1/users/corporate-actions").json()["actions"] == []


def test_lookup_reports_nse_failure_clearly(api, monkeypatch):
    from backend.tools import corpactions as CA

    def down(sym):
        raise ConnectionError("blocked")
    monkeypatch.setattr(CA, "fetch_nse", down)
    r = api.get("/api/v1/users/corporate-actions/lookup/TCS")
    assert r.status_code == 502 and "Enter the action yourself" in r.json()["detail"]
    monkeypatch.setattr(CA, "fetch_nse", lambda s: [{"ticker": "TCS", "ex_date": date(2025, 10, 17), "kind": "dividend", "amount": 11.0, "source_text": "Interim Dividend - Rs 11 Per Share"}])
    assert api.get("/api/v1/users/corporate-actions/lookup/tcs").json()["actions"][0]["ex_date"] == "2025-10-17"
    assert api.get("/api/v1/users/corporate-actions/lookup/BAD%20SYM").status_code == 422


def test_placeholder_prices_are_flagged(api, monkeypatch):
    def synth(sym, days=260):
        df = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=pd.bdate_range(end="2026-10-30", periods=5))
        return providers.Prices(df, "synthetic", None)
    monkeypatch.setattr(providers, "get_prices", synth)
    j = api.get("/api/v1/users/portfolio/performance").json()
    assert j["real_prices"] is False and "PLACEHOLDERS" in j["warning"]


def test_family_accounts_filter_performance(api):
    r = api.post("/api/v1/users/portfolio", json={"ticker": "TCS", "quantity": 5, "avg_buy_price": 100, "buy_date": "2023-06-01T00:00:00", "account": "Mom"})
    assert r.status_code == 201, r.text
    assert api.post("/api/v1/users/portfolio", json={"ticker": "TCS", "quantity": 1, "avg_buy_price": 1, "buy_date": "2023-06-01T00:00:00", "account": "x;drop"}).status_code == 422
    j = api.get("/api/v1/users/portfolio/performance?account=Mom").json()
    assert [h["account"] for h in j["holdings"]] == ["Mom"] and j["total"]["invested"] == 500 and j["accounts"] == ["Me", "Mom"]
    assert len(api.get("/api/v1/users/portfolio/performance").json()["holdings"]) == 3


def test_named_watchlists(api):
    for body in ({"ticker": "TCS"}, {"ticker": "TCS", "list_name": "Banks"}, {"ticker": "HDFCBANK", "list_name": "Banks"}):
        assert api.post("/api/v1/stocks/watchlist", json=body).status_code == 201
    assert api.post("/api/v1/stocks/watchlist", json={"ticker": "TCS", "list_name": "Banks"}).status_code == 409
    items = api.get("/api/v1/stocks/watchlist").json()["watchlist"]
    assert sorted((i["list_name"], i["ticker"]) for i in items) == [("Banks", "HDFCBANK"), ("Banks", "TCS"), ("Main", "TCS")]
