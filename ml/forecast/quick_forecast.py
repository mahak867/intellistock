"""
Honest multi-horizon forecasting: direction (shrunk toward "no change") plus a
volatility model that sets the confidence band.

Why this design (measured on 8 NIFTY stocks, 5-day horizon): a price-only
direction model is right ~49.5% of the time and is *worse* than "price stays
the same" on every stock. Daily returns are mostly noise. Volatility, on the
other hand, is persistent and forecastable, so:

  1. Direction: Ridge + RandomForest ensemble, then shrunk toward zero by a
     factor fitted out of sample. If the shrunk forecast still fails a
     significance test against "no change", `has_edge` is False and callers
     must not present BUY/SELL.
  2. Volatility: HAR-style ridge regression on log range-based (Parkinson)
     volatility predicts forward volatility. The 80% band is
     sigma_hat * sqrt(k) * empirical z-quantiles, calibrated out of sample.
  3. Optional market features (index returns, India VIX) via `market=`.

All evaluation is walk-forward with a gap of `horizon` days (no label leakage).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler

LAGS = (1, 2, 3, 5, 10, 20)
PARK = 1.0 / (4.0 * np.log(2.0))


# ─── Features ────────────────────────────────────────────────────────────────


def _parkinson_var(df: pd.DataFrame) -> pd.Series:
    return PARK * np.log(df["high"] / df["low"]).clip(lower=1e-6) ** 2


def _market_features(market: pd.DataFrame | None, index: pd.Index) -> pd.DataFrame:
    """market: DatetimeIndex frame with optional columns `index_close`, `vix`."""
    out = pd.DataFrame(index=index)
    if market is None or market.empty:
        return out
    m = market.reindex(index).ffill()
    if "index_close" in m:
        li = np.log(m["index_close"])
        out["mkt_ret_1"], out["mkt_ret_5"], out["mkt_ret_20"] = li.diff(), li.diff(5), li.diff(20)
    if "vix" in m:
        out["vix_log"] = np.log(m["vix"].clip(lower=1))
        out["vix_chg_5"] = out["vix_log"].diff(5)
    return out


def build_features(df: pd.DataFrame, market: pd.DataFrame | None = None) -> pd.DataFrame:
    c = df["close"]
    r = np.log(c).diff()
    f = pd.DataFrame(index=df.index)
    for k in LAGS:
        f[f"ret_{k}"] = np.log(c).diff(k)
    f["vol_10"], f["vol_30"] = r.rolling(10).std(), r.rolling(30).std()
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
    mf = _market_features(market, df.index)
    if len(mf.columns):
        f = f.join(mf)
        if "mkt_ret_5" in f:  # relative strength vs the index
            f["rel_5"] = f["ret_5"] - f["mkt_ret_5"]
            f["rel_20"] = f["ret_20"] - f["mkt_ret_20"]
    return f


def vol_features(df: pd.DataFrame, market: pd.DataFrame | None = None) -> pd.DataFrame:
    pv = _parkinson_var(df)
    f = pd.DataFrame(index=df.index)
    for w in (1, 5, 22, 66):
        f[f"lv_{w}"] = 0.5 * np.log(pv.rolling(w).mean().clip(lower=1e-10))
    f["absret"] = np.log(np.abs(np.log(df["close"]).diff()).clip(lower=1e-6))
    mf = _market_features(market, df.index)
    if "vix_log" in mf:
        f["vix_log"] = mf["vix_log"]
    return f


# ─── Targets ─────────────────────────────────────────────────────────────────


def _cum_returns(close: pd.Series, horizon: int) -> pd.DataFrame:
    lc = np.log(close)
    return pd.concat({k: lc.shift(-k) - lc for k in range(1, horizon + 1)}, axis=1)


def _fwd_log_vol(df: pd.DataFrame, horizon: int) -> pd.Series:
    pv = _parkinson_var(df)
    fwd = pv[::-1].rolling(horizon).mean()[::-1].shift(-1)  # mean var of days t+1..t+h
    return 0.5 * np.log(fwd.clip(lower=1e-10))


# ─── Models ──────────────────────────────────────────────────────────────────


def _direction_fit_predict(Xtr, Ytr, Xte):
    sc = StandardScaler().fit(Xtr)
    ridge = Ridge(alpha=50.0).fit(sc.transform(Xtr), Ytr)
    rf = RandomForestRegressor(
        n_estimators=120, min_samples_leaf=15, max_features=0.5, n_jobs=-1, random_state=7
    ).fit(Xtr, Ytr)
    return 0.5 * ridge.predict(sc.transform(Xte)) + 0.5 * rf.predict(Xte)


def _vol_fit_predict(Xtr, ytr, Xte):
    sc = StandardScaler().fit(Xtr)
    return Ridge(alpha=5.0).fit(sc.transform(Xtr), ytr).predict(sc.transform(Xte))


def _shrink_factor(P: np.ndarray, T: np.ndarray) -> float:
    """Least-squares slope of realised on predicted through the origin, clipped
    to [0, 1] (never amplify, never flip sign)."""
    num, den = float(np.sum(P * T)), float(np.sum(P * P))
    return float(np.clip(num / den, 0.0, 1.0)) if den > 0 else 0.0


def _edge_test(P: np.ndarray, T: np.ndarray, horizon: int) -> tuple[bool, float]:
    """Is |T-P| smaller than |T| (the no-change loss)? t-stat on the loss
    differential with an effective sample of n/horizon (overlapping targets)."""
    d = np.abs(T - P) - np.abs(T)
    n_eff = max(len(d) / horizon, 2.0)
    se = d.std(ddof=1) / np.sqrt(n_eff)
    t = float(d.mean() / se) if se > 0 else 0.0
    return bool(d.mean() < 0 and t < -2.0), t


def forecast(
    df: pd.DataFrame, horizon: int = 10, splits: int = 4, market: pd.DataFrame | None = None
) -> dict:
    """df: DatetimeIndex frame with open/high/low/close/volume (>= 250 rows)."""
    # Dirty input must not change the answer silently: order by date, one row per date, no missing prices.
    df = df[~df.index.duplicated(keep="last")].sort_index().dropna(subset=["open", "high", "low", "close"])
    if len(df) < 250:
        raise ValueError(f"Need at least 250 days of prices to forecast; this stock has {len(df)}.")
    # --- direction (walk-forward) ---
    feats = build_features(df, market)
    tgt = _cum_returns(df["close"], horizon)
    data = pd.concat([feats, tgt], axis=1).dropna()
    if len(data) < 100:
        raise ValueError("Too few clean days to forecast. Flat prices or missing volume leave too little to learn from.")
    X, Y = data[feats.columns].to_numpy(), data[tgt.columns].to_numpy()
    cv = TimeSeriesSplit(n_splits=splits, gap=horizon)
    oos_idx = np.concatenate([te for _, te in cv.split(X)])
    P = np.vstack([_direction_fit_predict(X[tr], Y[tr], X[te]) for tr, te in cv.split(X)])
    T = Y[oos_idx]
    h = horizon - 1

    shrink = _shrink_factor(P[:, h], T[:, h])
    Ps = P * shrink
    has_edge, t_stat = _edge_test(Ps[:, h], T[:, h], horizon)
    dir_acc = float(np.mean(np.sign(P[:, h]) == np.sign(T[:, h])))
    mae_raw = float(np.mean(np.abs(T[:, h] - P[:, h])))
    mae_shrunk = float(np.mean(np.abs(T[:, h] - Ps[:, h])))
    mae_naive = float(np.mean(np.abs(T[:, h])))

    # --- volatility (walk-forward) ---
    vf = vol_features(df, market)
    vt = _fwd_log_vol(df, horizon)
    vdata = pd.concat([vf, vt.rename("y")], axis=1).dropna()
    if len(vdata) < 100:
        raise ValueError("Too few clean days to estimate volatility. Flat prices or missing volume leave too little to learn from.")
    VX, vy = vdata[vf.columns].to_numpy(), vdata["y"].to_numpy()
    vcv = TimeSeriesSplit(n_splits=splits, gap=horizon)
    v_idx = np.concatenate([te for _, te in vcv.split(VX)])
    vpred = np.concatenate([_vol_fit_predict(VX[tr], vy[tr], VX[te]) for tr, te in vcv.split(VX)])
    vtrue = vy[v_idx]
    naive_v = vdata["lv_22"].to_numpy()[v_idx]  # "tomorrow looks like the last month"
    vol_mae, vol_naive_mae = float(np.mean(np.abs(vtrue - vpred))), float(np.mean(np.abs(vtrue - naive_v)))

    # Standardised OOS returns -> empirical z-quantiles per horizon day.
    # Align direction-OOS rows to vol-OOS rows by date.
    d_dates = data.index[oos_idx]
    vser = pd.Series(vpred, index=vdata.index[v_idx])
    sig_at = np.exp(vser.reindex(d_dates).ffill().bfill().to_numpy())
    ks = np.arange(1, horizon + 1)
    Z = (T - Ps) / (sig_at[:, None] * np.sqrt(ks)[None, :])
    zlo, zhi = np.quantile(Z, 0.10, axis=0), np.quantile(Z, 0.90, axis=0)
    covered = (Z[:, h] >= zlo[h]) & (Z[:, h] <= zhi[h])
    width = float(np.mean((zhi[h] - zlo[h]) * sig_at * np.sqrt(horizon)))

    # --- final fit on all data, forecast forward ---
    last_close = float(df["close"].iloc[-1])
    mean = _direction_fit_predict(X, Y, feats.iloc[[-1]].to_numpy())[0] * shrink
    sigma = float(np.exp(_vol_fit_predict(VX, vy, vf.iloc[[-1]].to_numpy())[0]))
    idx = pd.bdate_range(df.index[-1] + pd.Timedelta(days=1), periods=horizon)
    fan = [
        {
            "time": d.strftime("%Y-%m-%d"),
            "mean": last_close * float(np.exp(mean[k])),
            "lo": last_close * float(np.exp(mean[k] + zlo[k] * sigma * np.sqrt(k + 1))),
            "hi": last_close * float(np.exp(mean[k] + zhi[k] * sigma * np.sqrt(k + 1))),
        }
        for k, d in enumerate(idx)
    ]

    return {
        "fan": fan,
        "metrics": {
            "model": "Ridge + RandomForest (shrunk) with HAR volatility band",
            "horizon_days": horizon,
            "walk_forward_samples": int(len(T)),
            "market_features": bool(market is not None and not market.empty),
            "directional_accuracy": dir_acc,
            "shrink": shrink,
            "mae_log_return": mae_shrunk,
            "mae_raw_model": mae_raw,
            "mae_naive_baseline": mae_naive,
            "beats_naive": mae_shrunk < mae_naive,
            "has_edge": has_edge,
            "edge_t_stat": t_stat,
            "vol_mae_log": vol_mae,
            "vol_naive_mae_log": vol_naive_mae,
            "vol_beats_naive": vol_mae < vol_naive_mae,
            "band_coverage_80": float(np.mean(covered)),
            "band_width_pct": width,
            "daily_vol_pct": sigma * 100,
        },
    }
