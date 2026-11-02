"""SIP and goal planner, rebalancing helper, dividend calendar."""
from __future__ import annotations

from datetime import date


def monthly_rate(annual_effective: float) -> float:
    return (1 + annual_effective) ** (1 / 12) - 1


def sip_future_value(monthly: float, annual_rate: float, years: int, step_up_pct: float = 0.0, at_start: bool = False) -> dict:
    """Effective annual rate converted to a monthly rate. Payments at month end unless at_start.
    step_up_pct raises the monthly amount once a year."""
    r = monthly_rate(annual_rate)
    bal, invested, amt = 0.0, 0.0, monthly
    for m in range(years * 12):
        if m and m % 12 == 0:
            amt *= 1 + step_up_pct / 100
        if at_start:
            bal = (bal + amt) * (1 + r)
        else:
            bal = bal * (1 + r) + amt
        invested += amt
    return {"future_value": bal, "invested": invested, "gain": bal - invested}


def required_sip(goal_today: float, years: int, annual_rate: float, inflation: float = 0.06, step_up_pct: float = 0.0) -> dict:
    """Monthly SIP needed to reach a goal stated in today's money. Solved by bisection."""
    target = goal_today * (1 + inflation) ** years
    lo, hi = 0.0, target
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if sip_future_value(mid, annual_rate, years, step_up_pct)["future_value"] < target:
            lo = mid
        else:
            hi = mid
    return {"monthly_sip": 0.5 * (lo + hi), "goal_in_future_rupees": target, "inflation": inflation}


def rebalance(values: dict[str, float], targets: dict[str, float], band: float = 0.05, new_cash: float = 0.0) -> dict:
    """Trades to return to target weights. Only acts if any holding drifts beyond `band`
    (absolute weight, 0.05 = 5 points). With new_cash, buys underweights first and sells nothing."""
    if abs(sum(targets.values()) - 1.0) > 1e-6:
        raise ValueError("target weights must sum to 1")
    total = sum(values.values()) + new_cash
    cur = {k: values.get(k, 0.0) / (total - new_cash) if total - new_cash else 0.0 for k in targets}
    drift = {k: cur[k] - targets[k] for k in targets}
    if new_cash == 0 and max(abs(v) for v in drift.values()) <= band:
        return {"needed": False, "drift": drift, "trades": {}}
    want = {k: targets[k] * total - values.get(k, 0.0) for k in targets}
    if new_cash > 0:
        under = {k: max(v, 0.0) for k, v in want.items()}
        s = sum(under.values())
        trades = {k: (v / s * new_cash if s else 0.0) for k, v in under.items()}
    else:
        trades = want
    return {"needed": True, "drift": drift, "trades": {k: round(v, 2) for k, v in trades.items()}}


def dividend_calendar(holdings: dict[str, float], events: list[dict], today: date, days: int = 60) -> list[dict]:
    """events: {date, symbol, type='dividend', per_share}. Estimated income = shares x per_share."""
    out = []
    for e in events:
        if e.get("type") == "dividend" and 0 <= (e["date"] - today).days <= days and e["symbol"] in holdings:
            out.append({**e, "shares": holdings[e["symbol"]], "estimated_income": holdings[e["symbol"]] * e["per_share"]})
    return sorted(out, key=lambda x: x["date"])
