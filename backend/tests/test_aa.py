"""Account Aggregator (Setu) flow against a mock built from Setu's documented payloads."""
import asyncio
import json

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.brokers import aa as AA
from backend.core import database
from backend.core.config import settings
from backend.data import amfi, providers
from backend.models.db_models import Base, User

SESSION = {"status": "PARTIAL", "format": "json", "id": "sess-1", "consentId": "consent-123", "fips": [
    {"fipID": "HDFC-FIP", "accounts": [
        {"maskedAccNumber": "XXXXXX4373", "status": "DELIVERED", "data": {"account": {"type": "deposit", "summary": {"currentBalance": "101666.33", "type": "SAVINGS", "balanceDateTime": "2026-11-05T07:50:00+00:00"}}}},
        {"maskedAccNumber": "XXXXXX9911", "status": "DELIVERED", "data": {"account": {"type": "term_deposit", "summary": {"principalAmount": "200000", "currentValue": "214500.50", "interestRate": "7.1", "openingDate": "2025-01-15", "maturityDate": "2027-01-15"}}}}]},
    {"fipID": "CDSL", "accounts": [
        {"maskedAccNumber": "XXXX5678", "status": "DELIVERED", "data": {"account": {"type": "equities", "summary": {"investment": {"holdings": {"holding": [
            {"isin": "INE467B01029", "issuerName": "TATA CONSULTANCY SERVICES", "units": "10", "lastTradedPrice": "3480"},
            {"isin": "INE000Z99999", "issuerName": "UNLISTED CO", "units": "5", "lastTradedPrice": "10"}]}}}}}}]},
    {"fipID": "CAMS", "accounts": [
        {"maskedAccNumber": "XXXX1234", "status": "DELIVERED", "data": {"account": {"type": "mutual_funds", "summary": {"investment": {"holdings": {"holding": {"amfiCode": "120716", "isin": "INF769K01DM9", "schemeName": "UTI Nifty 50 Index Fund", "closingUnits": "40", "nav": "180.75", "folioNo": "77/12"}}}}}}}]},
    {"fipID": "ACME-FIP", "accounts": [{"maskedAccNumber": "XXXX0000", "FIstatus": "FAILED", "data": None}]}]}


def test_parse_session():
    got = AA.parse_session(SESSION)
    assert got["bank"][0]["amount"] == 101666.33 and got["bank"][0]["as_of"] == "2026-11-05"
    assert got["deposits"][0]["value"] == 214500.5 and got["deposits"][0]["maturity"] == "2027-01-15"
    assert [s["isin"] for s in got["stocks"]] == ["INE467B01029", "INE000Z99999"]
    assert got["funds"][0]["scheme_code"] == "120716" and got["funds"][0]["units"] == 40  # a single holding comes as an object, not a list
    assert got["failed"] == ["ACME-FIP XXXX0000"]


ME = "5f0c2a9e-3b7d-4c1e-9a2f-7d8e6b5a4c3d"


class FakeSetu:
    def __init__(self):
        self.status, self.calls = "PENDING", []

    def __call__(self, req: httpx.Request):
        self.calls.append((req.method, req.url.path))
        assert req.headers["x-client-id"] == "cid" and req.headers["x-product-instance-id"] == "pid"
        if req.method == "POST" and req.url.path == "/consents":
            body = json.loads(req.content)
            assert body["vua"] == "9876543210" and body["consentDuration"]["unit"] == "MONTH"
            return httpx.Response(201, json={"id": "consent-123", "url": "https://fiu-sandbox.setu.co/consents/webview/consent-123", "status": "PENDING"})
        if req.url.path == "/consents/consent-123":
            return httpx.Response(200, json={"id": "consent-123", "status": self.status})
        if req.method == "POST" and req.url.path == "/sessions":
            assert json.loads(req.content)["consentId"] == "consent-123"
            return httpx.Response(201, json={"id": "sess-1", "status": "PENDING"})
        if req.url.path == "/sessions/sess-1":
            return httpx.Response(200, json=SESSION)
        return httpx.Response(404, json={"errorMsg": "not found"})


@pytest.fixture
def api(tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api.routes.auth import get_current_user

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'aa.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, class_=AsyncSession)() as s:
            s.add(User(id=ME, email="me@example.com", full_name="m", hashed_password="x"))
            await s.commit()

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    for k, v in (("SETU_AA_CLIENT_ID", "cid"), ("SETU_AA_CLIENT_SECRET", "sec"), ("SETU_AA_PRODUCT_INSTANCE_ID", "pid")):
        monkeypatch.setattr(settings, k, v)
    fake = FakeSetu()
    orig = AA.Setu.__init__
    monkeypatch.setattr(AA.Setu, "__init__", lambda self, client=None: orig(self, httpx.Client(transport=httpx.MockTransport(fake))))
    monkeypatch.setattr(amfi, "navs", lambda *a, **k: {})

    def prices(sym, days=260):
        df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 1.0}, index=pd.bdate_range(end="2026-10-30", periods=5))
        return providers.Prices(df, "nse", None)
    monkeypatch.setattr(providers, "get_prices", prices)
    app.dependency_overrides[get_current_user] = lambda: {"sub": ME}
    c = TestClient(app)
    c.fake = fake
    yield c
    app.dependency_overrides.clear()
    asyncio.run(eng.dispose())


def test_consent_then_sync(api):
    r = api.post("/api/v1/assets/aa/consent", json={"mobile": "9876543210", "redirect_url": "http://localhost:3000/networth?aa=done", "account": "Me"})
    assert r.status_code == 200 and r.json()["url"].endswith("consent-123"), r.text
    assert api.post("/api/v1/assets/aa/sync", json={"consent_id": "consent-123"}).status_code == 409  # not approved yet
    api.fake.status = "ACTIVE"
    r = api.post("/api/v1/assets/aa/sync", json={"consent_id": "consent-123"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert (j["bank_accounts"], j["deposits"], j["funds"], j["stocks_added"]) == (1, 1, 1, 1) and j["unmatched_stocks"] == ["UNLISTED CO"]
    assert j["failed_accounts"] == ["ACME-FIP XXXX0000"]
    nw = api.get("/api/v1/assets").json()
    kinds = sorted(a["name"] for a in nw["assets"])
    assert kinds == ["HDFC-FIP 4373 Savings", "HDFC-FIP 9911 FD"] and nw["net_worth"]["other"] == round(101666.33 + 214500.5, 2)
    again = api.post("/api/v1/assets/aa/sync", json={"consent_id": "consent-123"}).json()  # re-sync replaces, no duplicates
    assert len(api.get("/api/v1/assets").json()["assets"]) == 2 and again["stocks_updated"] == 1
    st = api.get("/api/v1/assets/aa/status").json()
    assert st["configured"] and st["consents"][0]["status"] == "ACTIVE" and st["consents"][0]["last_synced"]


def test_validation_and_not_configured(api, monkeypatch):
    for bad in ({"mobile": "12345", "redirect_url": "http://x"}, {"mobile": "9876543210", "redirect_url": "javascript:alert(1)"}):
        assert api.post("/api/v1/assets/aa/consent", json=bad).status_code == 422
    assert api.post("/api/v1/assets/aa/sync", json={"consent_id": "unknown-1"}).status_code == 404
    monkeypatch.setattr(settings, "SETU_AA_CLIENT_ID", None)
    r = api.post("/api/v1/assets/aa/consent", json={"mobile": "9876543210", "redirect_url": "http://localhost:3000/networth"})
    assert r.status_code == 503 and "not set up" in r.json()["detail"]
