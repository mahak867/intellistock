"""Factor ranking (momentum, low volatility, optional quality) with a built-in edge test.
Ranks are only worth showing if the long-short spread is positive net of costs AND statistically
distinguishable from zero. `passes_edge` encodes that rule."""
from __future__ import annotations

import numpy as np
import pandas as pd


def factor_scores(close: pd.DataFrame, quality: pd.Series | None = None) -> pd.DataFrame:
    """close: columns = symbols, index = dates (>= ~260 rows). Scores are cross-sectional z-scores."""
    mom = close.iloc[-22] / close.iloc[-253] - 1  # 12-1 momentum: skip the last month
    vol = np.log(close).diff().tail(252).std()
    z = lambda s: (s - s.mean()) / s.std(ddof=0)  # noqa: E731
    df = pd.DataFrame({"momentum": z(mom), "low_vol": z(-vol)})
    if quality is not None:
        df["quality"] = z(quality.reindex(df.index))
    df["composite"] = df.mean(axis=1)
    return df.sort_values("composite", ascending=False)


def backtest_factor(close: pd.DataFrame, lookback: int = 252, skip: int = 21, hold: int = 21,
                    quantile: float = 0.2, cost_bps: float = 20.0) -> dict:
    """Monthly rebalance: long top quantile by 12-1 momentum, equal weight, versus the equal-weight
    universe. Costs charged on turnover. Non-overlapping periods keep the t-stat honest."""
    ex, bench_r = [], []
    prev: set[str] = set()
    for t in range(lookback + skip, len(close) - hold, hold):
        mom = close.iloc[t - skip] / close.iloc[t - skip - lookback + skip] - 1
        top = set(mom.nlargest(max(1, int(len(mom) * quantile))).index)
        fwd = close.iloc[t + hold] / close.iloc[t] - 1
        turnover = len(top ^ prev) / (2 * max(len(top), 1)) * 2  # fraction of book traded (both sides)
        long_r = fwd[list(top)].mean() - turnover * cost_bps / 10_000
        ex.append(long_r - fwd.mean())
        bench_r.append(fwd.mean())
        prev = top
    ex_s = pd.Series(ex)
    n = len(ex_s)
    t_stat = float(ex_s.mean() / (ex_s.std(ddof=1) / np.sqrt(n))) if n > 2 and ex_s.std(ddof=1) > 0 else 0.0
    return {"periods": n, "mean_excess_per_period": float(ex_s.mean()), "hit_rate": float((ex_s > 0).mean()),
            "t_stat": t_stat, "passes_edge": bool(ex_s.mean() > 0 and t_stat > 2.0)}
