"""One place the API asks for prices. Never silently substitutes fake prices for a real source."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backend.core.config import settings
from backend.data import store
from backend.data.prices import build_ohlcv


class NoData(Exception):
    pass


@dataclass
class Prices:
    df: pd.DataFrame
    source: str            # "synthetic" or "nse"
    quality: dict | None

    @property
    def synthetic(self) -> bool:
        return self.source == "synthetic"


def provider_name() -> str:
    return str(getattr(settings, "DATA_PROVIDER", "synthetic")).lower()


def data_dir() -> Path:
    return Path(getattr(settings, "DATA_DIR", "./data"))


def get_prices(symbol: str, days: int = 700) -> Prices:
    sym = symbol.upper().strip()
    if provider_name() == "nse":
        rows = store.load(data_dir())
        if rows is None:
            raise NoData("No local price store yet. Run: python scripts/fetch_data.py")
        try:
            df, q = build_ohlcv(rows, sym)
        except KeyError:
            raise NoData(f"No NSE data for {sym}. Check the symbol, or fetch a wider range.")
        if len(df) < 120:
            raise NoData(f"Only {len(df)} days of data for {sym}; need at least 120.")
        return Prices(df.tail(days), "nse", q)
    from ml.forecast.synthetic import synthetic_ohlcv

    return Prices(synthetic_ohlcv(sym, days), "synthetic", None)


def universe(limit: int = 60, min_days: int = 250) -> list[str]:
    """Symbols worth screening: real source = most liquid names with enough history; synthetic = a fixed list."""
    if provider_name() != "nse":
        return ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "MARUTI", "WIPRO", "ONGC", "NTPC", "COALINDIA",
                "HINDUNILVR", "NESTLEIND", "TATASTEEL", "JSWSTEEL", "KOTAKBANK", "AXISBANK", "TECHM", "HCLTECH"]
    rows = store.load(data_dir())
    if rows is None:
        raise NoData("No local price store yet. Run: python scripts/fetch_data.py")
    eq = rows[rows["series"] == "EQ"]
    counts = eq.groupby("symbol")["date"].count()
    recent = eq[eq["date"] >= eq["date"].max() - pd.Timedelta(days=90)]
    turnover = (recent["close"] * recent["volume"]).groupby(recent["symbol"]).mean()
    ok = turnover[turnover.index.isin(counts[counts >= min_days].index)].sort_values(ascending=False)
    return list(ok.head(limit).index)


def status() -> dict:
    name = provider_name()
    if name != "nse":
        return {"provider": "synthetic", "real_data": False, "note": "Placeholder prices. Set DATA_PROVIDER=nse after fetching data."}
    rows = store.load(data_dir())
    if rows is None:
        return {"provider": "nse", "real_data": False, "note": "No local price store yet. Run: python scripts/fetch_data.py"}
    return {"provider": "nse", "real_data": True, "symbols": int(rows["symbol"].nunique()), "first": str(rows["date"].min().date()),
            "last": str(rows["date"].max().date()), "note": "NSE end-of-day files. Prices are end-of-day, not live."}
