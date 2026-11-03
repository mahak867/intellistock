"""Deterministic synthetic OHLCV for offline demos. NOT market data."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


CANON_DAYS = 1500


def synthetic_ohlcv(ticker: str, days: int = 700) -> pd.DataFrame:
    """The last `days` rows of one fixed-length path per ticker, so every endpoint shows the same prices for a symbol
    whatever window it asks for (the path used to depend on `days`, so quotes and charts disagreed)."""
    full = _canonical(ticker, max(days, CANON_DAYS))
    return full.tail(days)


def _canonical(ticker: str, days: int) -> pd.DataFrame:
    seed = int(hashlib.sha256(ticker.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    base = 200 + seed % 3000
    vol = rng.uniform(0.011, 0.022)
    drift = rng.normal(0.0004, 0.0002)
    regime = np.sin(np.linspace(0, rng.uniform(3, 7) * days / 260, days)) * 0.0009
    # GARCH(1,1)-style volatility clustering, as seen in real markets
    sig = np.empty(days)
    s2 = vol**2
    shocks = rng.normal(0, 1, days)
    rets = np.empty(days)
    for i in range(days):
        sig[i] = np.sqrt(s2)
        rets[i] = drift + regime[i] + sig[i] * shocks[i]
        s2 = 0.06 * vol**2 + 0.12 * (sig[i] * shocks[i]) ** 2 + 0.82 * s2
    vol = float(np.mean(sig))
    close = base * np.exp(np.cumsum(rets))
    open_ = np.r_[base, close[:-1]] * (1 + rng.normal(0, 0.002, days))
    span = np.abs(rng.normal(0, 1, days)) * sig * 0.7 * close
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
