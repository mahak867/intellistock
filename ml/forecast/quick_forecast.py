"""
Fast multi-horizon price forecast with honest, walk-forward evaluation.

Model: Ridge + RandomForest ensemble predicting cumulative log-returns for
days 1..H in one multi-output fit, from lagged returns, volatility, RSI, MACD
histogram, moving-average ratios and volume z-score. The 80% band comes from
out-of-sample residual quantiles per horizon day (time-series CV), not from a
formula. Metrics compare against a naive "no change" baseline so a model that
does not beat it is reported as such.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

LAGS = (1, 2, 3, 5, 10, 20)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    r = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    for k in LAGS:
        f[f"ret_{k}"] = np.log(c).diff(k)
    f["vol_10"] = r.rolling(10).std()
    f["vol_30"] = r.rolling(30).std()
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi"] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))) / 100
    macd = c.ewm(span=12).mean() - c.ewm(span=26).mean()
    f["macd_hist"] = (macd - macd.ewm(span=9).mean()) / c
    f["sma20_gap"] = c / c.rolling(20).mean() - 1
    f["sma50_gap"] = c / c.rolling(50).mean() - 1
    v = df["volume"].astype(float)
    f["vol_z"] = (v - v.rolling(30).mean()) / v.rolling(30).std()
    return f


def _targets(close: pd.Series, horizon: int) -> pd.DataFrame:
    lc = np.log(close)
    return pd.concat({k: lc.shift(-k) - lc for k in range(1, horizon + 1)}, axis=1)


def _fit_predict(Xtr, Ytr, Xte):
    sc = StandardScaler().fit(Xtr)
    ridge = Ridge(alpha=50.0).fit(sc.transform(Xtr), Ytr)
    rf = RandomForestRegressor(
        n_estimators=120, min_samples_leaf=15, max_features=0.5, n_jobs=-1, random_state=7
    ).fit(Xtr, Ytr)
    return 0.5 * ridge.predict(sc.transform(Xte)) + 0.5 * rf.predict(Xte)


def forecast(df: pd.DataFrame, horizon: int = 10, splits: int = 4) -> dict:
    """df: DatetimeIndex frame with close and volume columns (>= 200 rows)."""
    feats = build_features(df)
    tgt = _targets(df["close"], horizon)
    data = pd.concat([feats, tgt], axis=1).dropna()
    X = data[feats.columns].to_numpy()
    Y = data[tgt.columns].to_numpy()

    # Walk-forward out-of-sample predictions (gap = horizon avoids label leakage)
    oos_pred, oos_true = [], []
    for tr, te in TimeSeriesSplit(n_splits=splits, gap=horizon).split(X):
        oos_pred.append(_fit_predict(X[tr], Y[tr], X[te]))
        oos_true.append(Y[te])
    P, T = np.vstack(oos_pred), np.vstack(oos_true)
    resid = T - P
    lo_q, hi_q = np.quantile(resid, 0.10, axis=0), np.quantile(resid, 0.90, axis=0)

    last_x = feats.iloc[[-1]].to_numpy()
    mean = _fit_predict(X, Y, last_x)[0]
    last_close = float(df["close"].iloc[-1])
    idx = pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=horizon)
    fan = [
        {
            "time": d.strftime("%Y-%m-%d"),
            "mean": last_close * float(np.exp(mean[k])),
            "lo": last_close * float(np.exp(mean[k] + lo_q[k])),
            "hi": last_close * float(np.exp(mean[k] + hi_q[k])),
        }
        for k, d in enumerate(idx)
    ]

    h = horizon - 1
    dir_acc = float(np.mean(np.sign(P[:, h]) == np.sign(T[:, h])))
    mae_model = float(np.mean(np.abs(T[:, h] - P[:, h])))
    mae_naive = float(np.mean(np.abs(T[:, h])))  # predict zero return
    coverage = float(np.mean((T[:, h] >= P[:, h] + lo_q[h]) & (T[:, h] <= P[:, h] + hi_q[h])))
    return {
        "fan": fan,
        "metrics": {
            "model": "Ridge + RandomForest ensemble",
            "horizon_days": horizon,
            "walk_forward_samples": int(len(P)),
            "directional_accuracy": dir_acc,
            "mae_log_return": mae_model,
            "mae_naive_baseline": mae_naive,
            "beats_naive": mae_model < mae_naive,
            "band_coverage_80": coverage,
        },
    }
