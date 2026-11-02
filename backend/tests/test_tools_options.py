import math

import pytest

from backend.tools.options import (Leg, bs_price, greeks, implied_vol, iv_vs_expected, max_pain,
                                   net_premium, payoff_at, payoff_curve, put_call_ratio)


def test_black_scholes_textbook_value():
    # Hull: S=42, K=40, r=10%, sigma=20%, T=0.5 -> call 4.76, put 0.81
    assert bs_price(42, 40, 0.5, 0.10, 0.20, "call") == pytest.approx(4.76, abs=0.01)
    assert bs_price(42, 40, 0.5, 0.10, 0.20, "put") == pytest.approx(0.81, abs=0.01)


def test_put_call_parity_and_dividend():
    s, k, t, r, v, q = 100, 95, 0.75, 0.065, 0.3, 0.02
    c, p = bs_price(s, k, t, r, v, "call", q), bs_price(s, k, t, r, v, "put", q)
    assert c - p == pytest.approx(s * math.exp(-q * t) - k * math.exp(-r * t), abs=1e-9)


def test_greeks_match_finite_differences():
    s, k, t, r, v = 100, 100, 0.5, 0.06, 0.25
    g = greeks(s, k, t, r, v, "call")
    h = 0.01
    delta = (bs_price(s + h, k, t, r, v) - bs_price(s - h, k, t, r, v)) / (2 * h)
    gamma = (bs_price(s + h, k, t, r, v) - 2 * bs_price(s, k, t, r, v) + bs_price(s - h, k, t, r, v)) / h**2
    vega = (bs_price(s, k, t, r, v + 0.0001) - bs_price(s, k, t, r, v - 0.0001)) / 0.0002 / 100
    theta = (bs_price(s, k, t - 1 / 365, r, v) - bs_price(s, k, t, r, v))
    assert g["delta"] == pytest.approx(delta, abs=1e-4) and g["gamma"] == pytest.approx(gamma, abs=1e-4)
    assert g["vega"] == pytest.approx(vega, abs=1e-4) and g["theta"] == pytest.approx(theta, abs=2e-3)
    assert greeks(s, k, t, r, v, "put")["delta"] == pytest.approx(g["delta"] - 1, abs=1e-9)


def test_implied_vol_roundtrip_and_bounds():
    for kind in ("call", "put"):
        p = bs_price(24500, 24800, 20 / 365, 0.065, 0.14, kind)
        assert implied_vol(p, 24500, 24800, 20 / 365, 0.065, kind) == pytest.approx(0.14, abs=1e-5)
    assert implied_vol(1e9, 100, 100, 1, 0.05) is None  # impossible price
    assert implied_vol(0.0, 100, 100, 1, 0.05) is None


def test_payoffs_and_breakevens():
    long_call = [Leg("call", 100, 5, 1)]
    c = payoff_curve(long_call, 50, 150)
    assert c["max_loss"] == -5 and c["max_profit"] is None and c["breakevens"] == [105.0]
    # bull call spread: long 100c @5, short 110c @2 -> max profit 7, max loss -3, BE 103
    spread = [Leg("call", 100, 5, 1), Leg("call", 110, 2, -1)]
    s = payoff_curve(spread, 50, 160)
    assert (s["max_profit"], s["max_loss"]) == (7, -3) and s["breakevens"] == [103.0]
    assert net_premium(spread) == 3
    # short straddle has unlimited loss
    st = [Leg("call", 100, 4, -1), Leg("put", 100, 4, -1)]
    z = payoff_curve(st, 50, 150)
    assert z["max_loss"] is None and z["max_profit"] == 8 and z["breakevens"] == [92.0, 108.0]
    assert payoff_at(spread, 120) == 7


def test_pcr_and_max_pain():
    chain = [{"strike": 100, "call_oi": 100, "put_oi": 300},
             {"strike": 110, "call_oi": 200, "put_oi": 200},
             {"strike": 120, "call_oi": 300, "put_oi": 100}]
    assert put_call_ratio(chain)["pcr_oi"] == pytest.approx(1.0)
    assert max_pain(chain) == 110  # hand check: losses 100->(200*10+300*20)=8000, 110->(100*10+100*10)=2000, 120->(100*20+200*10+200*10)=6000


def test_iv_vs_expected():
    r = iv_vs_expected(0.20, 0.01)  # expected annual = 0.1587
    assert r["verdict"] == "rich" and r["ratio"] == pytest.approx(0.20 / (0.01 * math.sqrt(252)))
    assert iv_vs_expected(0.15, 0.0095)["verdict"] == "fair"
    assert iv_vs_expected(0.10, 0.0095)["verdict"] == "cheap"
