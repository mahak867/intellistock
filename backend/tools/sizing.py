"""Position size and stop calculator. Risk-first: you choose the rupees at risk."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class SizeResult:
    side: str
    entry: float
    stop: float
    shares: int
    lots: int | None
    risk_per_share: float
    risk_amount: float
    position_value: float
    targets: dict[str, float]
    notes: list[str]


def volatility_stop(entry: float, daily_vol: float, side: str = "long", k: float = 1.5, hold_days: int = 5) -> float:
    """Stop placed k standard deviations of the expected move away, outside normal noise.
    daily_vol is a fraction (0.018 = 1.8%/day). Move = k * vol * sqrt(hold_days)."""
    if entry <= 0 or daily_vol <= 0 or k <= 0 or hold_days < 1:
        raise ValueError("entry, daily_vol, k must be positive and hold_days >= 1")
    dist = entry * k * daily_vol * math.sqrt(hold_days)
    return entry - dist if side == "long" else entry + dist


def position_size(
    entry: float,
    stop: float,
    risk_amount: float | None = None,
    capital: float | None = None,
    risk_pct: float | None = None,
    side: str = "long",
    lot_size: int = 1,
    reward_multiples: tuple[float, ...] = (1.0, 2.0, 3.0),
    cost_per_share_roundtrip: float = 0.0,
    max_position_pct_of_capital: float | None = None,
) -> SizeResult:
    if side not in ("long", "short"):
        raise ValueError("side must be long or short")
    if entry <= 0 or stop <= 0:
        raise ValueError("entry and stop must be positive")
    if (side == "long" and stop >= entry) or (side == "short" and stop <= entry):
        raise ValueError("stop must be below entry for long, above entry for short")
    if risk_amount is None:
        if capital is None or risk_pct is None:
            raise ValueError("give risk_amount, or capital and risk_pct")
        risk_amount = capital * risk_pct / 100.0
    if risk_amount <= 0 or lot_size < 1:
        raise ValueError("risk_amount must be positive and lot_size >= 1")

    rps = abs(entry - stop) + cost_per_share_roundtrip  # costs count as risk
    raw = math.floor(risk_amount / rps)
    notes: list[str] = []
    shares = (raw // lot_size) * lot_size
    if shares == 0 and raw > 0:
        notes.append(f"Risk budget is too small for one lot of {lot_size}.")
    if max_position_pct_of_capital and capital:
        cap_shares = math.floor(capital * max_position_pct_of_capital / 100 / entry)
        cap_shares = (cap_shares // lot_size) * lot_size
        if shares > cap_shares:
            shares = cap_shares
            notes.append(f"Reduced to keep the position within {max_position_pct_of_capital:g}% of capital.")
    if capital and shares * entry > capital:
        notes.append("Position value exceeds capital: leverage or margin is needed.")
    sign = 1 if side == "long" else -1
    r = abs(entry - stop)
    targets = {f"{m:g}R": round(entry + sign * m * r, 2) for m in reward_multiples}
    return SizeResult(
        side=side, entry=entry, stop=stop, shares=shares,
        lots=(shares // lot_size if lot_size > 1 else None),
        risk_per_share=round(rps, 4), risk_amount=round(shares * rps, 2),
        position_value=round(shares * entry, 2), targets=targets, notes=notes,
    )


def range_targets(entry: float, lo: float, hi: float, side: str = "long") -> dict[str, float]:
    """Targets and risk/reward from a forecast band: reward = distance to the far edge."""
    reward = (hi - entry) if side == "long" else (entry - lo)
    risk = (entry - lo) if side == "long" else (hi - entry)
    if risk <= 0 or reward <= 0:
        return {"reward": round(reward, 2), "risk": round(risk, 2), "rr": 0.0}
    return {"reward": round(reward, 2), "risk": round(risk, 2), "rr": round(reward / risk, 2)}
