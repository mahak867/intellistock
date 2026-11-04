"""One place the API asks for prices. Never silently substitutes fake prices for a real source.

DATA_PROVIDER
  synthetic  placeholder prices (development only)
  nse        files you downloaded from NSE with scripts/fetch_data.py (personal research: see LICENSING.md)
  local      a store you filled from licensed vendor data with scripts/import_vendor_csv.py
A store containing a file named FIXTURE is a test fixture and is labelled as such everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backend.core.config import settings
from backend.data import dividends as dv
from backend.data import indices, store
from backend.data.prices import build_ohlcv

STORE_PROVIDERS = ("nse", "local")


class NoData(Exception):
    pass


@dataclass
class Prices:
    df: pd.DataFrame
    source: str            # "synthetic" | "fixture" | "nse" | "local"
    quality: dict | None

    @property
    def synthetic(self) -> bool:
        return self.source in ("synthetic", "fixture")


def provider_name() -> str:
    return str(getattr(settings, "DATA_PROVIDER", "synthetic")).lower()


def data_dir() -> Path:
    return Path(getattr(settings, "DATA_DIR", "./data"))


def store_source() -> str:
    """Label for what is in the store: fixture, nse or local."""
    if (data_dir() / "FIXTURE").exists():
        return "fixture"
    return provider_name() if provider_name() in STORE_PROVIDERS else "synthetic"


def licensed() -> bool:
    """May this deployment serve this data to users? Downloaded NSE files need an NSE Data & Analytics agreement to be
    redistributed; set NSE_DATA_LICENSED=true only once you actually hold one."""
    return provider_name() != "nse" or bool(getattr(settings, "NSE_DATA_LICENSED", False))


def get_prices(symbol: str, days: int = 700) -> Prices:
    sym = symbol.upper().strip()
    if provider_name() in STORE_PROVIDERS:
        rows = store.load(data_dir())
        if rows is None:
            raise NoData("No local price store yet. Run: python scripts/fetch_data.py")
        try:
            df, q = build_ohlcv(rows, sym, dividends=dv.load_dividends(data_dir()))
        except KeyError:
            raise NoData(f"No data for {sym} in the local store. Check the symbol, or fetch a wider range.")
        if len(df) < 250:
            raise NoData(f"Only {len(df)} days of data for {sym}; need at least 250.")
        return Prices(df.tail(days), store_source(), q)
    from ml.forecast.synthetic import synthetic_ohlcv

    return Prices(synthetic_ohlcv(sym, days), "synthetic", None)


def index_series(name: str = "NIFTY 50") -> pd.Series | None:
    """Daily close of a real index from the store, or None."""
    if provider_name() not in STORE_PROVIDERS:
        return None
    idx = indices.load_indices(data_dir())
    if idx is None:
        return None
    s = idx[idx["index"] == name].drop_duplicates("date").set_index("date")["close"].sort_index()
    return s if len(s) >= 60 else None


def market_frame(index: pd.Index) -> pd.DataFrame | None:
    """Nifty 50 and India VIX aligned to a stock's dates, for the forecast model's market features."""
    n, v = index_series("NIFTY 50"), index_series("INDIA VIX")
    if n is None and v is None:
        return None
    m = pd.DataFrame(index=index)
    if n is not None:
        m["index_close"] = n.reindex(index.union(n.index)).ffill().reindex(index)
    if v is not None:
        m["vix"] = v.reindex(index.union(v.index)).ffill().reindex(index)
    m = m.dropna(how="all")
    return m if len(m) > 100 else None


def universe(limit: int = 60, min_days: int = 250) -> list[str]:
    """Symbols worth screening: real source = most liquid names with enough history; synthetic = a fixed list."""
    if provider_name() not in STORE_PROVIDERS:
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
    if name not in STORE_PROVIDERS:
        return {"provider": "synthetic", "real_data": False, "licensed_to_serve": True,
                "note": "Placeholder prices. Fetch NSE data (scripts/fetch_data.py) and set DATA_PROVIDER=nse."}
    rows = store.load(data_dir())
    if rows is None:
        return {"provider": name, "real_data": False, "licensed_to_serve": licensed(), "note": "No local price store yet. Run: python scripts/fetch_data.py"}
    src = store_source()
    return {"provider": name, "source": src, "real_data": src != "fixture", "licensed_to_serve": licensed(), "symbols": int(rows["symbol"].nunique()),
            "first": str(rows["date"].min().date()), "last": str(rows["date"].max().date()),
            "has_index_data": index_series("NIFTY 50") is not None, "has_vix": index_series("INDIA VIX") is not None,
            "has_dividends": dv.load_dividends(data_dir()) is not None,
            "note": "Test fixture: synthetic prices in NSE layout." if src == "fixture" else "End-of-day prices, not live."}
