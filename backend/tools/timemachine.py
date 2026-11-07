"""Time Machine: replay a planned trade on the stock's own past days before risking money.

Adapted from trader-timemachine in Jake Schincariol's day-trader-skill
(https://github.com/Jakeschincariol/day-trader-skill, MIT licence, see THIRD_PARTY_NOTICES.md).
The original replays the rest of one US session on 5-minute bars. This version works on daily
NSE/BSE bars and a holding period of days, because that is the data IntelliStock has and the way
most of its users hold a position.

How it works:
  1. The pool: each of the last `lookback` days as (open, high, low, close) / previous close.
  2. One replay starts at the entry price and walks `horizon` days. Days are drawn in blocks of
     `block` consecutive past days (a block bootstrap), so calm and volatile stretches stay
     together instead of being shuffled into an average.
  3. Each day: if the open is already past the stop (a gap), the trade exits at the open, which is
     worse than the stop. Same for a gap through the target, which exits at the open. Otherwise the
     stop is checked before the target, so a day that touches both counts as the stop.
  4. Outcomes: "target", "stop", or "neither" (still open after `horizon` days, valued at the
     last close). R = profit / risk per share, after round-trip costs.
  5. History: the same distances (stop % and target % from the entry) applied from every past
     day's close, walked forward the same way. No randomness: what really happened.

The verdict compares the target's share of the replays that hit a side with the share that
breaks even at the plan's reward:risk, 1 / (1 + R). It describes this stock's past behaviour.
It is not a forecast: results, news and policy can do what the last two years never did.
"""
from __future__ import annotations

import random
import statistics
from dataclasses import dataclass

import pandas as pd

BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
SAMPLE_PATHS = 40
BAND_PATHS = 2000
HIST_BINS = 24
MIN_DAYS = 120
COIN_FLIP = 0.05
STRONG = 0.15
MANY_NEITHER = 0.40


@dataclass
class Plan:
    entry: float
    stop: float
    target: float
    side: str = "long"          # "long" or "short"
    horizon: int = 10           # trading days to hold at most
    cost_bps: float = 15.0      # round-trip charges and slippage, basis points of the entry

    def check(self) -> None:
        if self.side not in ("long", "short"):
            raise ValueError("side must be long or short")
        if min(self.entry, self.stop, self.target) <= 0:
            raise ValueError("entry, stop and target must be positive")
        long = self.side == "long"
        if (self.stop >= self.entry) if long else (self.stop <= self.entry):
            raise ValueError(f"the stop must be {'below' if long else 'above'} the entry for a {self.side} trade")
        if (self.target <= self.entry) if long else (self.target >= self.entry):
            raise ValueError(f"the target must be {'above' if long else 'below'} the entry for a {self.side} trade")
        if not 1 <= self.horizon <= 120:
            raise ValueError("horizon must be 1 to 120 trading days")
        if not 0 <= self.cost_bps <= 500:
            raise ValueError("cost_bps must be 0 to 500")

    @property
    def long(self) -> bool:
        return self.side == "long"

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def r_target(self) -> float:
        return abs(self.target - self.entry) / self.risk


def pct(a: list[float], q: float) -> float:
    return a[min(len(a) - 1, int(q * len(a)))]


def build_pool(df: pd.DataFrame, lookback: int = 500) -> list[tuple[float, float, float, float]]:
    """Each day as (open, high, low, close) divided by the previous close, oldest first."""
    d = df[["open", "high", "low", "close"]].dropna().tail(lookback + 1)
    prev = d["close"].shift(1)
    r = d.div(prev, axis=0).dropna()
    r = r[(r > 0).all(axis=1)]
    return [tuple(map(float, row)) for row in r.itertuples(index=False)]


def _walk(bars, plan: Plan):
    """One path through `bars` (absolute o/h/l/c). Returns (outcome, exit_price, closes)."""
    long, stop, target = plan.long, plan.stop, plan.target
    closes = []
    for o, h, l, c in bars:
        if long:
            if o <= stop:
                return "stop", o, closes + [c]
            if o >= target:
                return "target", o, closes + [c]
            if l <= stop:
                return "stop", stop, closes + [c]
            if h >= target:
                return "target", target, closes + [c]
        else:
            if o >= stop:
                return "stop", o, closes + [c]
            if o <= target:
                return "target", o, closes + [c]
            if h >= stop:
                return "stop", stop, closes + [c]
            if l <= target:
                return "target", target, closes + [c]
        closes.append(c)
    return "neither", closes[-1] if closes else plan.entry, closes


def _r(plan: Plan, exit_price: float) -> float:
    move = (exit_price - plan.entry) if plan.long else (plan.entry - exit_price)
    cost = plan.entry * plan.cost_bps / 1e4
    return (move - cost) / plan.risk


def _draw(rng: random.Random, pool, n: int, block: int):
    out = []
    while len(out) < n:
        s = rng.randrange(0, max(1, len(pool) - block + 1))
        out.extend(pool[s:s + block])
    return out[:n]


def simulate(pool, plan: Plan, replays: int = 10000, seed: int = 19, block: int = 5) -> dict:
    plan.check()
    if len(pool) < MIN_DAYS:
        raise ValueError(f"need at least {MIN_DAYS} past days of prices, got {len(pool)}")
    rng = random.Random(seed)
    outcomes, finals, Rs, paths, gaps = [], [], [], [], 0
    for n in range(replays):
        p, bars = plan.entry, []
        for o, h, l, c in _draw(rng, pool, plan.horizon, block):
            bars.append((p * o, p * h, p * l, p * c))
            p *= c
        oc, ex, closes = _walk(bars, plan)
        if oc != "neither" and ex not in (plan.stop, plan.target):
            gaps += 1
        outcomes.append(oc)
        finals.append(bars[-1][3])
        Rs.append(_r(plan, ex))
        if n < SAMPLE_PATHS:
            paths.append([round(plan.entry, 2)] + [round(b[3], 2) for b in bars])
    cnt = {k: outcomes.count(k) for k in ("target", "stop", "neither")}
    green = sum(1 for r in Rs if r > 0)

    rng = random.Random(seed)
    allp = []
    for _ in range(BAND_PATHS):
        p, path = plan.entry, [plan.entry]
        for _o, _h, _l, c in _draw(rng, pool, plan.horizon, block):
            p *= c
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(plan.horizon + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([round(pct(col, q), 2) for q in BAND_Q])

    srt = sorted(finals)
    lo, hi = pct(srt, 0.01), pct(srt, 0.99)
    w = (hi - lo) / HIST_BINS
    bins = [0] * HIST_BINS
    for x in srt:
        b = int((x - lo) / w) if w > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    mc = {
        "replays": replays, "seed": seed, "block_days": block, "horizon_days": plan.horizon, "pool_days": len(pool),
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["neither"] / replays, 4), "p_green": round(green / replays, 4),
        "p_gap_exit": round(gaps / replays, 4),
        "median_final": round(pct(srt, 0.5), 2), "p5_final": round(pct(srt, 0.05), 2), "p95_final": round(pct(srt, 0.95), 2),
        "avg_R": round(statistics.mean(Rs), 3), "r_at_target": round(plan.r_target, 3),
        "worst_R_5pct": round(pct(sorted(Rs), 0.05), 2),
        "bands": bands, "band_quantiles": list(BAND_Q), "sample_paths": paths,
        "hist": {"lo": round(lo, 2), "hi": round(hi, 2), "bins": bins},
    }
    mc["verdict"] = verdict(mc)
    mc["notes"] = verdict_notes(mc)
    return mc


def history_replay(df: pd.DataFrame, plan: Plan, lookback: int = 500) -> dict:
    """The same stop and target distances, started from the close of every past day."""
    plan.check()
    d = df[["open", "high", "low", "close"]].dropna().tail(lookback + plan.horizon)
    rows = list(d.itertuples())
    stop_f, tgt_f = plan.stop / plan.entry, plan.target / plan.entry
    trades = []
    for i in range(len(rows) - plan.horizon):
        e = float(rows[i].close)
        p = Plan(e, e * stop_f, e * tgt_f, plan.side, plan.horizon, plan.cost_bps)
        bars = [(float(r.open), float(r.high), float(r.low), float(r.close)) for r in rows[i + 1:i + 1 + plan.horizon]]
        oc, ex, _ = _walk(bars, p)
        trades.append({"date": str(pd.Timestamp(rows[i].Index).date()), "entry": round(e, 2),
                       "outcome": oc, "R": round(_r(p, ex), 2)})
    n = len(trades)
    if not n:
        return {"starts": 0}
    Rs = [t["R"] for t in trades]
    return {
        "starts": n, "from": trades[0]["date"], "to": trades[-1]["date"],
        "target": sum(t["outcome"] == "target" for t in trades), "stop": sum(t["outcome"] == "stop" for t in trades),
        "neither": sum(t["outcome"] == "neither" for t in trades), "green": sum(r > 0 for r in Rs),
        "avg_R": round(statistics.mean(Rs), 3), "recent": trades[-15:],
        "note": "Overlapping start days share most of their path, so these are not independent trades.",
    }


def lean(mc: dict):
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0:
        return None
    r = mc.get("r_at_target") or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    return share - even, share, even


def verdict(mc: dict) -> str:
    pt, ps, h = mc["p_target"], mc["p_stop"], mc["horizon_days"]
    lv = lean(mc)
    if lv is None:
        return f"No replay reached the target or the stop within {h} days: the price on day {h} decides every one."
    d, share, even = lv
    r = mc.get("r_at_target") or 1.0
    one_r = abs(r - 1.0) < 0.005
    if abs(d) < COIN_FLIP:
        head = "Close to a coin flip" if one_r else "Close to break-even"
    elif abs(d) < STRONG:
        head = "Leans toward the target" if d > 0 else "Leans toward the stop"
    else:
        head = "Strongly toward the target" if d > 0 else "Strongly toward the stop"
    odds = f"target first {100 * pt:.1f}% vs stop first {100 * ps:.1f}%"
    if one_r:
        return f"{head}: {odds}."
    return (f"{head}: at {r:.2f}R the target has to come first in {100 * even:.0f}% of the replays that hit a side "
            f"to break even; it did in {100 * share:.0f}% ({odds}).")


def verdict_notes(mc: dict) -> list[str]:
    notes = []
    lv = lean(mc)
    h = mc["horizon_days"]
    if mc["p_neither"] > MANY_NEITHER and lv is not None:
        notes.append(f"{100 * mc['p_neither']:.1f}% of the replays hit neither within {h} days; the price on day {h} decides those.")
    avg = mc.get("avg_R")
    if lv and abs(lv[0]) >= COIN_FLIP and avg and (avg > 0) != (lv[0] > 0):
        notes.append(f"Average R is {avg:+.3f} all the same: costs and the replays that hit neither pull it the other way.")
    if mc.get("p_gap_exit", 0) > 0.02:
        notes.append(f"{100 * mc['p_gap_exit']:.1f}% of the replays gapped past a level at the open, so the fill was worse "
                     "(or better) than the price you set. A stop-loss order cannot prevent that.")
    notes.append("Built from this stock's own past days. It is not a prediction and not advice.")
    return notes
