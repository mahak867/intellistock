"""Turn raw symbol-day rows into one clean, split-adjusted OHLCV series plus an honest quality report."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

SERIES_PREF = ["EQ", "BE", "BZ", "SM", "ST"]
CA_TOL = 0.005          # exchange previous close vs our previous close: beyond this, something was adjusted
BIG_JUMP = 0.15         # a gap this large is treated as a corporate action even if days are missing around it


def _pick_series(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["_r"] = g["series"].map({s: i for i, s in enumerate(SERIES_PREF)}).fillna(99)
    return g.sort_values(["date", "_r"]).drop_duplicates("date", keep="first").drop(columns="_r").set_index("date")


def build_ohlcv(rows: pd.DataFrame, symbol: str, adjust: bool = True, today: date | None = None,
                dividends: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """rows: long frame from the store. Returns (ohlcv, quality). Raises KeyError if the symbol is unknown.
    With `dividends` (symbol, ex_date, amount) the series becomes total-return: earlier prices are scaled down so a
    dividend is not read as a price drop. Splits and dividends are both multiplicative, so the order does not matter."""
    g = rows[rows["symbol"] == symbol]
    if g.empty:
        raise KeyError(symbol)
    series_seen = sorted(g["series"].unique())
    d = _pick_series(g)
    d[["open", "high", "low", "close", "prev_close", "volume"]] = d[["open", "high", "low", "close", "prev_close", "volume"]].astype(float)
    issues: list[str] = []

    bad = (d["high"] < d["low"]) | (d["close"] > d["high"] * 1.0001) | (d["close"] < d["low"] * 0.9999) | (d[["open", "high", "low", "close"]] <= 0).any(axis=1)
    if bad.any():
        issues.append(f"dropped {int(bad.sum())} rows where high, low and close disagree")
        d = d[~bad]

    # market-wide trading days: a symbol-day gap inside this set means the stock itself was missing
    mkt_days = pd.DatetimeIndex(sorted(rows["date"].unique()))
    span = mkt_days[(mkt_days >= d.index[0]) & (mkt_days <= d.index[-1])]
    sym_missing = int(len(span.difference(d.index)))
    if sym_missing:
        issues.append(f"{sym_missing} trading days missing for this stock (suspension, or a failed download)")

    actions: list[dict] = []
    div_applied: list[str] = []
    if adjust and len(d) > 1:
        prev_close_ours = d["close"].shift(1)
        ratio = (d["prev_close"] / prev_close_ours).replace([np.inf, -np.inf], np.nan)
        pos = {t: i for i, t in enumerate(mkt_days)}
        for t, r in ratio.dropna().items():
            if abs(r - 1) <= CA_TOL:
                continue
            i = d.index.get_loc(t)
            prev_day = d.index[i - 1]
            gap_days = pos.get(t, 0) - pos.get(prev_day, 0) - 1  # market days between the two rows
            if gap_days > 0 and abs(r - 1) < BIG_JUMP:
                issues.append(f"{t.date()}: previous close differs by {abs(r - 1):.1%} but {gap_days} day(s) are missing, so it was NOT adjusted")
                continue
            actions.append({"date": str(t.date()), "factor": float(r)})
        div_applied, div_skipped = [], []
        if dividends is not None and len(dividends):
            ca = {a["date"]: a["factor"] for a in actions}
            for _, dv in dividends[dividends["symbol"] == symbol].iterrows():
                ex = dv["ex_date"]
                if ex <= d.index[0] or ex > d.index[-1]:
                    continue
                ex_day = d.index[d.index.searchsorted(ex)]  # first trading day on or after the ex-date
                prev_px = d["close"].iloc[d.index.get_loc(ex_day) - 1]  # raw close the day before: same units as the dividend
                f = 1.0 - dv["amount"] / prev_px
                if not 0.2 < f < 1.0:
                    div_skipped.append(f"{ex.date()}: dividend {dv['amount']} against price {prev_px:.2f} looks wrong, skipped")
                    continue
                seen = ca.get(str(ex_day.date()))
                if seen is not None and abs(seen - f) < 0.01:
                    div_skipped.append(f"{ex.date()}: the exchange already adjusted its previous close for this dividend, not counted twice")
                    continue
                actions.append({"date": str(ex_day.date()), "factor": float(f), "kind": "dividend"})
                div_applied.append(str(ex_day.date()))
            issues.extend(div_skipped)
        for a in sorted(actions, key=lambda x: x["date"], reverse=True):
            cut = pd.Timestamp(a["date"])
            m = d.index < cut
            d.loc[m, ["open", "high", "low", "close"]] *= a["factor"]
            if a.get("kind") != "dividend":
                d.loc[m, "volume"] /= a["factor"]

    out = d[["open", "high", "low", "close", "volume"]].astype(float)
    last = out.index[-1].date()
    stale = ((today or date.today()) - last).days
    if stale > 5:
        issues.append(f"latest price is {stale} days old")
    if (out["volume"] == 0).mean() > 0.05:
        issues.append("many zero-volume days: thinly traded")
    q = {"symbol": symbol, "rows": int(len(out)), "first": str(out.index[0].date()), "last": str(last), "stale_days": int(stale),
         "series": series_seen, "corporate_actions_adjusted": [a for a in actions if a.get("kind") != "dividend"], "issues": issues,
         "dividends_applied": len(div_applied), "total_return": bool(div_applied),
         "adjusted_for": ("splits, bonus and the exchange's own previous-close changes" +
                          (f", plus {len(div_applied)} cash dividends (total return)" if div_applied else "; no dividend file loaded, so dividends are NOT added back"))}
    return out, q
