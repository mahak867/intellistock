"""
IntelliStock — Feature Engineering
────────────────────────────────────
• All indicators computed on TRAINING data only, then transformed on val/test
• Warm-up period tracked per indicator — no silent NaN contamination
• NIFTY50 macro feature included
• Returns clean numpy arrays ready for LSTM sequences
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple

import numpy as np
import pandas as pd
import ta
from loguru import logger
from sklearn.preprocessing import MinMaxScaler

# ─── Indicator warm-up periods ──────────────────────────────────────────────────

WARMUP_PERIODS = {
    "RSI": 14,
    "MACD": 26,
    "MACD_signal": 9,
    "BB": 20,
    "SMA_20": 20,
    "SMA_50": 50,
    "EMA_12": 12,
    "EMA_26": 26,
    "ATR": 14,
    "OBV": 1,
}

# Max warm-up across all indicators — first N rows will always be NaN
MAX_WARMUP = max(WARMUP_PERIODS.values())


# ─── Feature set ────────────────────────────────────────────────────────────────


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators on a single OHLCV DataFrame.

    IMPORTANT: Call this function on each split independently AFTER
    train/test/val split. Never call on the full dataset.

    Args:
        df: DataFrame with Open, High, Low, Close, Volume columns

    Returns:
        DataFrame with all features. First MAX_WARMUP rows will be NaN
        — caller must drop them (handled in FeatureEngineer.fit_transform).
    """
    df = df.copy()

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # ── Price-based features ─────────────────────────────────────────────────
    df["Returns"] = close.pct_change()
    df["Log_Returns"] = np.log(close / close.shift(1))
    df["HL_Ratio"] = (high - low) / close  # daily range as % of close
    df["OC_Ratio"] = (close - df["Open"]) / df["Open"]  # open-close momentum

    # ── Moving Averages ──────────────────────────────────────────────────────
    df["SMA_20"] = ta.trend.sma_indicator(close, window=20)
    df["SMA_50"] = ta.trend.sma_indicator(close, window=50)
    df["EMA_12"] = ta.trend.ema_indicator(close, window=12)
    df["EMA_26"] = ta.trend.ema_indicator(close, window=26)

    # Price relative to moving averages (dimensionless)
    df["Price_SMA20_Ratio"] = close / df["SMA_20"]
    df["Price_SMA50_Ratio"] = close / df["SMA_50"]
    df["SMA20_SMA50_Cross"] = df["SMA_20"] / df["SMA_50"]  # golden/death cross signal

    # ── RSI ──────────────────────────────────────────────────────────────────
    df["RSI"] = ta.momentum.rsi(close, window=14)
    df["RSI_Overbought"] = (df["RSI"] > 70).astype(float)
    df["RSI_Oversold"] = (df["RSI"] < 30).astype(float)

    # ── MACD ─────────────────────────────────────────────────────────────────
    macd_obj = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    df["MACD"] = macd_obj.macd()
    df["MACD_Signal"] = macd_obj.macd_signal()
    df["MACD_Hist"] = macd_obj.macd_diff()
    df["MACD_Crossover"] = (df["MACD"] > df["MACD_Signal"]).astype(float)

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_obj = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    df["BB_High"] = bb_obj.bollinger_hband()
    df["BB_Low"] = bb_obj.bollinger_lband()
    df["BB_Width"] = (df["BB_High"] - df["BB_Low"]) / bb_obj.bollinger_mavg()
    df["BB_Position"] = (close - df["BB_Low"]) / (df["BB_High"] - df["BB_Low"] + 1e-10)

    # ── Volume indicators ─────────────────────────────────────────────────────
    df["Volume_SMA20"] = ta.trend.sma_indicator(volume.astype(float), window=20)
    df["Volume_Ratio"] = volume / (df["Volume_SMA20"] + 1e-10)
    df["OBV"] = ta.volume.on_balance_volume(close, volume.astype(float))
    df["OBV_Norm"] = df["OBV"] / (df["OBV"].abs().max() + 1e-10)

    # ── Volatility ────────────────────────────────────────────────────────────
    df["ATR"] = ta.volatility.average_true_range(high, low, close, window=14)
    df["Volatility_20"] = df["Returns"].rolling(20).std() * np.sqrt(252)  # annualised
    df["Volatility_5"] = df["Returns"].rolling(5).std() * np.sqrt(252)

    # ── Holiday flag ─────────────────────────────────────────────────────────
    if "IsHoliday" in df.columns:
        df["IsHoliday"] = df["IsHoliday"].astype(float)
    else:
        df["IsHoliday"] = 0.0

    return df


# ── Feature columns used for model input (order matters for scaler) ─────────────

FEATURE_COLS = [
    "Close",
    "Returns",
    "Log_Returns",
    "HL_Ratio",
    "OC_Ratio",
    "SMA_20",
    "SMA_50",
    "EMA_12",
    "EMA_26",
    "Price_SMA20_Ratio",
    "Price_SMA50_Ratio",
    "SMA20_SMA50_Cross",
    "RSI",
    "RSI_Overbought",
    "RSI_Oversold",
    "MACD",
    "MACD_Signal",
    "MACD_Hist",
    "MACD_Crossover",
    "BB_High",
    "BB_Low",
    "BB_Width",
    "BB_Position",
    "Volume",
    "Volume_Ratio",
    "OBV_Norm",
    "ATR",
    "Volatility_20",
    "Volatility_5",
    "IsHoliday",
]

TARGET_COL = "Close"
TARGET_IDX = FEATURE_COLS.index(TARGET_COL)  # index in scaler for inverse_transform


# ─── Scaler pipeline (fit on train ONLY) ────────────────────────────────────────


@dataclass
class FeatureEngineer:
    """
    Stateful feature engineering pipeline.

    Usage:
        fe = FeatureEngineer(sequence_length=60)
        X_train, y_train = fe.fit_transform(train_df, nifty_series)
        X_val,   y_val   = fe.transform(val_df,   nifty_series)
        X_test,  y_test  = fe.transform(test_df,  nifty_series)

    The scaler is fitted ONLY on training data — zero leakage into val/test.
    """

    sequence_length: int = 60
    prediction_horizon: int = 1
    scaler: MinMaxScaler = field(
        default_factory=lambda: MinMaxScaler(feature_range=(0, 1))
    )
    _is_fitted: bool = field(default=False, init=False)
    feature_cols: list[str] = field(default_factory=lambda: list(FEATURE_COLS))

    def _prepare(
        self,
        df: pd.DataFrame,
        nifty_series: pd.Series | None = None,
    ) -> pd.DataFrame:
        """Compute features, merge NIFTY, drop warm-up NaNs."""
        feat = compute_features(df)

        # Add NIFTY50 macro feature if provided
        if nifty_series is not None:
            feat = feat.join(nifty_series.rename("Nifty50_Return"), how="left")
            feat["Nifty50_Return"] = feat["Nifty50_Return"].fillna(0)
            if "Nifty50_Return" not in self.feature_cols:
                self.feature_cols.append("Nifty50_Return")

        # Drop warm-up NaN rows — must be from the START only to preserve sequence integrity
        feat = feat.iloc[MAX_WARMUP:].copy()
        feat = feat[self.feature_cols].dropna()
        return feat

    def fit_transform(
        self,
        train_df: pd.DataFrame,
        nifty_series: pd.Series | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Fit scaler on training data and return sequences."""
        feat = self._prepare(train_df, nifty_series)
        scaled = self.scaler.fit_transform(feat.values)
        self._is_fitted = True
        logger.info(
            f"Scaler fitted on {len(feat)} training rows | {len(self.feature_cols)} features"
        )
        return self._make_sequences(scaled)

    def transform(
        self,
        df: pd.DataFrame,
        nifty_series: pd.Series | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Transform val/test data using TRAINING scaler — no leakage."""
        if not self._is_fitted:
            raise RuntimeError("Call fit_transform() on training data first")
        feat = self._prepare(df, nifty_series)
        scaled = self.scaler.transform(feat.values)  # transform ONLY — no fit
        return self._make_sequences(scaled)

    def _make_sequences(
        self,
        scaled: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Sliding window sequence builder.
        X shape: (samples, sequence_length, n_features)
        y shape: (samples,) — next-day Close (inverse-transformable)
        """
        X, y = [], []
        for i in range(self.sequence_length, len(scaled) - self.prediction_horizon + 1):
            X.append(scaled[i - self.sequence_length : i])
            y.append(scaled[i + self.prediction_horizon - 1, TARGET_IDX])
        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    def inverse_transform_close(self, y_scaled: np.ndarray) -> np.ndarray:
        """
        Correctly inverse-transform predicted Close prices.
        Pads to full feature width before inverting, extracts Close column.
        """
        padded = np.zeros((len(y_scaled), len(self.feature_cols)))
        padded[:, TARGET_IDX] = y_scaled.flatten()
        return self.scaler.inverse_transform(padded)[:, TARGET_IDX]


# ─── Signal generation ───────────────────────────────────────────────────────────


class SignalLabel:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def generate_signal(
    predicted_price: float,
    current_price: float,
    rsi: float,
    macd: float,
    macd_signal: float,
) -> dict:
    """
    Generate BUY / SELL / HOLD signal combining LSTM prediction + RSI + MACD.

    Logic:
        BUY  → predicted_return > +1%  AND RSI < 70  AND MACD > MACD_Signal
        SELL → predicted_return < -1%  AND RSI > 30  AND MACD < MACD_Signal
        HOLD → everything else
    """
    predicted_return = (predicted_price - current_price) / current_price * 100
    macd_bullish = macd > macd_signal
    rsi_not_overbought = rsi < 70
    rsi_not_oversold = rsi > 30

    if predicted_return > 1.0 and rsi_not_overbought and macd_bullish:
        label = SignalLabel.BUY
        confidence = min(0.95, 0.6 + predicted_return / 20 + (70 - rsi) / 200)
    elif predicted_return < -1.0 and rsi_not_oversold and not macd_bullish:
        label = SignalLabel.SELL
        confidence = min(0.95, 0.6 + abs(predicted_return) / 20 + (rsi - 30) / 200)
    else:
        label = SignalLabel.HOLD
        confidence = 0.5 + abs(predicted_return) / 100

    return {
        "signal": label,
        "confidence": round(confidence, 4),
        "predicted_price": round(predicted_price, 2),
        "current_price": round(current_price, 2),
        "predicted_return_pct": round(predicted_return, 2),
        "rsi": round(rsi, 2),
        "macd_bullish": macd_bullish,
    }
