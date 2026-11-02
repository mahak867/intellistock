"""Trade journal: pair broker fills into round trips (FIFO) and analyse them honestly."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import pandas as pd

COLS = {  # canonical -> accepted header names (lowercase)
    "symbol": ("symbol", "tradingsymbol", "scrip", "instrument"),
    "time": ("order_execution_time", "trade_time", "datetime", "time", "timestamp"),
    "date": ("trade_date", "date"),
    "side": ("trade_type", "side", "buy/sell", "transaction_type", "type"),
    "qty": ("quantity", "qty"),
    "price": ("price", "trade_price", "avg_price", "rate"),
}


def parse_tradebook(csv_text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text))
    low = {c.lower().strip(): c for c in df.columns}
    out = {}
    for canon, names in COLS.items():
        for n in names:
            if n in low:
                out[canon] = df[low[n]]
                break
    for need in ("symbol", "side", "qty", "price"):
        if need not in out:
            raise ValueError(f"CSV is missing a '{need}' column. Found: {list(df.columns)}")
    t = out.get("time")
    when = pd.to_datetime(t if t is not None else out.get("date"), errors="coerce")
    if when is None or when.isna().all():
        raise ValueError("CSV needs a date or time column that can be read")
    res = pd.DataFrame({
        "symbol": out["symbol"].astype(str).str.upper().str.strip(),
        "time": when,
        "side": out["side"].astype(str).str.lower().str.strip().map(lambda s: "buy" if s.startswith("b") else "sell"),
        "qty": pd.to_numeric(out["qty"], errors="coerce"),
        "price": pd.to_numeric(out["price"], errors="coerce"),
    }).dropna()
    return res.sort_values("time", kind="stable").reset_index(drop=True)


@dataclass
class Trade:
    symbol: str
    direction: str
    qty: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry: float
    exit: float
    pnl: float


def pair_trades(fills: pd.DataFrame, cost_per_trade: float = 0.0) -> list[Trade]:
    """FIFO matching per symbol; handles long and short and partial fills.
    Open leftovers are ignored (they are not realised)."""
    trades: list[Trade] = []
    books: dict[str, list[list]] = {}
    for r in fills.itertuples(index=False):
        book = books.setdefault(r.symbol, [])
        sign = 1 if r.side == "buy" else -1
        qty = float(r.qty)
        while qty > 1e-9 and book and book[0][0] * sign < 0:  # opposite side open
            lot = book[0]
            m = min(qty, abs(lot[0]))
            direction = "long" if lot[0] > 0 else "short"
            pnl = (r.price - lot[1]) * m if direction == "long" else (lot[1] - r.price) * m
            trades.append(Trade(r.symbol, direction, m, lot[2], r.time, lot[1], float(r.price), pnl - cost_per_trade))
            lot[0] -= math.copysign(m, lot[0])
            qty -= m
            if abs(lot[0]) < 1e-9:
                book.pop(0)
        if qty > 1e-9:
            book.append([sign * qty, float(r.price), r.time])
    return trades


def analyse(trades: list[Trade], starting_equity: float = 0.0) -> dict:
    if not trades:
        return {"trades": 0}
    df = pd.DataFrame([t.__dict__ for t in trades]).sort_values("exit_time")
    wins, losses = df[df.pnl > 0], df[df.pnl <= 0]
    win_rate = len(wins) / len(df)
    avg_win = float(wins.pnl.mean()) if len(wins) else 0.0
    avg_loss = float(losses.pnl.mean()) if len(losses) else 0.0
    gross_win, gross_loss = float(wins.pnl.sum()), float(-losses.pnl.sum())
    curve = starting_equity + df.pnl.cumsum()
    peak = curve.cummax().clip(lower=starting_equity if starting_equity > 0 else None)
    dd = (curve - peak)
    by_hour = df.assign(h=df.entry_time.dt.hour).groupby("h").pnl.agg(["count", "sum"]).rename(columns={"sum": "pnl"})
    by_dow = df.assign(d=df.entry_time.dt.day_name()).groupby("d").pnl.agg(["count", "sum"]).rename(columns={"sum": "pnl"})
    return {
        "trades": len(df),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": (avg_win / abs(avg_loss)) if avg_loss else None,
        "expectancy": win_rate * avg_win + (1 - win_rate) * avg_loss,
        "profit_factor": (gross_win / gross_loss) if gross_loss else None,
        "total_pnl": float(df.pnl.sum()),
        "max_drawdown": float(dd.min()),
        "worst_trade": float(df.pnl.min()),
        "best_trade": float(df.pnl.max()),
        "by_hour": {int(k): {"trades": int(v["count"]), "pnl": float(v["pnl"])} for k, v in by_hour.iterrows()},
        "by_weekday": {k: {"trades": int(v["count"]), "pnl": float(v["pnl"])} for k, v in by_dow.iterrows()},
    }


def behaviour_flags(trades: list[Trade], revenge_minutes: int = 30, oversize_x: float = 2.0) -> list[dict]:
    """Patterns that cost traders money. Flags, not accusations: the rule is shown with each."""
    flags: list[dict] = []
    if not trades:
        return flags
    df = pd.DataFrame([t.__dict__ for t in trades]).sort_values("entry_time").reset_index(drop=True)
    med = df.qty.median()
    for i, r in df.iterrows():
        if r.qty > oversize_x * med and len(df) >= 5:
            flags.append({"type": "over_sizing", "symbol": r.symbol, "time": str(r.entry_time),
                          "detail": f"size {r.qty:g} is {r.qty / med:.1f}x your median of {med:g}"})
    for i in range(1, len(df)):
        p, c = df.iloc[i - 1], df.iloc[i]
        gap = (c.entry_time - p.exit_time).total_seconds() / 60
        if p.pnl < 0 and 0 <= gap <= revenge_minutes and c.qty > p.qty:
            flags.append({"type": "revenge_trade", "symbol": c.symbol, "time": str(c.entry_time),
                          "detail": f"re-entered {gap:.0f} min after a loss, with a larger size ({p.qty:g} to {c.qty:g})"})
    return flags


def whatif_vol_stop(trades: list[Trade], daily_vol: dict[str, float], k: float = 1.5, hold_days: int = 5,
                    paths: dict[str, pd.DataFrame] | None = None) -> dict:
    """Replay: cap each loss at a volatility stop, if intraday/daily low/high data is supplied
    for the holding window. Trades without data are skipped and counted, never guessed."""
    if not paths:
        return {"replayed": 0, "skipped": len(trades), "reason": "price data needed for each symbol"}
    base = new = 0.0
    n = skipped = 0
    for t in trades:
        px, v = paths.get(t.symbol), daily_vol.get(t.symbol)
        if px is None or v is None:
            skipped += 1
            continue
        win = px.loc[t.entry_time:t.exit_time]
        if win.empty:
            skipped += 1
            continue
        dist = t.entry * k * v * math.sqrt(hold_days)
        stop = t.entry - dist if t.direction == "long" else t.entry + dist
        hit = (win["low"].min() <= stop) if t.direction == "long" else (win["high"].max() >= stop)
        exit_px = stop if hit else t.exit
        pnl = ((exit_px - t.entry) if t.direction == "long" else (t.entry - exit_px)) * t.qty
        base += t.pnl
        new += pnl
        n += 1
    return {"replayed": n, "skipped": skipped, "actual_pnl": base, "with_vol_stop_pnl": new, "difference": new - base}
