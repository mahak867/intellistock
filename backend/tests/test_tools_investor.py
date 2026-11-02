from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.tools import announcements as AN
from backend.tools import factors as F
from backend.tools import fundamentals as FU
from backend.tools import planner as P
from backend.tools import portfolio as PF
from backend.tools import portrisk as PR
from backend.tools import tax as T


# ── portfolio ───────────────────────────────────────────────────────────────
def test_xirr_exact_and_none_cases():
    assert PF.xirr([(date(2021, 1, 1), -1000), (date(2022, 1, 1), 1100)]) == pytest.approx(0.10, abs=1e-6)
    flows = [(date(2020, 1, 1), -100), (date(2021, 1, 1), -100), (date(2022, 1, 1), 250)]
    r = PF.xirr(flows)
    t0 = flows[0][0]
    assert sum(v / (1 + r) ** ((d - t0).days / 365) for d, v in flows) == pytest.approx(0, abs=1e-6)
    assert PF.xirr([(date(2021, 1, 1), -1), (date(2022, 1, 1), -2)]) is None


def test_benchmark_xirr_hand_check():
    idx = pd.Series([100.0, 110.0], index=pd.to_datetime(["2021-01-01", "2022-01-01"]))
    assert PF.benchmark_xirr([(date(2021, 1, 1), -1000)], idx, 1200, date(2022, 1, 1)) == pytest.approx(0.10, abs=1e-6)


def test_holdings_allocation_and_correlation():
    h = PF.parse_holdings("Symbol,Qty,Average Price,Sector\nA,10,90,IT\nB,30,80,Banks\n")
    a = PF.allocation(h, {"A": 100.0, "B": 100.0})
    assert a["top1"] == pytest.approx(0.75) and a["hhi"] == pytest.approx(0.625) and a["effective_positions"] == pytest.approx(1.6)
    assert a["unrealised_pnl"] == pytest.approx(4000 - (900 + 2400)) and a["sector_weights"]["Banks"] == pytest.approx(0.75)
    assert PF.allocation(h, {"A": 1.0})["missing_prices"] == ["B"]
    x = pd.Series(np.random.default_rng(0).normal(size=50))
    c = PF.correlation(pd.DataFrame({"p": x, "q": 2 * x, "r": -x}))
    assert c["most_correlated"][0][2] == pytest.approx(1.0)
    with pytest.raises(ValueError):
        PF.parse_holdings("a,b\n1,2")


# ── portfolio risk ──────────────────────────────────────────────────────────
def test_parametric_range_hand_check():
    cov = pd.DataFrame(np.diag([1e-4, 1e-4]), index=["A", "B"], columns=["A", "B"])
    r = PR.parametric_range(pd.Series({"A": 0.5, "B": 0.5}), cov, 1_000_000, 5, 0.95)
    assert r["sd_pct"] == pytest.approx(np.sqrt(0.25 * 1e-4 * 2) * np.sqrt(5))
    assert r["var_amount"] == pytest.approx(1.6449 * 0.015811 * 1_000_000, rel=1e-3)


def test_ewma_cov_properties():
    a = pd.Series(np.random.default_rng(1).normal(0, 0.01, 500))
    c = PR.ewma_cov(pd.DataFrame({"a": a, "b": 2 * a}))
    assert c.loc["b", "b"] == pytest.approx(4 * c.loc["a", "a"]) and c.loc["a", "b"] == pytest.approx(c.loc["b", "a"])
    assert PR.ewma_cov(pd.DataFrame({"a": [0.01] * 50})).iloc[0, 0] == pytest.approx(0)


def test_historical_range_and_errors():
    r = pd.Series(np.random.default_rng(2).normal(0, 0.01, 800))
    h = PR.historical_range(r, 100000, 5)
    assert h["worst_pct"] >= h["expected_shortfall_pct"] >= h["var_pct"] > 0
    with pytest.raises(ValueError):
        PR.historical_range(r.iloc[:50], 1, 5)


def test_beta_and_stress():
    idx = pd.Series(np.random.default_rng(3).normal(0, 0.01, 300))
    b = PR.betas(pd.DataFrame({"S": 1.5 * idx}), idx)
    assert b["S"] == pytest.approx(1.5)
    res = PR.stress(pd.Series({"S": 1.0}), b, 100000)
    assert res[0]["portfolio_move"] == pytest.approx(-0.57) and res[0]["loss_amount"] == pytest.approx(57000)


# ── fundamentals ────────────────────────────────────────────────────────────
def test_quality_score():
    best = dict(roe=25, roce=30, debt_equity=0.0, profit_cagr_3y=30, cfo_to_pat=1.2, promoter_holding=70, pledge_pct=0)
    worst = dict(roe=0, roce=0, debt_equity=5, profit_cagr_3y=-5, cfo_to_pat=0, promoter_holding=10, pledge_pct=60)
    assert FU.quality_score(best)["score"] == 100 and FU.quality_score(worst)["score"] == 0
    only = FU.quality_score({"roe": 20})
    assert only["score"] == 100 and only["coverage_pct"] == 20 and "roce" in only["missing"]
    assert FU.quality_score({"roe": 12.5, "debt_equity": 1.05})["score"] == 50
    assert FU.quality_score({})["score"] is None


def test_valuation_and_holding_trend():
    v = FU.valuation_percentile(25, list(range(1, 101)))
    assert v["percentile"] == pytest.approx(0.25) and "cheap" in v["label"]
    assert FU.valuation_percentile(10, [1, 2])["percentile"] is None
    t = FU.holding_trend([{"promoter": 60, "pledge": 5}, {"promoter": 55, "pledge": 28}])
    assert len(t["flags"]) == 3


# ── factors ─────────────────────────────────────────────────────────────────
def _universe(drift_sd, seed, n=60, days=900):
    rng = np.random.default_rng(seed)
    mu = rng.normal(0, drift_sd, n)
    r = rng.normal(mu, 0.01, (days, n))
    return pd.DataFrame(100 * np.exp(np.cumsum(r, 0)), columns=[f"S{i}" for i in range(n)])


def test_factor_scores_shape():
    s = F.factor_scores(_universe(0.0005, 1))
    assert list(s.columns) == ["momentum", "low_vol", "composite"] and s.composite.is_monotonic_decreasing


def test_factor_edge_test_separates_real_from_noise():
    assert F.backtest_factor(_universe(0.0012, 5))["passes_edge"] is True   # persistent drifts: momentum works
    noise = [F.backtest_factor(_universe(0.0, s))["passes_edge"] for s in (11, 12, 13, 14, 15)]
    assert sum(noise) <= 1                                                    # pure noise rarely passes


# ── planner ─────────────────────────────────────────────────────────────────
def test_sip_math():
    assert P.sip_future_value(10000, 0.0, 10)["future_value"] == pytest.approx(1_200_000)
    r = P.monthly_rate(0.12)
    expect = 10000 * ((1 + r) ** 120 - 1) / r
    assert P.sip_future_value(10000, 0.12, 10)["future_value"] == pytest.approx(expect, rel=1e-9)
    assert P.sip_future_value(10000, 0.12, 10, at_start=True)["future_value"] == pytest.approx(expect * (1 + r))
    assert P.sip_future_value(10000, 0.0, 2, step_up_pct=10)["invested"] == pytest.approx(252000)
    assert P.required_sip(1_200_000, 10, 0.0, inflation=0.0)["monthly_sip"] == pytest.approx(10000, rel=1e-6)
    s = P.required_sip(5_000_000, 15, 0.12, inflation=0.06)
    assert P.sip_future_value(s["monthly_sip"], 0.12, 15)["future_value"] == pytest.approx(s["goal_in_future_rupees"], rel=1e-6)


def test_rebalance_and_dividends():
    assert P.rebalance({"A": 52000, "B": 48000}, {"A": .5, "B": .5})["needed"] is False
    r = P.rebalance({"A": 70000, "B": 30000}, {"A": .5, "B": .5})
    assert r["trades"] == {"A": -20000.0, "B": 20000.0}
    c = P.rebalance({"A": 52000, "B": 48000}, {"A": .5, "B": .5}, new_cash=20000)
    assert c["trades"] == {"A": 8000.0, "B": 12000.0}
    with pytest.raises(ValueError):
        P.rebalance({"A": 1}, {"A": .6})
    d = P.dividend_calendar({"TCS": 50}, [{"date": date(2026, 11, 20), "symbol": "TCS", "type": "dividend", "per_share": 10.0},
                                          {"date": date(2026, 11, 20), "symbol": "INFY", "type": "dividend", "per_share": 5.0}], date(2026, 11, 2))
    assert len(d) == 1 and d[0]["estimated_income"] == 500


# ── announcements ───────────────────────────────────────────────────────────
def test_classification_and_digest_order():
    assert AN.classify("Outcome of Board Meeting: Financial Results for Q2")["category"] == "Financial results"
    assert AN.classify("Resignation of Statutory Auditor")["importance"] == "high"
    assert AN.classify("Intimation of analyst meet")["category"] == "Meeting or schedule"
    assert AN.classify("Change in registered office")["category"] == "Other"
    d = AN.digest([{"symbol": "A", "title": "Analyst meet", "date": date(2026, 11, 2), "url": "u1"},
                   {"symbol": "B", "title": "Invocation of pledge by promoter", "date": date(2026, 11, 1), "url": "u2"}])
    assert d[0]["symbol"] == "B" and d[0]["url"] == "u2"


# ── tax (worked examples) ───────────────────────────────────────────────────
def _g(buys, sells):
    fills = [T.Fill(*b) for b in buys] + [T.Fill(*s) for s in sells]
    return T.tax_summary(T.realised_gains(fills))


def test_long_term_below_and_above_exemption():
    small = _g([("X", date(2023, 1, 10), "buy", 100, 100)], [("X", date(2025, 2, 1), "sell", 100, 300)])
    assert small["2024-25"]["ltcg"] == 20000 and small["2024-25"]["estimated_tax_with_cess"] == 0
    big = _g([("X", date(2022, 1, 10), "buy", 1000, 100)], [("X", date(2025, 2, 1), "sell", 1000, 400)])  # gain 300,000
    assert big["2024-25"]["estimated_tax_with_cess"] == pytest.approx((300000 - 125000) * 0.125 * 1.04)


def test_short_term_and_boundary_of_twelve_months():
    st = _g([("X", date(2025, 1, 1), "buy", 100, 100)], [("X", date(2025, 6, 1), "sell", 100, 600)])
    assert st["2025-26"]["estimated_tax_with_cess"] == pytest.approx(50000 * 0.20 * 1.04)
    on = T.realised_gains([T.Fill("X", date(2024, 8, 1), "buy", 1, 100), T.Fill("X", date(2025, 8, 1), "sell", 1, 200)])
    after = T.realised_gains([T.Fill("X", date(2024, 8, 1), "buy", 1, 100), T.Fill("X", date(2025, 8, 2), "sell", 1, 200)])
    assert on[0]["term"] == "short" and after[0]["term"] == "long"  # exactly 12 months is still short-term


def test_loss_set_off_rules():
    a = _g([("X", date(2025, 1, 1), "buy", 100, 100), ("Y", date(2022, 1, 1), "buy", 100, 500)],
           [("X", date(2025, 5, 1), "sell", 100, 600), ("Y", date(2025, 6, 1), "sell", 100, 200)])
    f = a["2025-26"]  # long-term loss cannot reduce the short-term gain
    assert f["estimated_tax_with_cess"] == pytest.approx(50000 * 0.2 * 1.04) and f["loss_to_carry_forward"]["long_term_loss"] == 30000
    b = _g([("Z", date(2022, 1, 1), "buy", 1000, 100), ("W", date(2025, 3, 1), "buy", 100, 500)],
           [("Z", date(2025, 6, 1), "sell", 1000, 300), ("W", date(2025, 6, 2), "sell", 100, 100)])
    assert b["2025-26"]["estimated_tax_with_cess"] == pytest.approx(35000 * 0.125 * 1.04)  # LT 200k - ST loss 40k - 125k


def test_grandfathering_and_errors():
    g = T.realised_gains([T.Fill("X", date(2017, 6, 1), "buy", 10, 100, fmv_31jan2018=150), T.Fill("X", date(2025, 1, 1), "sell", 10, 130)])
    assert g[0]["cost"] == 130 and g[0]["gain"] == 0  # cost = max(100, min(150, 130))
    with pytest.raises(ValueError, match="fmv_31jan2018"):
        T.realised_gains([T.Fill("X", date(2017, 6, 1), "buy", 1, 1), T.Fill("X", date(2025, 1, 1), "sell", 1, 2)])
    with pytest.raises(ValueError, match="before 23 Jul 2024"):
        T.realised_gains([T.Fill("X", date(2023, 1, 1), "buy", 1, 1), T.Fill("X", date(2024, 1, 1), "sell", 1, 2)])
    with pytest.raises(ValueError, match="more"):
        T.realised_gains([T.Fill("X", date(2025, 1, 1), "sell", 1, 2)])
    assert T.fy_of(date(2025, 3, 31)) == "2024-25" and T.fy_of(date(2025, 4, 1)) == "2025-26"
    assert T.ltcg_headroom(100000) == 25000 and T.ltcg_headroom(200000) == 0
