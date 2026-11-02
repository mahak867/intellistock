"""Daily loss limit and pre-trade checklist: guardrails that run before the bad day gets worse."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DayLimits:
    max_loss: float                 # positive rupees
    max_trades: int | None = None
    max_consecutive_losses: int | None = 3
    warn_at: float = 0.7            # fraction of max_loss


def day_status(trade_pnls: list[float], lim: DayLimits) -> dict:
    """trade_pnls: realised P&L of today's closed trades in order."""
    pnl = sum(trade_pnls)
    loss = max(-pnl, 0.0)
    streak = 0
    for p in reversed(trade_pnls):
        if p < 0:
            streak += 1
        else:
            break
    reasons: list[str] = []
    level = "ok"
    if loss >= lim.max_loss:
        level = "stop"
        reasons.append(f"Daily loss limit reached: down {loss:,.0f} of {lim.max_loss:,.0f}. Stop trading today.")
    elif loss >= lim.warn_at * lim.max_loss:
        level = "warn"
        reasons.append(f"Down {loss:,.0f}, {loss / lim.max_loss:.0%} of your {lim.max_loss:,.0f} limit.")
    if lim.max_consecutive_losses and streak >= lim.max_consecutive_losses:
        level = "stop"
        reasons.append(f"{streak} losing trades in a row. Take a break before the next one.")
    if lim.max_trades and len(trade_pnls) >= lim.max_trades:
        level = "stop"
        reasons.append(f"{len(trade_pnls)} trades today reached your limit of {lim.max_trades}.")
    return {"level": level, "pnl": pnl, "loss_used_pct": loss / lim.max_loss if lim.max_loss else None,
            "losing_streak": streak, "reasons": reasons}


DEFAULT_CHECKLIST = [
    ("I know my stop before I enter", True),
    ("Risk on this trade is within my per-trade limit", True),
    ("There is no result, expiry or policy event today that I did not plan for", True),
    ("I am not trying to win back an earlier loss", True),
    ("The setup matches my written plan", False),
]


def checklist(answers: dict[str, bool], items=DEFAULT_CHECKLIST) -> dict:
    missing = [t for t, req in items if req and not answers.get(t, False)]
    soft = [t for t, req in items if not req and not answers.get(t, False)]
    return {"pass": not missing, "blocking": missing, "warnings": soft}
