"""Deterministic synthetic OHLCV for offline demos. NOT market data."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


def synthetic_ohlcv(ticker: str, days: int = 700) -> pd.DataFrame:
    seed = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    base = 200 + seed % 3000
    vol = rng.uniform(0.011, 0.022)
    drift = rng.normal(0.0004, 0.0002)
    regime = np.sin(np.linspace(0, rng.uniform(3, 7) * days / 260, days)) * 0.0009
    rets = rng.normal(drift, vol, days) + regime
    close = base * np.exp(np.cumsum(rets))
    open_ = np.r_[base, close[:-1]] * (1 + rng.normal(0, 0.002, days))
    span = np.abs(rng.normal(0, vol * 0.7, days)) * close
    volume = (rng.lognormal(14.2, 0.35, days) * (1 + 6 * np.abs(rets))).astype(int)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.DataFrame(
        {
            "open": open_,
            "high": np.maximum(open_, close) + span,
            "low": np.minimum(open_, close) - span,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )
