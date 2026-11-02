import math

import pandas as pd
import pytest

from backend.tools import journal as J
from backend.tools.sizing import position_size, range_targets, volatility_stop


# ── sizing (numbers checked by hand) ─────────────────────────────────────────
def test_basic_long_sizing():
    r = position_size(entry=500, stop=490, risk_amount=5000)
    assert r.shares == 500 and r.risk_amount == 5000 and r.position_value == 250000
    assert r.targets == {"1R": 510.0, "2R": 520.0, "3R": 530.0}


def test_short_and_lots():
    r = position_size(entry=100, stop=104, risk_amount=5000, side="short", lot_size=75)
    # 5000/4 = 1250 -> floor to lots of 75 = 1200 (16 lots); targets move down
    assert r.shares == 1200 and r.lots == 16 and r.targets["2R"] == 92.0


def test_costs_count_as_risk_and_capital_cap():
    r = position_size(entry=500, stop=490, risk_amount=5000, cost_per_share_roundtrip=1.0)
    assert r.shares == 454  # 5000/11
    r2 = position_size(entry=500, stop=490, capital=100000, risk_pct=5, max_position_pct_of_capital=50)
    assert r2.shares == 100 and any("within 50%" in n for n in r2.notes)


def test_sizing_rejects_bad_input():
    for kw in (dict(entry=100, stop=101, risk_amount=100), dict(entry=0, stop=1, risk_amount=1),
               dict(entry=100, stop=99, risk_amount=-5)):
        with pytest.raises(ValueError):
            position_size(**kw)
    with pytest.raises(ValueError):
        position_size(entry=100, stop=99)


def test_volatility_stop_and_range_targets():
    s = volatility_stop(1000, 0.02, "long", k=1.5, hold_days=4)  # 1000*1.5*0.02*2 = 60
    assert math.isclose(s, 940)
    assert volatility_stop(1000, 0.02, "short", 1.5, 4) == pytest.approx(1060)
    assert range_targets(100, 95, 110) == {"reward": 10, "risk": 5, "rr": 2.0}


# ── journal ──────────────────────────────────────────────────────────────────
CSV = """symbol,trade_date,order_execution_time,trade_type,quantity,price
INFY,2026-10-01,2026-10-01T09:20:00,buy,10,1500
INFY,2026-10-01,2026-10-01T10:00:00,sell,10,1520
TCS,2026-10-01,2026-10-01T10:30:00,buy,5,4000
TCS,2026-10-01,2026-10-01T11:00:00,sell,5,3960
TCS,2026-10-01,2026-10-01T11:10:00,buy,10,3950
TCS,2026-10-01,2026-10-01T12:00:00,sell,10,3940
SBIN,2026-10-02,2026-10-02T09:30:00,sell,20,800
SBIN,2026-10-02,2026-10-02T09:45:00,buy,20,790
"""


def test_pairing_and_stats():
    t = J.pair_trades(J.parse_tradebook(CSV))
    pnl = [round(x.pnl, 2) for x in t]
    assert pnl == [200.0, -200.0, -100.0, 200.0]  # INFY +, TCS -, TCS -, SBIN short +
    a = J.analyse(t)
    assert a["trades"] == 4 and a["win_rate"] == 0.5
    assert a["expectancy"] == pytest.approx(25.0) and a["profit_factor"] == pytest.approx(400 / 300)
    assert a["max_drawdown"] == pytest.approx(-300.0)  # 200 -> 0 -> -100: peak 200, low -100


def test_partial_fills_fifo():
    csv = "symbol,time,side,qty,price\nA,2026-01-01 09:15,buy,10,100\nA,2026-01-01 09:20,buy,10,110\nA,2026-01-01 09:30,sell,15,120\n"
    t = J.pair_trades(J.parse_tradebook(csv))
    assert [(x.qty, x.pnl) for x in t] == [(10.0, 200.0), (5.0, 50.0)]


def test_revenge_and_oversize_flags():
    t = J.pair_trades(J.parse_tradebook(CSV))
    f = J.behaviour_flags(t, revenge_minutes=30)
    assert any(x["type"] == "revenge_trade" and x["symbol"] == "TCS" for x in f)  # 10 > 5 within 10 min of a loss


def test_bad_csv_is_rejected_clearly():
    with pytest.raises(ValueError, match="missing a 'price'"):
        J.parse_tradebook("symbol,side,qty,date\nA,buy,1,2026-01-01")


def test_whatif_skips_without_data_instead_of_guessing():
    t = J.pair_trades(J.parse_tradebook(CSV))
    assert J.whatif_vol_stop(t, {})["replayed"] == 0
    idx = pd.date_range("2026-10-01 09:15", periods=200, freq="min")
    px = pd.DataFrame({"low": 1400.0, "high": 1600.0}, index=idx)
    r = J.whatif_vol_stop(t[:1], {"INFY": 0.01}, k=1, hold_days=1, paths={"INFY": px})
    assert r["replayed"] == 1 and r["with_vol_stop_pnl"] != r["actual_pnl"]
