from datetime import date

import httpx
import numpy as np
import pandas as pd
import pytest

from backend.tools import alerts as A
from backend.tools import backtest as B
from backend.tools import calendar as C
from backend.tools import costs as K
from backend.tools import risklimits as R
from backend.tools import screener as S


# ── costs: worked by hand ───────────────────────────────────────────────────
def test_delivery_buy_and_sell_costs():
    b = K.trade_cost("equity_delivery", "buy", 1000, 100)  # turnover 100,000
    assert (b.stt, b.stamp, b.brokerage) == (100.0, 15.0, 0.0)
    assert b.total == pytest.approx(118.6226, abs=1e-3)  # 100+2.97+0.1+15+0.5526
    s = K.trade_cost("equity_delivery", "sell", 1000, 100)
    assert s.stamp == 0 and s.dp == pytest.approx(15.93) and s.total == pytest.approx(119.5526, abs=1e-3)


def test_intraday_and_options_costs():
    i = K.trade_cost("equity_intraday", "buy", 1000, 100)
    assert i.brokerage == 20.0 and i.stt == 0 and i.total == pytest.approx(30.2226, abs=1e-3)
    o = K.trade_cost("options", "sell", 100, 75)  # premium turnover 7,500
    assert o.stt == pytest.approx(11.25) and o.brokerage == pytest.approx(2.25)
    f = K.trade_cost("futures", "sell", 1000, 100)
    assert f.stt == pytest.approx(50.0)  # 0.05% from 1 Apr 2026


def test_breakeven_and_validation():
    assert 0.2 < K.breakeven_move_pct("equity_delivery", 1000, 100) < 0.3  # ~0.238%
    with pytest.raises(ValueError):
        K.trade_cost("bonds", "buy", 1, 1)
    with pytest.raises(ValueError):
        K.trade_cost("futures", "hold", 1, 1)


# ── backtest ────────────────────────────────────────────────────────────────
def _px(n=300, drift=0.01):
    return pd.Series(100 * (1 + drift) ** np.arange(n), index=pd.bdate_range("2024-01-01", periods=n))


def test_execution_is_next_bar_and_costs_hand_check():
    c = _px()
    r = B.run_backtest(c, pd.Series(1.0, index=c.index), cost_bps=10, slippage_bps=5)
    assert r.position.iloc[0] == 0 and r.position.iloc[1] == 1
    assert r.returns.iloc[1] == pytest.approx(0.01 - 0.0015)  # entry cost on first held day
    assert r.returns.iloc[2] == pytest.approx(0.01)


def test_no_lookahead_in_signal_pipeline():
    rng = np.random.default_rng(1)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=pd.bdate_range("2024-01-01", periods=400))
    full = B.run_backtest(c, B.sma_signal(c, 5, 20)).position
    cut = B.run_backtest(c.iloc[:300], B.sma_signal(c.iloc[:300], 5, 20)).position
    assert np.allclose(full.iloc[:300].to_numpy(), cut.to_numpy())  # future data never changes the past


def test_costs_reduce_returns():
    rng = np.random.default_rng(2)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 500))), index=pd.bdate_range("2023-01-01", periods=500))
    sig = B.sma_signal(c, 3, 10)
    assert B.run_backtest(c, sig, 0, 0).metrics["total_return"] > B.run_backtest(c, sig, 30, 20).metrics["total_return"]


def test_walk_forward_windows_and_bootstrap():
    rng = np.random.default_rng(3)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1000))), index=pd.bdate_range("2020-01-01", periods=1000))
    wf = B.walk_forward(c, B.sma_signal, [{"fast": 5, "slow": 20}, {"fast": 10, "slow": 50}], train=504, test=126)
    assert len(wf["picks"]) == 3 and len(wf["returns"]) == 378
    flat = pd.Series(0.001, index=range(200))
    assert B.bootstrap_drawdown(flat, sims=50)["median_max_dd"] == 0
    bad = pd.Series(-0.01, index=range(100))
    assert B.bootstrap_drawdown(bad, sims=50, ruin_level=-0.3)["prob_dd_beyond_ruin"] == 1.0
    noise = pd.Series(rng.normal(0, 0.01, 500))
    bd = B.bootstrap_drawdown(noise, sims=300)
    assert bd["p99_worst_dd"] <= bd["p95_worst_dd"] <= bd["median_max_dd"] < 0


# ── alerts ──────────────────────────────────────────────────────────────────
def test_alert_rules():
    today = date(2026, 11, 2)
    snap = {"TCS": {"price": 3500, "band_lo": 3600, "band_hi": 3800, "day_high": 3520, "day_low": 3400, "forecast_daily_vol": 0.01}}
    rules = [A.Rule("a", "TCS", "price_below", 3600), A.Rule("b", "TCS", "range_breakout"),
             A.Rule("c", "TCS", "vol_spike", 2.0), A.Rule("d", "TCS", "event_soon", 7), A.Rule("e", "TCS", "price_above", 4000),
             A.Rule("f", "NOPE", "price_above", 1)]
    fired = A.evaluate(rules, snap, today, events=[{"date": date(2026, 11, 5), "symbol": "TCS", "type": "Q2 results"}])
    ids = {f.rule_id for f in fired}
    assert ids == {"a", "b", "c", "d"}  # e not hit, f has no data -> skipped, never guessed
    assert A.evaluate(rules, snap, today, already_fired={"a"})[0].rule_id != "a"
    ex = A.evaluate([A.Rule("x", "-", "expiry_soon", 3)], {}, today, expiries=[date(2026, 11, 3)])
    assert "expiry" in ex[0].message


def test_senders_with_mock_transport():
    def tg(req: httpx.Request):
        assert "sendMessage" in req.url.path and b"hello" in req.content
        return httpx.Response(200, json={"ok": True})
    assert A.TelegramSender("T", "1", httpx.Client(transport=httpx.MockTransport(tg))).send("hello")
    wa = A.WhatsAppCloudSender("T", "123", "9198", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    assert wa.send("x") is False


# ── screener ────────────────────────────────────────────────────────────────
def _bars(growth, n=300, vol_last=1.0):
    c = 100 * np.cumprod(np.full(n, 1 + growth))
    v = np.full(n, 1000.0)
    v[-1] *= vol_last
    return pd.DataFrame({"close": c, "volume": v})


def test_screener_metrics_and_filters():
    t = S.build_table({"UP": _bars(0.002, vol_last=5), "FLAT": _bars(0.0), "DOWN": _bars(-0.002)})
    assert t.loc["UP", "mom_rank"] == 1.0 and t.loc["DOWN", "mom_rank"] == pytest.approx(1 / 3)
    assert t.loc["UP", "volume_spike"] == pytest.approx(5.0)
    assert list(S.screen(t, mom_rank_min=0.9).index) == ["UP"]
    assert t.loc["UP", "pct_of_52w_high"] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        S.screen(t, bogus=1)


# ── risk limits ─────────────────────────────────────────────────────────────
def test_daily_limits():
    lim = R.DayLimits(max_loss=5000, max_trades=10, max_consecutive_losses=3)
    assert R.day_status([500, -1000], lim)["level"] == "ok"
    assert R.day_status([-3600], lim)["level"] == "warn"  # 72% of limit
    assert R.day_status([200, -2600, -2700], lim)["level"] == "stop"
    s = R.day_status([-100, -100, -100], lim)
    assert s["level"] == "stop" and s["losing_streak"] == 3
    c = R.checklist({"I know my stop before I enter": True})
    assert not c["pass"] and len(c["blocking"]) == 3


# ── calendar ────────────────────────────────────────────────────────────────
def test_expiries():
    assert C.monthly_expiry(2026, 10) == date(2026, 10, 27)
    assert C.monthly_expiry(2026, 10, {date(2026, 10, 27)}) == date(2026, 10, 26)  # holiday -> previous trading day
    assert C.monthly_expiry(2026, 11) == date(2026, 11, 24)
    assert C.monthly_expiry(2026, 10, weekday=3) == date(2026, 10, 29)  # BSE Thursday
    assert C.weekly_expiries(date(2026, 10, 1), date(2026, 10, 31)) == [date(2026, 10, d) for d in (6, 13, 20, 27)]


def test_events():
    ev = C.parse_events_csv("date,symbol,type,note\n2026-11-05,tcs,Q2 results,\n2026-12-01,infy,dividend,\n")
    assert [e["symbol"] for e in C.upcoming(ev, date(2026, 11, 2), 7)] == ["TCS"]
