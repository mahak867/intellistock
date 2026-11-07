"""Pre-trade risk check and position sizing against your own rules.

Adapted from trader-risk (check.py) and trader-budget (size.py) in Jake Schincariol's
day-trader-skill (https://github.com/Jakeschincariol/day-trader-skill, MIT licence, see
THIRD_PARTY_NOTICES.md). Changed for IntelliStock: rupees, NSE hours in IST, F&O lot sizes,
long and short, delivery or intraday, and a drawdown table showing what a fall in this one
stock does to the whole portfolio. Nothing here places an order.

Maximum quantity = the smallest of
  max loss       max_loss / risk per share (entry minus stop, plus costs)
  position cap   (portfolio x max_position_pct - what you already hold of it) / entry
  cash           (cash - cash buffer) / entry          (delivery buys only)
rounded down to whole lots. The limit that sets it is named, so you know which rule binds.

What blocks the trade: a blocked ticker, a stop on the wrong side, no stop when one is required,
a quantity over the maximum, reward:risk under your minimum, or the market being closed (NSE,
Monday to Friday 09:15 to 15:30 IST; exchange holidays are not checked).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
OPEN, CLOSE = time(9, 15), time(15, 30)
FALLS = (0.10, 0.20, 0.30, 0.50)


@dataclass
class Rules:
    portfolio_value: float                  # everything you hold plus cash, rupees
    cash: float | None = None               # free cash; None skips the cash limit
    cash_buffer_pct: float = 10.0           # of the portfolio, never spent
    max_position_pct: float = 20.0          # one stock, of the portfolio
    max_loss: float | None = None           # rupees per trade; None = risk_pct of the portfolio
    risk_pct: float = 1.0
    min_reward_risk: float = 1.5
    require_stop: bool = True
    blocked: list[str] = field(default_factory=list)
    no_entries_after: str = "15:15"         # IST, for intraday


@dataclass
class Trade:
    symbol: str
    entry: float
    stop: float | None = None
    target: float | None = None
    qty: int | None = None                  # None = just size it
    side: str = "long"
    product: str = "delivery"               # delivery | intraday
    lot_size: int = 1
    held_value: float = 0.0                 # what you already hold of this stock, rupees
    cost_per_share: float = 0.0             # round-trip charges per share


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def market_window(now: datetime, product: str, rules: Rules) -> tuple[str | None, str | None]:
    """(block, warning) for the NSE session. Holidays are not known here, so they only warn."""
    t = now.astimezone(IST)
    if t.weekday() >= 5:
        return f"the market is closed ({t:%A})", None
    if not OPEN <= t.time() <= CLOSE:
        return f"the market is closed at {t:%H:%M} IST (open 09:15 to 15:30)", None
    if product == "intraday":
        h, m = map(int, rules.no_entries_after.split(":"))
        if t.time() > time(h, m):
            return f"no new intraday entries after {rules.no_entries_after} IST (square-off is near)", None
    return None, "Exchange holidays are not checked: confirm the market is open today."


def check(trade: Trade, rules: Rules, now: datetime | None = None) -> dict:
    if trade.entry <= 0 or rules.portfolio_value <= 0:
        raise ValueError("entry and portfolio value must be positive")
    if trade.side not in ("long", "short"):
        raise ValueError("side must be long or short")
    if trade.product not in ("delivery", "intraday"):
        raise ValueError("product must be delivery or intraday")
    if trade.lot_size < 1:
        raise ValueError("lot size must be at least 1")
    long = trade.side == "long"
    sym = trade.symbol.strip().upper()
    block, warn = [], []

    if sym in {b.strip().upper() for b in rules.blocked}:
        block.append(f"{sym} is on your blocked list")
    if long is False and trade.product == "delivery":
        block.append("you cannot short shares for delivery in India; use intraday or futures")

    risk = None
    if trade.stop is None:
        (block if rules.require_stop else warn).append("no stop: the loss on this trade has no limit")
    elif (trade.stop >= trade.entry) if long else (trade.stop <= trade.entry):
        block.append(f"the stop {trade.stop:g} is on the wrong side of the entry {trade.entry:g} for a {trade.side} trade")
    else:
        risk = abs(trade.entry - trade.stop) + trade.cost_per_share

    rr = None
    if trade.target is not None and risk:
        reward = (trade.target - trade.entry) if long else (trade.entry - trade.target)
        if reward <= 0:
            block.append("the target is on the wrong side of the entry: the move has already happened")
        else:
            rr = round((reward - trade.cost_per_share) / risk, 2)
            if rr < rules.min_reward_risk:
                block.append(f"reward:risk {rr} is under your minimum {rules.min_reward_risk}")
    elif trade.target is None:
        warn.append("no target: reward:risk is not checked")

    max_loss = rules.max_loss if rules.max_loss else rules.portfolio_value * rules.risk_pct / 100
    limits = []
    if risk:
        limits.append({"name": "max loss", "rupees": round(max_loss), "shares": int(max_loss // risk),
                       "how": f"{_inr(max_loss)} / {risk:.2f} risk a share"})
    room = rules.portfolio_value * rules.max_position_pct / 100 - trade.held_value
    limits.append({"name": "position cap", "rupees": round(max(room, 0)), "shares": max(int(room // trade.entry), 0),
                   "how": f"{rules.max_position_pct:g}% of {_inr(rules.portfolio_value)}"
                          + (f" minus {_inr(trade.held_value)} already held" if trade.held_value else "")})
    if rules.cash is not None and trade.product == "delivery" and long:
        free = rules.cash - rules.portfolio_value * rules.cash_buffer_pct / 100
        limits.append({"name": "cash", "rupees": round(max(free, 0)), "shares": max(int(free // trade.entry), 0),
                       "how": f"{_inr(rules.cash)} cash minus the {rules.cash_buffer_pct:g}% buffer"})
    raw = min(l["shares"] for l in limits)
    max_qty = raw - raw % trade.lot_size
    bound = min(limits, key=lambda l: l["shares"])["name"]
    for l in limits:
        l["binds"] = l["name"] == bound
    if max_qty == 0:
        block.append(f"zero shares fit: the {bound} limit allows less than one {'lot' if trade.lot_size > 1 else 'share'}")

    qty = trade.qty if trade.qty is not None else max_qty
    if trade.qty is not None:
        if trade.qty % trade.lot_size:
            block.append(f"quantity {trade.qty} is not a whole number of lots of {trade.lot_size}")
        if trade.qty > max_qty:
            block.append(f"quantity {trade.qty} is over the {max_qty} your {bound} limit allows")

    if now is not None:
        b, w = market_window(now, trade.product, rules)
        if b:
            block.append(b)
        if w:
            warn.append(w)

    value = qty * trade.entry
    total_in_stock = value + trade.held_value
    loss_at_stop = qty * risk if risk else None
    falls = [{"move_against_you": f"{int(f * 100)}%", "loss": round(total_in_stock * f),
              "of_portfolio_pct": round(100 * total_in_stock * f / rules.portfolio_value, 2)} for f in FALLS]
    if total_in_stock / rules.portfolio_value > 0.25:
        warn.append(f"{sym} would be {100 * total_in_stock / rules.portfolio_value:.0f}% of everything you own; "
                    "one bad result moves your whole portfolio")

    return {
        "symbol": sym, "pass": not block, "blocking": block, "warnings": warn,
        "qty": qty, "max_qty": max_qty, "bound_by": bound, "limits": limits,
        "position_value": round(value), "position_pct": round(100 * total_in_stock / rules.portfolio_value, 2),
        "risk_per_share": round(risk, 2) if risk else None, "loss_at_stop": round(loss_at_stop) if loss_at_stop else None,
        "loss_at_stop_pct": round(100 * loss_at_stop / rules.portfolio_value, 2) if loss_at_stop else None,
        "reward_risk": rr, "if_it_moves_against_you": falls,
        "note": "A gap at the open can fill a stop well below its price. Checks your own rules only; not advice.",
    }
