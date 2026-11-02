"""Options: Black-Scholes pricing and Greeks, implied volatility, payoff builder,
put-call ratio, max pain, and implied-vs-expected volatility.

European exercise (NSE index and stock options). r and q are continuous rates.
Margin is NOT computed: short-option margin comes from SPAN + exposure and must be read
from your broker's margin calculator. Only the premium outlay for long options is exact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

N = math.erf


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _d1d2(s, k, t, r, q, sigma):
    d1 = (math.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
    return d1, d1 - sigma * math.sqrt(t)


def bs_price(s: float, k: float, t: float, r: float, sigma: float, kind: str = "call", q: float = 0.0) -> float:
    if kind not in ("call", "put"):
        raise ValueError("kind must be call or put")
    if t <= 0 or sigma <= 0:  # at expiry / zero vol: intrinsic (discounted forward for sigma=0)
        return max(s - k, 0.0) if kind == "call" else max(k - s, 0.0)
    d1, d2 = _d1d2(s, k, t, r, q, sigma)
    if kind == "call":
        return s * math.exp(-q * t) * _cdf(d1) - k * math.exp(-r * t) * _cdf(d2)
    return k * math.exp(-r * t) * _cdf(-d2) - s * math.exp(-q * t) * _cdf(-d1)


def greeks(s: float, k: float, t: float, r: float, sigma: float, kind: str = "call", q: float = 0.0) -> dict:
    """delta, gamma, vega (per 1 vol point), theta (per calendar day), rho (per 1% rate)."""
    if t <= 0 or sigma <= 0:
        itm = (s > k) if kind == "call" else (s < k)
        return {"delta": (1.0 if kind == "call" else -1.0) if itm else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1, d2 = _d1d2(s, k, t, r, q, sigma)
    sq = math.sqrt(t)
    eq, er = math.exp(-q * t), math.exp(-r * t)
    gamma = eq * _pdf(d1) / (s * sigma * sq)
    vega = s * eq * _pdf(d1) * sq / 100.0
    if kind == "call":
        delta = eq * _cdf(d1)
        theta = (-s * eq * _pdf(d1) * sigma / (2 * sq) - r * k * er * _cdf(d2) + q * s * eq * _cdf(d1)) / 365.0
        rho = k * t * er * _cdf(d2) / 100.0
    else:
        delta = -eq * _cdf(-d1)
        theta = (-s * eq * _pdf(d1) * sigma / (2 * sq) + r * k * er * _cdf(-d2) - q * s * eq * _cdf(-d1)) / 365.0
        rho = -k * t * er * _cdf(-d2) / 100.0
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


def implied_vol(price: float, s: float, k: float, t: float, r: float, kind: str = "call", q: float = 0.0) -> float | None:
    """Bisection on [0.1%, 500%]. Returns None if the price is outside no-arbitrage bounds."""
    if t <= 0 or price <= 0:
        return None
    lo, hi = 1e-3, 5.0
    if not (bs_price(s, k, t, r, lo, kind, q) - 1e-9 <= price <= bs_price(s, k, t, r, hi, kind, q) + 1e-9):
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if bs_price(s, k, t, r, mid, kind, q) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


@dataclass
class Leg:
    kind: str       # call | put | future/stock handled as "fut"
    strike: float
    premium: float  # per unit paid (+) or received (-) is set by qty sign, premium stays positive
    qty: int        # + long, - short (in units, not lots)


def payoff_at(legs: list[Leg], spot: float) -> float:
    total = 0.0
    for lg in legs:
        if lg.kind == "call":
            v = max(spot - lg.strike, 0.0)
        elif lg.kind == "put":
            v = max(lg.strike - spot, 0.0)
        elif lg.kind == "fut":
            v = spot - lg.strike
        else:
            raise ValueError("kind must be call, put or fut")
        premium = 0.0 if lg.kind == "fut" else lg.premium
        total += lg.qty * (v - premium)
    return total


def payoff_curve(legs: list[Leg], lo: float, hi: float, steps: int = 200) -> dict:
    """P&L at expiry. Payoff is piecewise linear with kinks at strikes, so extremes are found
    exactly at spot = 0, the strikes and the far end; the plotted range is only for drawing."""
    xs = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    ys = [payoff_at(legs, x) for x in xs]
    top = max([hi] + [lg.strike for lg in legs]) * 1.5
    nodes = sorted({0.0, top, *[lg.strike for lg in legs]})
    vals = [payoff_at(legs, x) for x in nodes]
    slope_up = payoff_at(legs, top + 1) - payoff_at(legs, top)
    bes: list[float] = []
    for a, b in zip(nodes, nodes[1:]):
        fa, fb = payoff_at(legs, a), payoff_at(legs, b)
        if fa == 0:
            bes.append(a)
        elif fa * fb < 0:
            bes.append(a + (b - a) * (-fa) / (fb - fa))
    if vals[-1] == 0 and slope_up != 0:
        bes.append(nodes[-1])
    return {
        "x": xs, "pnl": ys,
        "breakevens": sorted({round(x, 4) for x in bes if x > 0}),
        "max_profit": None if slope_up > 0 else max(vals),
        "max_loss": None if slope_up < 0 else min(vals),
    }


def net_premium(legs: list[Leg]) -> float:
    """Cash paid (+) or received (-) up front. Exact for long-only; short margin is separate."""
    return sum(lg.qty * lg.premium for lg in legs if lg.kind != "fut")


def put_call_ratio(chain: list[dict]) -> dict:
    """chain rows: {strike, call_oi, put_oi}. PCR by open interest."""
    c = sum(r["call_oi"] for r in chain)
    p = sum(r["put_oi"] for r in chain)
    return {"pcr_oi": (p / c) if c else None, "call_oi": c, "put_oi": p}


def max_pain(chain: list[dict]) -> float | None:
    """Strike at which total option-holder payoff at expiry is lowest (writers' pain minimum)."""
    if not chain:
        return None
    best, best_loss = None, None
    for cand in (r["strike"] for r in chain):
        loss = sum(r["call_oi"] * max(cand - r["strike"], 0) + r["put_oi"] * max(r["strike"] - cand, 0) for r in chain)
        if best_loss is None or loss < best_loss:
            best, best_loss = cand, loss
    return best


def iv_vs_expected(implied_annual: float, expected_daily_vol: float, rich_above: float = 1.15, cheap_below: float = 0.9) -> dict:
    """Compare option-implied vol with the model's expected vol (daily -> annual by sqrt(252)).
    Ratio > rich_above: options price in more movement than expected (rich: selling edge in theory, risky).
    Ratio < cheap_below: priced for less movement than expected (cheap)."""
    exp_annual = expected_daily_vol * math.sqrt(252.0)
    ratio = implied_annual / exp_annual if exp_annual > 0 else float("nan")
    verdict = "rich" if ratio > rich_above else "cheap" if ratio < cheap_below else "fair"
    return {"implied_annual": implied_annual, "expected_annual": exp_annual, "ratio": ratio, "verdict": verdict,
            "note": "Verdict compares volatility only. It is not a trade signal: earnings, events and skew matter."}
