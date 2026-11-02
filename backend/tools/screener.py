"""Screener over daily bars. Pure metrics: every column is a plain, checkable number."""
from __future__ import annotations

import numpy as np
import pandas as pd


def metrics_for(df: pd.DataFrame) -> dict:
    c = df["close"]
    r = np.log(c).diff()
    vol20 = r.rolling(20).std()
    hist = vol20.dropna().tail(252)
    out = {
        "price": float(c.iloc[-1]),
        "vol_20d_ann": float(vol20.iloc[-1] * np.sqrt(252)) if len(hist) else None,
        "vol_pct_rank": float((hist <= vol20.iloc[-1]).mean()) if len(hist) >= 60 else None,
        "mom_12_1": float(c.iloc[-22] / c.iloc[-253] - 1) if len(c) >= 253 else None,
        "ret_1m": float(c.iloc[-1] / c.iloc[-22] - 1) if len(c) >= 22 else None,
        "pct_of_52w_high": float(c.iloc[-1] / c.tail(252).max()),
        "pct_above_52w_low": float(c.iloc[-1] / c.tail(252).min() - 1),
        "volume_spike": float(df["volume"].iloc[-1] / df["volume"].iloc[-21:-1].mean()) if "volume" in df and len(df) > 21 else None,
    }
    if "delivery_pct" in df and len(df) > 21:
        out["delivery_spike"] = float(df["delivery_pct"].iloc[-1] / df["delivery_pct"].iloc[-21:-1].mean())
    return out


def build_table(universe: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = {s: metrics_for(d) for s, d in universe.items() if len(d) >= 60}
    t = pd.DataFrame(rows).T
    if "mom_12_1" in t:
        t["mom_rank"] = t["mom_12_1"].rank(pct=True)
    return t


def screen(table: pd.DataFrame, **flt) -> pd.DataFrame:
    """flt keys: <col>_min / <col>_max, e.g. mom_rank_min=0.8, volume_spike_min=2, vol_pct_rank_max=0.2."""
    t = table
    for k, v in flt.items():
        if k.endswith("_min"):
            t = t[t[k[:-4]] >= v]
        elif k.endswith("_max"):
            t = t[t[k[:-4]] <= v]
        else:
            raise ValueError(f"filter must end with _min or _max: {k}")
    return t
