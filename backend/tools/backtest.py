"""Backtester: daily bars, next-bar execution (no look-ahead), costs and slippage, walk-forward
parameter selection, and a block-bootstrap worst-case drawdown simulation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


@dataclass
class Result:
    returns: pd.Series
    equity: pd.Series
    position: pd.Series
    metrics: dict


def _metrics(r: pd.Series, pos: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    n = max(len(r), 1)
    years = n / 252
    dd = eq / eq.cummax() - 1
    sd = r.std(ddof=1)
    return {
        "total_return": float(eq.iloc[-1] - 1) if n else 0.0,
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1) if n and years > 0 and eq.iloc[-1] > 0 else None,
        "ann_vol": float(sd * np.sqrt(252)) if n > 1 else 0.0,
        "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd and sd > 0 else 0.0,
        "max_drawdown": float(dd.min()),
        "time_in_market": float((pos != 0).mean()),
        "turnover_per_year": float(pos.diff().abs().sum() / years) if years > 0 else 0.0,
        "trades": int((pos.diff().abs() > 0).sum()),
    }


def run_backtest(close: pd.Series, signal: pd.Series, cost_bps: float = 10.0, slippage_bps: float = 5.0) -> Result:
    """signal[t] in [-1, 1] is decided using data up to the close of day t and is held from t+1.
    Cost per unit of turnover = (cost_bps + slippage_bps) / 10_000."""
    sig = signal.reindex(close.index).fillna(0.0).clip(-1, 1)
    pos = sig.shift(1).fillna(0.0)  # trade at the next bar: no look-ahead
    ret = close.pct_change().fillna(0.0)
    turn = pos.diff().abs().fillna(pos.abs())
    strat = pos * ret - turn * (cost_bps + slippage_bps) / 10_000
    eq = (1 + strat).cumprod()
    return Result(strat, eq, pos, _metrics(strat, pos))


def sma_signal(close: pd.Series, fast: int, slow: int) -> pd.Series:
    return (close.rolling(fast).mean() > close.rolling(slow).mean()).astype(float)


def walk_forward(close: pd.Series, make_signal: Callable[..., pd.Series], grid: list[dict],
                 train: int = 504, test: int = 126, cost_bps: float = 10.0, slippage_bps: float = 5.0) -> dict:
    """Pick the best parameters (by Sharpe) on each train window, then trade them on the next
    unseen test window. Stitched out-of-sample result is the honest number."""
    oos, oos_pos, picks = [], [], []
    start = train
    while start + test <= len(close):
        tr, te = close.iloc[:start], close.iloc[: start + test]
        best, best_s = None, -1e9
        for p in grid:
            s = run_backtest(tr.iloc[-train:], make_signal(tr.iloc[-train:], **p), cost_bps, slippage_bps).metrics["sharpe"]
            if s > best_s:
                best, best_s = p, s
        full = run_backtest(te, make_signal(te, **best), cost_bps, slippage_bps)
        oos.append(full.returns.iloc[-test:])
        oos_pos.append(full.position.iloc[-test:])
        picks.append({"start": str(close.index[start]), "params": best, "train_sharpe": best_s})
        start += test
    if not oos:
        raise ValueError("not enough data for one train+test window")
    r, pos = pd.concat(oos), pd.concat(oos_pos)
    return {"returns": r, "metrics": _metrics(r, pos), "picks": picks}


def bootstrap_drawdown(returns: pd.Series, sims: int = 2000, block: int = 10, horizon: int | None = None,
                       ruin_level: float = -0.3, seed: int = 7) -> dict:
    """Stationary-ish block bootstrap of daily returns: how bad can drawdown get by luck alone?"""
    r = returns.dropna().to_numpy()
    n = len(r)
    if n < block * 2:
        raise ValueError("need more returns for a bootstrap")
    horizon = horizon or n
    rng = np.random.default_rng(seed)
    worst = np.empty(sims)
    for i in range(sims):
        idx = []
        while len(idx) < horizon:
            s = rng.integers(0, n - block + 1)
            idx.extend(range(s, s + block))
        path = (1 + r[np.array(idx[:horizon])]).cumprod()
        worst[i] = (path / np.maximum.accumulate(path) - 1).min()
    return {"median_max_dd": float(np.median(worst)), "p95_worst_dd": float(np.quantile(worst, 0.05)),
            "p99_worst_dd": float(np.quantile(worst, 0.01)), "prob_dd_beyond_ruin": float(np.mean(worst <= ruin_level)),
            "ruin_level": ruin_level, "sims": sims}
