from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.tools import pretrade as PT
from backend.tools import timemachine as TM


def bars(n=400, drift=0.0, vol=0.015, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(drift + vol * rng.standard_normal(n)))
    o = np.r_[100, c[:-1]] * (1 + 0.002 * rng.standard_normal(n))
    h = np.maximum(o, c) * (1 + abs(0.005 * rng.standard_normal(n)))
    lo = np.minimum(o, c) * (1 - abs(0.005 * rng.standard_normal(n)))
    return pd.DataFrame({"open": o, "high": h, "low": lo, "close": c}, index=pd.bdate_range("2024-01-01", periods=n))


# ── time machine ────────────────────────────────────────────────────────────
def test_pool_is_ratios_to_previous_close():
    df = pd.DataFrame({"open": [10, 11], "high": [10, 12], "low": [10, 10.5], "close": [10, 11.5]})
    assert TM.build_pool(df) == [(1.1, 1.2, 1.05, 1.15)]


def test_walk_stop_first_and_gaps():
    p = TM.Plan(100, 95, 110, horizon=3)
    assert TM._walk([(100, 111, 94, 100)], p)[:2] == ("stop", 95)        # touches both: the stop counts
    assert TM._walk([(90, 92, 88, 91)], p)[:2] == ("stop", 90)           # gap through the stop fills at the open
    assert TM._walk([(101, 103, 99, 102)] * 3, p)[0] == "neither"
    s = TM.Plan(100, 105, 90, side="short")
    assert TM._walk([(100, 101, 89, 95)], s)[:2] == ("target", 90)


def test_simulate_is_reproducible_and_sane():
    pool = TM.build_pool(bars())
    p = TM.Plan(100, 95, 110, horizon=10, cost_bps=0)
    a, b = TM.simulate(pool, p, replays=2000), TM.simulate(pool, p, replays=2000)
    assert a["p_target"] == b["p_target"]
    assert a["p_target"] + a["p_stop"] + a["p_neither"] == pytest.approx(1, abs=1e-3)
    assert len(a["bands"]) == 11 and a["bands"][0] == [100.0] * 5
    assert a["p5_final"] <= a["median_final"] <= a["p95_final"]
    assert a["verdict"] and a["notes"][-1].startswith("Built from")


def test_trend_shows_up_and_costs_cost():
    up = TM.build_pool(bars(drift=0.004, seed=3))
    p = TM.Plan(100, 95, 105, horizon=10, cost_bps=0)
    r = TM.simulate(up, p, replays=2000)
    assert r["p_target"] > r["p_stop"] and "target" in r["verdict"]
    dear = TM.simulate(up, TM.Plan(100, 95, 105, horizon=10, cost_bps=100), replays=2000)
    assert dear["avg_R"] < r["avg_R"]


def test_history_replay_and_validation():
    h = TM.history_replay(bars(), TM.Plan(100, 95, 110, horizon=5))
    assert h["starts"] > 300 and h["target"] + h["stop"] + h["neither"] == h["starts"]
    for bad in (TM.Plan(100, 101, 110), TM.Plan(100, 95, 99), TM.Plan(100, 95, 110, side="short")):
        with pytest.raises(ValueError):
            bad.check()
    with pytest.raises(ValueError):
        TM.simulate(TM.build_pool(bars(50)), TM.Plan(100, 95, 110))


# ── pre-trade check ─────────────────────────────────────────────────────────
MON_11 = datetime(2026, 11, 9, 5, 30, tzinfo=timezone.utc)  # Monday 11:00 IST


def test_size_picks_the_tightest_limit():
    r = PT.check(PT.Trade("tcs", 3000, 2940, 3150), PT.Rules(1_000_000, cash=500_000), MON_11)
    # max loss 10,000 / 60 = 166; cap 200,000 / 3000 = 66; cash (500k - 100k) / 3000 = 133
    assert r["max_qty"] == 66 and r["bound_by"] == "position cap" and r["pass"]
    assert r["reward_risk"] == 2.5 and r["symbol"] == "TCS"
    assert r["if_it_moves_against_you"][0]["loss"] == round(66 * 3000 * 0.1)


def test_blocks_and_lots():
    r = PT.check(PT.Trade("X", 100, 101, 110, qty=50), PT.Rules(100_000), MON_11)
    assert not r["pass"] and any("wrong side" in b for b in r["blocking"])
    r = PT.check(PT.Trade("X", 100, 98, 101), PT.Rules(100_000), MON_11)
    assert any("reward:risk" in b for b in r["blocking"])
    r = PT.check(PT.Trade("NIFTY", 100, 98, 106, lot_size=75), PT.Rules(1_000_000, max_position_pct=100), MON_11)
    assert r["max_qty"] % 75 == 0 and r["max_qty"] == 5000 - 5000 % 75
    r = PT.check(PT.Trade("X", 100, 102, 90, side="short"), PT.Rules(100_000), MON_11)
    assert any("cannot short" in b for b in r["blocking"])
    r = PT.check(PT.Trade("BAD", 100, 98, 106), PT.Rules(100_000, blocked=["bad"]), MON_11)
    assert any("blocked" in b for b in r["blocking"])


def test_market_hours():
    sat = datetime(2026, 11, 7, 6, 0, tzinfo=timezone.utc)
    late = datetime(2026, 11, 9, 9, 55, tzinfo=timezone.utc)   # 15:25 IST
    assert any("closed" in b for b in PT.check(PT.Trade("X", 100, 98, 106), PT.Rules(100_000), sat)["blocking"])
    r = PT.check(PT.Trade("X", 100, 98, 106, product="intraday"), PT.Rules(100_000), late)
    assert any("intraday" in b for b in r["blocking"])


# ── HTTP ────────────────────────────────────────────────────────────────────
def test_endpoints():
    c = TestClient(app)
    r = c.post("/api/v1/tools/risk/pretrade", json={"symbol": "TCS", "entry": 3000, "stop": 2940, "target": 3150,
                                                     "portfolio_value": 1000000, "check_market_hours": False})
    assert r.status_code == 200 and r.json()["max_qty"] == 66
    r = c.get("/api/v1/market/time-machine/TCS", params={"entry": 100, "stop": 95, "target": 110, "horizon": 5})
    assert r.status_code in (200, 404), r.text
    if r.status_code == 200:
        j = r.json()
        assert {"replays", "history", "plan", "last_close"} <= set(j)
    assert c.get("/api/v1/market/time-machine/TCS", params={"entry": 100, "stop": 105, "target": 110}).status_code == 422
    r = c.get("/api/v1/market/time-machine/TCS", params={"stop_pct": 3, "target_pct": 6})
    if r.status_code == 200:
        pl = r.json()["plan"]
        assert pl["entry_from"] == "last close" and pl["stop"] < pl["entry"] < pl["target"]
    assert c.get("/api/v1/market/time-machine/TCS", params={"target_pct": 6}).status_code in (404, 422)
