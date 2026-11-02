"""Portfolio risk: likely loss range over a week/month and stress tests.

Parametric numbers assume roughly normal returns, which understates crashes: always read them
next to the stress tests and the historical-simulation figures."""
from __future__ import annotations

import numpy as np
import pandas as pd

Z = {0.90: 1.2816, 0.95: 1.6449, 0.99: 2.3263}
SCENARIOS = {  # approximate peak-to-trough falls of the Nifty 50
    "COVID crash (Jan-Mar 2020)": -0.38,
    "Global financial crisis (Jan-Oct 2008)": -0.60,
}


def ewma_cov(returns: pd.DataFrame, lam: float = 0.94) -> pd.DataFrame:
    """RiskMetrics exponentially weighted covariance of daily returns."""
    x = returns.dropna().to_numpy()
    w = lam ** np.arange(len(x) - 1, -1, -1)
    w /= w.sum()
    mu = (w[:, None] * x).sum(0)
    xc = x - mu
    cov = (xc * w[:, None]).T @ xc
    return pd.DataFrame(cov, index=returns.columns, columns=returns.columns)


def parametric_range(weights: pd.Series, cov: pd.DataFrame, value: float, horizon_days: int, conf: float = 0.95) -> dict:
    w = weights.reindex(cov.index).fillna(0).to_numpy()
    sd = float(np.sqrt(w @ cov.to_numpy() @ w) * np.sqrt(horizon_days))
    z = Z[conf]
    return {"horizon_days": horizon_days, "confidence": conf, "sd_pct": sd, "var_pct": z * sd, "var_amount": z * sd * value}


def historical_range(port_returns: pd.Series, value: float, horizon_days: int, conf: float = 0.95) -> dict:
    """Overlapping horizon returns from the portfolio's own history (needs >= 2 years)."""
    r = port_returns.dropna()
    h = (1 + r).rolling(horizon_days).apply(np.prod, raw=True).dropna() - 1
    if len(h) < 100:
        raise ValueError("not enough history for a historical simulation")
    q = np.quantile(h, 1 - conf)
    es = h[h <= q].mean()
    return {"horizon_days": horizon_days, "confidence": conf, "var_pct": float(-q), "var_amount": float(-q * value),
            "expected_shortfall_pct": float(-es), "worst_pct": float(-h.min()),
            "p05_pct": float(np.quantile(h, 0.05)), "p95_pct": float(np.quantile(h, 0.95))}


def betas(stock_returns: pd.DataFrame, index_returns: pd.Series) -> pd.Series:
    df = stock_returns.join(index_returns.rename("_idx"), how="inner").dropna()
    var = df["_idx"].var(ddof=1)
    return pd.Series({c: df[c].cov(df["_idx"]) / var for c in stock_returns.columns})


def stress(weights: pd.Series, beta: pd.Series, value: float, scenarios: dict[str, float] | None = None) -> list[dict]:
    """Beta-scaled: portfolio move = sum(weight * beta) * index fall. A rough guide: single
    stocks can fall far more or less than beta implies."""
    pb = float((weights * beta.reindex(weights.index).fillna(1.0)).sum())
    return [{"scenario": n, "index_move": m, "portfolio_beta": pb, "portfolio_move": pb * m, "loss_amount": -pb * m * value}
            for n, m in (scenarios or SCENARIOS).items()]
