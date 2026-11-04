"""HTTP-level tests for /api/v1/tools and the dev-only /api/v1/demo tool endpoints."""
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app

P = "/api/v1/tools"
D = "/api/v1/market"
TRADES = """symbol,trade_date,order_execution_time,trade_type,quantity,price
ABC,2026-01-05,2026-01-05T09:20:00,buy,10,100
ABC,2026-01-05,2026-01-05T10:20:00,sell,10,110
XYZ,2026-01-06,2026-01-06T09:30:00,buy,10,200
XYZ,2026-01-06,2026-01-06T09:50:00,sell,10,190
"""


@pytest.fixture(scope="module")
def c():
    # No `with`: skips the lifespan, so the tests need neither Postgres nor Redis.
    yield TestClient(app)


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_position_size_with_explicit_stop(c):
    j = ok(c.post(f"{P}/position-size", json={"entry": 500, "stop": 490, "capital": 100000, "risk_pct": 1}))
    assert j["shares"] == 100 and j["stop_was_computed"] is False


def test_position_size_places_stop_from_volatility(c):
    j = ok(c.post(f"{P}/position-size", json={"entry": 500, "daily_vol_pct": 1.5, "risk_amount": 1000}))
    assert j["stop_was_computed"] is True and j["shares"] > 0


def test_position_size_needs_stop_or_vol(c):
    assert c.post(f"{P}/position-size", json={"entry": 500, "risk_amount": 1000}).status_code == 422


def test_costs(c):
    j = ok(c.post(f"{P}/costs", json={"segment": "equity_delivery", "buy_price": 100, "sell_price": 110, "qty": 100}))
    assert j["net_pnl"] < j["gross_pnl"] and "approximate" in j["note"]


def test_costs_unknown_segment(c):
    assert c.post(f"{P}/costs", json={"segment": "nope", "buy_price": 1, "sell_price": 1, "qty": 1}).status_code == 422


def test_journal(c):
    j = ok(c.post(f"{P}/journal", json={"csv": TRADES}))
    assert j["stats"]["trades"] == 2 and len(j["trades"]) == 2


def test_journal_bad_csv(c):
    assert c.post(f"{P}/journal", json={"csv": "a,b\n1,2"}).status_code == 422


def test_options_analyse_from_vol_and_from_price(c):
    base = {"spot": 100, "strike": 100, "days": 30, "kind": "call"}
    a = ok(c.post(f"{P}/options/analyse", json={**base, "vol_pct": 20}))
    b = ok(c.post(f"{P}/options/analyse", json={**base, "market_price": a["theoretical_price"]}))
    assert abs(b["implied_vol"] - 0.20) < 1e-3
    assert 0 < a["greeks"]["delta"] < 1


def test_options_analyse_needs_vol_or_price(c):
    assert c.post(f"{P}/options/analyse", json={"spot": 100, "strike": 100, "days": 30}).status_code == 422


def test_payoff_and_chain(c):
    legs = [{"kind": "call", "strike": 100, "premium": 5, "qty": 1}]
    j = ok(c.post(f"{P}/options/payoff", json={"legs": legs, "lo": 50, "hi": 150}))
    assert j["max_loss"] == -5 and "SPAN" in j["note"]
    rows = [{"strike": 100, "call_oi": 10, "put_oi": 20}, {"strike": 110, "call_oi": 30, "put_oi": 5}]
    ch = ok(c.post(f"{P}/options/chain", json=rows))
    assert ch["max_pain"] in (100, 110) and ch["pcr_oi"] == pytest.approx(25 / 40)


def test_risk_day_and_checklist(c):
    s = ok(c.post(f"{P}/risk/day", json={"pnls": [-500, -600], "max_loss": 1000}))
    assert s["level"] == "stop"
    items = ok(c.get(f"{P}/risk/checklist-items"))
    j = ok(c.post(f"{P}/risk/checklist", json={i["text"]: True for i in items}))
    assert j["pass"] is True
    assert ok(c.post(f"{P}/risk/checklist", json={}))["pass"] is False


def test_expiries(c):
    j = ok(c.post(f"{P}/calendar/expiries", json={"year": 2026, "month": 11, "exchange": "NSE"}))
    assert j["weekday"] == "Tuesday" and j["monthly"] == "2026-11-24"


def test_portfolio_allocation_and_xirr(c):
    j = ok(c.post(f"{P}/portfolio/allocation", json={"csv": "symbol,qty,avg_price\nA,10,100\nB,10,50\n", "prices": {"A": 120, "B": 40}}))
    assert j["total_value"] == 1600
    x = ok(c.post(f"{P}/portfolio/xirr", json=[{"date": "2025-01-01", "amount": -1000}, {"date": "2026-01-01", "amount": 1100}]))
    assert x["xirr"] == pytest.approx(0.10, abs=1e-3)


def test_planner(c):
    f = ok(c.post(f"{P}/planner/sip", json={"monthly": 10000, "annual_return_pct": 12, "years": 10}))
    assert f["invested"] == 1_200_000 and f["future_value"] > f["invested"]
    g = ok(c.post(f"{P}/planner/goal", json={"goal_today": 1_000_000, "years": 10, "annual_return_pct": 12}))
    assert g["monthly_sip"] > 0
    r = ok(c.post(f"{P}/planner/rebalance", json={"values": {"EQ": 700, "DEBT": 300}, "targets": {"EQ": 0.6, "DEBT": 0.4}}))
    assert r


def test_tax(c):
    fills = [{"symbol": "A", "date": "2025-01-01", "side": "buy", "qty": 10, "price": 100},
             {"symbol": "A", "date": "2026-03-01", "side": "sell", "qty": 10, "price": 200}]
    j = ok(c.post(f"{P}/tax/capital-gains", json=fills))
    assert "chartered accountant" in j["disclaimer"] and j["lots"]


def test_fundamentals_and_announcements(c):
    q = ok(c.post(f"{P}/fundamentals/score", json={"roe": 22, "debt_equity": 0.3}))
    assert "score" in q
    d = ok(c.post(f"{P}/announcements/digest", json=[{"symbol": "A", "title": "Board approves dividend", "date": "2026-11-01"}]))
    assert d and d[0]["symbol"] == "A"


def test_demo_screener_backtest_portfolio_risk(c):
    s = ok(c.get(f"{D}/screener"))
    assert s["synthetic"] is True and len(s["rows"]) >= 10 and "symbol" in s["rows"][0]
    b = ok(c.get(f"{D}/backtest/TCS"))
    assert b["synthetic"] and "walk_forward_out_of_sample" in b and len(b["equity"]) > 20
    p = ok(c.post(f"{D}/portfolio-risk", json={"csv": "symbol,qty,avg_price\nTCS,10,100\nINFY,20,100\nITC,50,100\n"}))
    assert p["synthetic"] and p["month"]["historical"] and len(p["stress"]) == 2


def test_quotes_say_whether_they_are_placeholders(c):
    q = ok(c.get(f"{D}/quotes?tickers=TCS,INFY"))
    assert len(q) == 2 and all(x["synthetic"] is True and x["source"] == "synthetic" and x["as_of"] for x in q)


def test_cors_allows_patch_for_profile_update(c):
    """Settings uses PATCH /users/me from the browser; the CORS preflight must allow PATCH."""
    r = c.options("/api/v1/users/me", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PATCH",
                                               "Access-Control-Request-Headers": "authorization,content-type"})
    assert r.status_code == 200, r.text
    assert "PATCH" in r.headers.get("access-control-allow-methods", "")


def test_placeholder_prices_are_consistent_across_windows():
    """A symbol must show the same placeholder price on the watchlist, chart and screener, whatever window each asks for."""
    from ml.forecast.synthetic import synthetic_ohlcv

    for t in ("RELIANCE", "TCS"):
        a, b, d = synthetic_ohlcv(t, 300), synthetic_ohlcv(t, 400), synthetic_ohlcv(t, 700)
        assert a["close"].iloc[-1] == b["close"].iloc[-1] == d["close"].iloc[-1]
        assert a.index[-1] == d.index[-1] and len(a) == 300 and len(d) == 700


@pytest.mark.parametrize("path,body", [
    ("/position-size", {"entry": 500, "stop": 490, "capital": 99999999999999999999, "risk_pct": 1}),
    ("/costs", {"segment": "equity_intraday", "buy_price": 99999999999999999999, "sell_price": 1, "qty": 1}),
    ("/options/analyse", {"spot": 99999999999999999999, "strike": 24200, "days": 7, "kind": "call", "vol_pct": 14}),
    ("/options/analyse", {"spot": 24000, "strike": 24200, "days": 99999999999999999999, "kind": "call", "vol_pct": 14}),
    ("/options/chain", [{"strike": 100, "call_oi": 99999999999999999999, "put_oi": 5}]),
    ("/risk/day", {"pnls": [99999999999999999999, 1], "max_loss": 2000}),
    ("/planner/sip", {"monthly": 99999999999999999999, "annual_return_pct": 12, "years": 10}),
    ("/planner/goal", {"goal_today": 99999999999999999999, "years": 10, "annual_return_pct": 12, "inflation_pct": 6}),
])
def test_extreme_numbers_are_a_422_not_a_500(c, path, body):
    r = c.post(P + path, json=body)
    assert r.status_code < 500, r.text
    assert r.status_code in (200, 422)


@pytest.mark.parametrize("raw", [b"NaN", b'{"entry": NaN}', b"[Infinity]", b'{"entry": Infinity, "stop": 1, "capital": 1, "risk_pct": 1}'])
def test_non_finite_json_is_a_422(c, raw):
    r = c.post(f"{P}/position-size", content=raw, headers={"Content-Type": "application/json"})
    assert r.status_code == 422, r.text
    assert "detail" in r.json()


@pytest.fixture()
def authed(c):
    from backend.api.routes.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": "00000000-0000-0000-0000-000000000001", "role": "user"}
    yield c
    app.dependency_overrides.pop(get_current_user, None)


U = "/api/v1/users"


@pytest.mark.parametrize("path,body", [
    (f"{U}/portfolio", {"ticker": "TCS", "exchange": "A" * 40, "quantity": 1, "avg_buy_price": 1, "buy_date": "2026-01-01T00:00:00"}),
    (f"{U}/portfolio", {"ticker": "TCS", "exchange": "NSE", "quantity": 1, "avg_buy_price": 1, "buy_date": "2026-01-01T00:00:00", "notes": "a\u0000b"}),
    ("/api/v1/stocks/watchlist", {"ticker": "TCS", "exchange": "'; DROP TABLE users;--"}),
    ("/api/v1/stocks/watchlist", {"ticker": "TCS", "notes": "x\u0000"}),
    ("/api/v1/auth/register", {"email": "a@example.com", "password": "Valid-Pass-1!", "full_name": "a\u0000b"}),
])
def test_bad_strings_are_422_before_reaching_the_database(authed, path, body):
    r = authed.post(path, json=body)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("path", [f"{U}/portfolio/abc", f"{U}/alerts/123", "/api/v1/stocks/watchlist/'; --"])
def test_malformed_ids_are_422_not_500(authed, path):
    assert authed.delete(path).status_code == 422


def test_login_with_null_character_is_401_not_500(c):
    r = c.post("/api/v1/auth/login", data={"username": "a\u0000@example.com", "password": "x"})
    assert r.status_code == 401


def test_exchange_accepts_nse_and_bse_only():
    from backend.api.routes.users import PortfolioAddRequest

    ok = dict(ticker="TCS", quantity=1, avg_buy_price=1, buy_date="2026-01-01T00:00:00")
    assert PortfolioAddRequest(exchange="BSE", **ok).exchange == "BSE"
    with pytest.raises(Exception):
        PortfolioAddRequest(exchange="NYSE", **ok)
