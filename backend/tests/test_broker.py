"""Zerodha Kite Connect link: client against a mock of the documented API, encryption, confirmations, and the HTTP routes."""
import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.brokers import kite as K
from backend.brokers import vault
from backend.core import database
from backend.core.config import settings
from backend.models.db_models import Base, OrderLog, PortfolioEntry, User
from backend.services import broker_service as B

# Real-looking ids: on SQLite an all-digit id would be stored as a number.
ME, OTHER = "5f0c2a9e-3b7d-4c1e-9a2f-7d8e6b5a4c3d", "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
API_KEY, SECRET, REQ, ACCESS = "abcd1234key", "s3cretS3cret99", "reqTOKEN123", "accessTOKEN456"


class FakeKite:
    """Answers like api.kite.trade (v3 envelope: {"status": "success", "data": ...})."""

    def __init__(self):
        self.calls, self.orders, self.fail_orders, self.no_quotes, self.expired = [], [], None, False, False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        assert req.headers["X-Kite-Version"] == "3"
        p = req.url.path
        ok = lambda d: httpx.Response(200, json={"status": "success", "data": d})  # noqa: E731
        err = lambda code, kind, msg: httpx.Response(code, json={"status": "error", "error_type": kind, "message": msg})  # noqa: E731
        if p == "/session/token" and req.method == "POST":
            f = parse_qs(req.content.decode())
            if f["checksum"][0] != hashlib.sha256((API_KEY + f["request_token"][0] + SECRET).encode()).hexdigest():
                return err(403, "TokenException", "Invalid checksum")
            return ok({"user_id": "AB1234", "user_name": "Test Trader", "access_token": ACCESS, "public_token": "x"})
        if p == "/session/token" and req.method == "DELETE":
            return ok(True)
        if req.headers.get("Authorization") != f"token {API_KEY}:{ACCESS}" or self.expired:
            return err(403, "TokenException", "Incorrect `api_key` or `access_token`.")
        if p == "/portfolio/holdings":
            return ok([{"tradingsymbol": "TCS", "exchange": "NSE", "isin": "INE467B01029", "quantity": 8, "t1_quantity": 2, "average_price": 3300.5, "last_price": 3500.0, "pnl": 1995.0},
                       {"tradingsymbol": "INFY", "exchange": "NSE", "quantity": 5, "t1_quantity": 0, "average_price": 1450.0, "last_price": 1500.0, "pnl": 250.0},
                       {"tradingsymbol": "SOLD", "exchange": "NSE", "quantity": 0, "t1_quantity": 0, "average_price": 10.0}])
        if p == "/quote/ltp":
            if self.no_quotes:
                return err(403, "PermissionException", "Insufficient permission for that call.")
            keys = [v for k, v in req.url.params.multi_items() if k == "i"]
            prices = {"NSE:TCS": 3500.0, "NSE:INFY": 1500.0, "NSE:RELIANCE": 1300.0}
            return ok({k: {"instrument_token": 1, "last_price": prices[k]} for k in keys if k in prices})
        if p == "/orders/regular" and req.method == "POST":
            f = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            if self.fail_orders:
                return err(400, "InputException", self.fail_orders)
            self.orders.append(f)
            return ok({"order_id": f"2611060000{len(self.orders):05d}"})
        return err(404, "GeneralException", "Route not found")


@pytest.fixture
def fake(monkeypatch):
    f = FakeKite()
    monkeypatch.setattr(B, "make_client", lambda key, tok: K.Kite(key, tok, httpx.Client(transport=httpx.MockTransport(f))))
    return f


# ── client ──
def test_checksum_and_login_url():
    assert K.checksum("a", "b", "c") == hashlib.sha256(b"abc").hexdigest()
    assert K.login_url("key1").endswith("/connect/login?v=3&api_key=key1")


@pytest.mark.parametrize("ist_time,expected_day_offset", [((10, 0), 1), ((5, 59), 0), ((6, 0), 1), ((23, 30), 1)])
def test_token_expires_at_six_am_ist(ist_time, expected_day_offset):
    ist = timezone(timedelta(hours=5, minutes=30))
    login = datetime(2026, 11, 6, *ist_time, tzinfo=ist)
    exp = K.token_expiry(login).astimezone(ist)
    assert (exp.hour, exp.minute) == (6, 0) and (exp.date() - login.date()).days == expected_day_offset


def test_client_session_holdings_quotes_orders(fake):
    k = B.make_client(API_KEY, None)
    assert k.create_session(REQ, SECRET)["user_id"] == "AB1234" and k.access_token == ACCESS
    h = k.holdings()
    assert [x["ticker"] for x in h] == ["TCS", "INFY"] and h[0]["quantity"] == 10  # T1 shares count; sold-out rows dropped
    assert k.ltp(["tcs", "INFY", "bad;sym"]) == {"TCS": 3500.0, "INFY": 1500.0}
    oid = k.place_limit_order(tradingsymbol="TCS", exchange="NSE", side="BUY", quantity=2, price=3490.0, product="CNC")
    assert oid and fake.orders[0] == {"tradingsymbol": "TCS", "exchange": "NSE", "transaction_type": "BUY", "order_type": "LIMIT", "quantity": "2",
                                      "price": "3490.00", "product": "CNC", "validity": "DAY", "tag": "intellistock"}


def test_client_errors_are_typed(fake):
    with pytest.raises(K.KiteError) as e:
        B.make_client(API_KEY, None).create_session(REQ, "wrong-secret")
    assert e.value.needs_login
    with pytest.raises(K.KiteError):
        B.make_client(API_KEY, None).create_session("bad token!", SECRET)
    fake.no_quotes = True
    with pytest.raises(K.KiteError) as e:
        B.make_client(API_KEY, ACCESS).ltp(["TCS"])
    assert e.value.kind == "PermissionException"


def test_network_failure_is_a_clear_error():
    def boom(req):
        raise httpx.ConnectError("down")
    with pytest.raises(K.KiteError) as e:
        K.Kite(API_KEY, ACCESS, httpx.Client(transport=httpx.MockTransport(boom))).holdings()
    assert e.value.kind == "NetworkException"


# ── vault and confirmations ──
def test_vault_roundtrip_and_key_change(monkeypatch):
    sealed = vault.seal("my-secret")
    assert "my-secret" not in sealed and vault.unseal(sealed) == "my-secret"
    monkeypatch.setattr(settings, "BROKER_ENCRYPTION_KEY", "a-different-key")
    with pytest.raises(vault.VaultError):
        vault.unseal(sealed)


def test_confirm_token_binds_the_exact_order():
    o = {"tradingsymbol": "TCS", "exchange": "NSE", "side": "BUY", "quantity": 2, "price": 3490.0, "product": "CNC"}
    t = B.confirm_token("u1", o, now=1000)
    assert B.check_confirm("u1", o, t, now=1050)
    for changed in ({**o, "quantity": 20}, {**o, "price": 349.0}, {**o, "side": "SELL"}, {**o, "product": "MIS"}):
        with pytest.raises(B.BrokerProblem):
            B.check_confirm("u1", changed, t, now=1050)
    with pytest.raises(B.BrokerProblem):
        B.check_confirm("someone-else", o, t, now=1050)
    with pytest.raises(B.BrokerProblem, match="expired"):
        B.check_confirm("u1", o, t, now=1000 + B.CONFIRM_SECONDS + 1)
    with pytest.raises(B.BrokerProblem):
        B.check_confirm("u1", o, "garbage", now=1050)


# ── HTTP routes (SQLite, logged-in user, fake Kite) ──
@pytest.fixture
def api(tmp_path, monkeypatch, fake):
    from backend.api.main import app
    from backend.api.routes.auth import get_current_user

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'b.db'}")

    async def setup():
        async with eng.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(eng, class_=AsyncSession)() as s:
            for uid, e in ((ME, "me@example.com"), (OTHER, "other@example.com")):
                s.add(User(id=uid, email=e, full_name=e, hashed_password="x"))
            await s.commit()

    asyncio.run(setup())
    monkeypatch.setattr(database, "AsyncSessionFactory", async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False))
    who = {"sub": ME}
    app.dependency_overrides[get_current_user] = lambda: who
    c = TestClient(app)
    c.who = who
    yield c
    app.dependency_overrides.clear()
    asyncio.run(eng.dispose())


def _connect(c):
    assert c.put("/api/v1/broker/kite/keys", json={"api_key": API_KEY, "api_secret": SECRET}).status_code == 200
    r = c.post("/api/v1/broker/kite/session", json={"request_token": REQ})
    assert r.status_code == 200, r.text
    return r.json()


def test_status_connect_and_secrets_never_returned(api):
    assert api.get("/api/v1/broker/status").json()["connected"] is False
    st = _connect(api)
    assert st["session_valid"] is True and st["broker_user_id"] == "AB1234"
    blob = json.dumps(api.get("/api/v1/broker/status").json())
    assert SECRET not in blob and ACCESS not in blob  # the api key is public (it is in the login link); secret and token never leave


def test_wrong_secret_gives_login_error(api):
    api.put("/api/v1/broker/kite/keys", json={"api_key": API_KEY, "api_secret": "wrongSecret1"})
    r = api.post("/api/v1/broker/kite/session", json={"request_token": REQ})
    assert r.status_code == 401 and "Zerodha says" in r.json()["detail"]


def test_not_connected_and_expired_session(api, fake):
    assert api.get("/api/v1/broker/holdings").status_code == 409
    _connect(api)
    fake.expired = True
    assert api.get("/api/v1/broker/holdings").status_code == 401


def test_holdings_quotes_and_import(api):
    _connect(api)
    assert [h["ticker"] for h in api.get("/api/v1/broker/holdings").json()["holdings"]] == ["TCS", "INFY"]
    q = api.get("/api/v1/broker/quotes?tickers=tcs,INFY,ZZZ").json()
    assert q["prices"] == {"TCS": 3500.0, "INFY": 1500.0} and q["missing"] == ["ZZZ"] and q["live"] is True

    async def seed():
        async with database.get_session() as s:
            for t, q in (("TCS", 1), ("TCS", 1), ("ITC", 50)):
                s.add(PortfolioEntry(user_id=api.who["sub"], ticker=t, exchange="NSE", quantity=q, avg_buy_price=100, buy_date=datetime.now(timezone.utc)))

    async def rows():
        from sqlalchemy import select
        async with database.get_session() as s:
            return {(e.ticker, e.quantity, e.avg_buy_price) for e in (await s.execute(select(PortfolioEntry))).scalars().all()}

    asyncio.run(seed())
    r = api.post("/api/v1/broker/holdings/import", json={"mode": "merge"}).json()
    assert (r["added"], r["updated"]) == (1, 1)
    assert asyncio.run(rows()) == {("TCS", 10, 3300.5), ("INFY", 5, 1450.0), ("ITC", 50, 100)}
    r = api.post("/api/v1/broker/holdings/import", json={"mode": "replace"}).json()
    assert r["removed"] == 3 and asyncio.run(rows()) == {("TCS", 10, 3300.5), ("INFY", 5, 1450.0)}


def test_order_preview_confirm_and_single_use(api, fake):
    _connect(api)
    o = {"tradingsymbol": "tcs", "exchange": "NSE", "side": "BUY", "quantity": 2, "price": 3490, "product": "CNC"}
    pv = api.post("/api/v1/broker/orders/preview", json=o)
    assert pv.status_code == 200, pv.text
    pv = pv.json()
    assert pv["last_price"] == 3500.0 and pv["value"] == 6980 and pv["charges_estimate"] > 0 and pv["order"]["tradingsymbol"] == "TCS"
    sent = api.post("/api/v1/broker/orders", json={**o, "confirm_token": pv["confirm_token"]})
    assert sent.status_code == 200, sent.text
    assert sent.json()["broker_order_id"] and len(fake.orders) == 1
    again = api.post("/api/v1/broker/orders", json={**o, "confirm_token": pv["confirm_token"]})
    assert again.status_code == 409 and len(fake.orders) == 1  # replay blocked before Zerodha
    tampered = api.post("/api/v1/broker/orders", json={**o, "quantity": 200, "confirm_token": pv["confirm_token"]})
    assert tampered.status_code == 400 and len(fake.orders) == 1
    log = api.get("/api/v1/broker/orders").json()["orders"]
    assert len(log) == 1 and log[0]["status"] == "sent" and log[0]["symbol"] == "TCS"


def test_order_guards(api, fake):
    _connect(api)
    base = {"tradingsymbol": "TCS", "exchange": "NSE", "side": "BUY", "quantity": 2, "product": "CNC"}
    assert api.post("/api/v1/broker/orders/preview", json={**base, "price": 349.0}).status_code == 422  # 90% below: typo
    assert api.post("/api/v1/broker/orders/preview", json={**base, "price": 3500, "quantity": 1000}).status_code == 422  # over value cap
    for bad in ({**base, "price": -1}, {**base, "price": 3500, "side": "HOLD"}, {**base, "price": 3500, "product": "NRML"},
                {**base, "price": 3500, "tradingsymbol": "TCS;DROP"}, {**base, "price": 3500, "quantity": 0}):
        assert api.post("/api/v1/broker/orders/preview", json=bad).status_code == 422, bad
    fake.no_quotes = True  # no market data add-on: preview still works, with a warning
    pv = api.post("/api/v1/broker/orders/preview", json={**base, "price": 3500})
    assert pv.status_code == 200, pv.text
    pv = pv.json()
    assert pv["last_price"] is None and any("No live price" in w for w in pv["warnings"])


def test_rejected_order_is_logged(api, fake):
    _connect(api)
    fake.fail_orders = "Order request from unregistered IP. Add your static IP in the developer console."
    o = {"tradingsymbol": "TCS", "exchange": "NSE", "side": "SELL", "quantity": 1, "price": 3500, "product": "CNC"}
    tok = api.post("/api/v1/broker/orders/preview", json=o).json()["confirm_token"]
    r = api.post("/api/v1/broker/orders", json={**o, "confirm_token": tok})
    assert r.status_code == 422 and "static IP" in r.json()["detail"]
    assert api.get("/api/v1/broker/orders").json()["orders"][0]["status"] == "rejected"


def test_orders_can_be_switched_off(api, monkeypatch):
    _connect(api)
    monkeypatch.setattr(settings, "BROKER_ORDERS_ENABLED", False)
    o = {"tradingsymbol": "TCS", "exchange": "NSE", "side": "BUY", "quantity": 1, "price": 3500, "product": "CNC"}
    assert api.post("/api/v1/broker/orders/preview", json=o).status_code == 403
    assert api.post("/api/v1/broker/orders", json={**o, "confirm_token": "1.x" * 6}).status_code == 403


def test_users_cannot_see_each_others_broker(api):
    _connect(api)
    api.post("/api/v1/broker/orders/preview", json={"tradingsymbol": "TCS", "exchange": "NSE", "side": "BUY", "quantity": 1, "price": 3500, "product": "CNC"})
    api.who["sub"] = OTHER
    assert api.get("/api/v1/broker/status").json()["connected"] is False
    assert api.get("/api/v1/broker/holdings").status_code == 409
    assert api.get("/api/v1/broker/orders").json()["orders"] == []


def test_disconnect_forgets_everything(api, fake):
    _connect(api)
    assert api.delete("/api/v1/broker").status_code == 204
    assert any(r.method == "DELETE" and r.url.path == "/session/token" for r in fake.calls)  # logged out at Zerodha too
    assert api.get("/api/v1/broker/status").json()["connected"] is False
    assert api.delete("/api/v1/broker").status_code == 404


def test_live_prices_drive_price_alerts(api, monkeypatch):
    """Connected users: price alerts use the live last price and may be delivered even while server data is placeholder."""
    from backend.data import providers
    from backend.models.db_models import AlertRule
    from backend.services import alert_service as S
    import numpy as np
    import pandas as pd

    _connect(api)
    idx = pd.bdate_range(end="2026-10-30", periods=120)
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=idx)
    monkeypatch.setattr(providers, "get_prices", lambda s, days=700: providers.Prices(df, "synthetic", None))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "tok")
    sent = []

    class Snd:
        def __init__(self, *a): pass
        def send(self, t): sent.append(t); return True

    async def go():
        async with database.get_session() as s:
            u = await s.get(User, api.who["sub"])
            u.telegram_chat_id = "123456"
            s.add(AlertRule(user_id=api.who["sub"], ticker="TCS", alert_type="price_above", price_target=3400.0))
        return await S.check_alerts(make_sender=Snd)

    out = asyncio.run(go())
    assert out["fired"][0]["live"] is True and out["fired"][0]["delivered"] is True
    assert "live price from your Zerodha account" in sent[0] and "3500.00" in sent[0]


def test_malformed_requests_never_500(api):
    _connect(api)
    junk = [None, "", "x" * 5000, -1, 0, 1e308, float("nan"), [], {}, "TCS\x00", "../../etc", "<script>", True]
    paths = {"/api/v1/broker/kite/keys": ("put", ("api_key", "api_secret")), "/api/v1/broker/kite/session": ("post", ("request_token",)),
             "/api/v1/broker/holdings/import": ("post", ("mode",)),
             "/api/v1/broker/orders/preview": ("post", ("tradingsymbol", "exchange", "side", "quantity", "price", "product")),
             "/api/v1/broker/orders": ("post", ("tradingsymbol", "quantity", "price", "confirm_token"))}
    good = {"api_key": API_KEY, "api_secret": SECRET, "request_token": REQ, "mode": "merge", "tradingsymbol": "TCS", "exchange": "NSE",
            "side": "BUY", "quantity": 1, "price": 3500, "product": "CNC", "confirm_token": "1.abc"}
    n = 0
    for path, (method, fields) in paths.items():
        for f in fields:
            for j in junk:
                body = {k: good[k] for k in fields} | {f: j}
                try:
                    r = getattr(api, method)(path, content=json.dumps(body, allow_nan=True), headers={"content-type": "application/json"})
                except ValueError:
                    continue
                n += 1
                assert r.status_code < 500, (path, f, j, r.status_code, r.text[:200])
    for q in ["", ",,,", "A" * 2000, "TCS%00", "TCS,../x"]:
        assert api.get(f"/api/v1/broker/quotes?tickers={q}").status_code < 500
    assert n > 100
