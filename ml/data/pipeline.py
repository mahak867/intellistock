"""
IntelliStock — Market Data Pipeline
────────────────────────────────────
• yfinance fetch with retry + timeout
• NSE/BSE market holiday detection via pandas_market_calendars
• Correct train/test split BEFORE any feature computation
• Proper ffill + volume=0 holiday gap handling
• Parquet caching to reduce API calls
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

# ── Constants ───────────────────────────────────────────────────────────────────

CACHE_DIR = Path(".cache/market_data")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NSE_SUFFIX = ".NS"
BSE_SUFFIX = ".BO"

OHLCV_COLS = ["Open", "High", "Low", "Close", "Volume"]

# ── Ticker helpers ──────────────────────────────────────────────────────────────


def normalise_ticker(ticker: str, exchange: Literal["NSE", "BSE"] = "NSE") -> str:
    """Ensure ticker has correct suffix for yfinance."""
    ticker = ticker.upper().strip()
    suffix = NSE_SUFFIX if exchange == "NSE" else BSE_SUFFIX
    if not ticker.endswith(suffix):
        ticker = ticker + suffix
    return ticker


# ── NSE holiday calendar ────────────────────────────────────────────────────────


def get_nse_trading_days(start: str, end: str) -> pd.DatetimeIndex:
    """Return actual NSE trading days — excludes weekends + Indian market holidays."""
    try:
        nse_cal = mcal.get_calendar("NSE")
        schedule = nse_cal.schedule(start_date=start, end_date=end)
        return mcal.date_range(schedule, frequency="1D").tz_localize(None)
    except Exception as exc:
        logger.warning(f"NSE calendar unavailable ({exc}), falling back to weekday filter")
        return pd.bdate_range(start=start, end=end)


# ── Raw data fetch ──────────────────────────────────────────────────────────────


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _fetch_raw(ticker: str, start: str, end: str, timeout: int = 30) -> pd.DataFrame:
    """Fetch OHLCV from Yahoo Finance with retry logic."""
    data = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=True,      # adjusted for splits & dividends
        progress=False,
        timeout=timeout,
        threads=False,         # avoid race conditions
    )
    if data.empty:
        raise ValueError(f"No data returned for {ticker} between {start} and {end}")
    return data


def _cache_key(ticker: str, start: str, end: str) -> str:
    raw = f"{ticker}_{start}_{end}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def fetch_ohlcv(
    ticker: str,
    start: str | None = None,
    end: str | None = None,
    lookback_years: int = 5,
    exchange: Literal["NSE", "BSE"] = "NSE",
    use_cache: bool = True,
    timeout: int = 30,
) -> pd.DataFrame:
    """
    Fetch and clean OHLCV data for any NSE/BSE ticker.

    Returns a DataFrame with:
        - DatetimeIndex (timezone-naive)
        - Columns: Open, High, Low, Close, Volume, IsHoliday
        - No NaN rows (gaps filled, flagged)
    """
    ticker = normalise_ticker(ticker, exchange)
    end = end or datetime.today().strftime("%Y-%m-%d")
    start = start or (datetime.today() - timedelta(days=365 * lookback_years)).strftime("%Y-%m-%d")

    # ── Cache check ─────────────────────────────────────────────────────────
    cache_file = CACHE_DIR / f"{_cache_key(ticker, start, end)}.parquet"
    if use_cache and cache_file.exists():
        age_hours = (datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)).seconds / 3600
        if age_hours < 12:
            logger.info(f"Loading {ticker} from cache ({age_hours:.1f}h old)")
            return pd.read_parquet(cache_file)

    logger.info(f"Fetching {ticker} from {start} to {end}")
    raw = _fetch_raw(ticker, start, end, timeout)

    # ── Flatten multi-level columns from yfinance 0.2.x ─────────────────────
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # ── Keep only OHLCV ─────────────────────────────────────────────────────
    df = raw[OHLCV_COLS].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df.index.name = "Date"

    # ── Align to trading calendar ────────────────────────────────────────────
    trading_days = get_nse_trading_days(start, end)
    df = df.reindex(trading_days)

    # ── Mark & fill holiday gaps ─────────────────────────────────────────────
    # IsHoliday = True for days with no exchange data (yfinance returned NaN)
    df["IsHoliday"] = df["Close"].isna()
    df[OHLCV_COLS] = df[OHLCV_COLS].ffill()    # carry last known price forward
    df.loc[df["IsHoliday"], "Volume"] = 0       # holidays: zero volume

    # ── Drop any remaining NaN at very start of series ──────────────────────
    df = df.dropna(subset=["Close"])

    # ── Data-quality checks ──────────────────────────────────────────────────
    if (df["Close"] <= 0).any():
        logger.warning(f"{ticker}: found non-positive Close prices — check data quality")
    if df.shape[0] < 252:
        logger.warning(f"{ticker}: only {df.shape[0]} rows — less than 1 year of data")

    # ── Cache write ──────────────────────────────────────────────────────────
    df.to_parquet(cache_file)
    logger.info(f"Fetched {len(df)} rows for {ticker}")
    return df


# ── NIFTY50 macro feature ────────────────────────────────────────────────────────


def fetch_nifty50(start: str, end: str) -> pd.Series:
    """
    Fetch NIFTY50 index and return daily % return as a Series.
    India-specific: individual NSE stocks are ~0.7 correlated with NIFTY.
    """
    nifty = fetch_ohlcv("^NSEI", start=start, end=end, use_cache=True)
    nifty_return = nifty["Close"].pct_change().rename("Nifty50_Return")
    return nifty_return


# ── Train/Test split ─────────────────────────────────────────────────────────────


def time_series_split(
    df: pd.DataFrame,
    test_ratio: float = 0.15,
    val_ratio: float = 0.10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Chronological split — NO shuffling, NO leakage.

    Returns (train, val, test) DataFrames preserving temporal order.
    All feature engineering must happen AFTER this split on each subset.
    """
    n = len(df)
    test_size = int(n * test_ratio)
    val_size = int(n * val_ratio)
    train_size = n - val_size - test_size

    train = df.iloc[:train_size].copy()
    val = df.iloc[train_size : train_size + val_size].copy()
    test = df.iloc[train_size + val_size :].copy()

    logger.info(
        f"Split → train={len(train)} | val={len(val)} | test={len(test)} "
        f"({train.index[0].date()} → {test.index[-1].date()})"
    )
    return train, val, test


# ── Batch fetch for multiple tickers ────────────────────────────────────────────


def fetch_multiple(
    tickers: list[str],
    start: str | None = None,
    end: str | None = None,
    lookback_years: int = 5,
    exchange: Literal["NSE", "BSE"] = "NSE",
) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for a list of tickers. Returns dict of {ticker: DataFrame}."""
    results: dict[str, pd.DataFrame] = {}
    for t in tickers:
        try:
            results[t] = fetch_ohlcv(t, start, end, lookback_years, exchange)
        except Exception as exc:
            logger.error(f"Failed to fetch {t}: {exc}")
    return results


# ── NIFTY50 constituents ─────────────────────────────────────────────────────────

NIFTY50_TICKERS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "BAJFINANCE", "WIPRO", "ULTRACEMCO", "NESTLEIND",
    "POWERGRID", "NTPC", "TECHM", "HCLTECH", "TATAMOTORS",
    "TATASTEEL", "JSWSTEEL", "GRASIM", "INDUSINDBK", "CIPLA",
    "DRREDDY", "DIVISLAB", "BAJAJFINSV", "ADANIENT", "ADANIPORTS",
    "COALINDIA", "ONGC", "BPCL", "HEROMOTOCO", "EICHERMOT",
    "SHREECEM", "BRITANNIA", "APOLLOHOSP", "TATACONSUM", "SBILIFE",
    "HDFCLIFE", "BAJAJ-AUTO", "M&M", "UPL", "HINDALCO",
]
