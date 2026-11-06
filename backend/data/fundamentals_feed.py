"""Company fundamentals from Yahoo Finance (via yfinance), cached for a day.

Yahoo's numbers are its own compilation and can differ from the annual report; each value is shown with its source.
Yahoo has no promoter-holding or pledge figures for Indian stocks: "insider holding" is the closest field and is
labelled as such, not as promoter holding.
"""
from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor

TTL = 24 * 3600
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _num(v, scale: float = 1.0):
    try:
        x = float(v) * scale
    except (TypeError, ValueError):
        return None
    return round(x, 4) if math.isfinite(x) else None


def _shares_x_price(info: dict):
    try:
        return float(info["sharesOutstanding"]) * float(info.get("currentPrice") or info["regularMarketPrice"])
    except (KeyError, TypeError, ValueError):
        return None


def from_info(symbol: str, info: dict) -> dict:
    """Map a yfinance `info` dict to IntelliStock's field names (percent fields as plain percents)."""
    de = _num(info.get("debtToEquity"))
    dy = _num(info.get("dividendYield"))  # Yahoo now reports this one as a percent already
    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": _num(info.get("currentPrice") or info.get("regularMarketPrice")),
        "pe": _num(info.get("trailingPE")),
        "forward_pe": _num(info.get("forwardPE")),
        "pb": _num(info.get("priceToBook")),
        "roe": _num(info.get("returnOnEquity"), 100),
        "roa": _num(info.get("returnOnAssets"), 100),
        "debt_equity": None if de is None else round(de / 100, 4),  # Yahoo reports debt/equity in percent
        "profit_margin": _num(info.get("profitMargins"), 100),
        "operating_margin": _num(info.get("operatingMargins"), 100),
        "sales_growth": _num(info.get("revenueGrowth"), 100),
        "profit_cagr_3y": None,  # not available from Yahoo
        "earnings_growth": _num(info.get("earningsGrowth"), 100),
        "market_cap_cr": _num(info.get("marketCap") or _shares_x_price(info), 1e-7),
        "dividend_yield": dy,
        "insider_holding": _num(info.get("heldPercentInsiders"), 100),
        "beta": _num(info.get("beta")),
        "source": "Yahoo Finance",
    }


def fetch_one(symbol: str, exchange: str = "NSE") -> dict:
    key = f"{exchange}:{symbol.upper()}"
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
    import yfinance as yf

    suffix = ".NS" if exchange == "NSE" else ".BO"
    tk = yf.Ticker(symbol.upper() + suffix)
    info = dict(tk.info or {})
    if not info.get("marketCap"):
        try:  # Yahoo sometimes leaves marketCap out of `info` for NSE listings
            info["marketCap"] = tk.fast_info["marketCap"]
        except Exception:
            pass
    if not info or (info.get("trailingPE") is None and info.get("marketCap") is None):
        raise LookupError(f"Yahoo Finance has no fundamentals for {symbol}.")
    row = from_info(symbol, info)
    with _lock:
        _cache[key] = (time.time(), row)
    return row


def fetch_many(symbols: list[str], workers: int = 8) -> tuple[list[dict], list[str]]:
    rows, missing = [], []

    def one(s):
        try:
            return fetch_one(s)
        except Exception:
            return s

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for r in ex.map(one, symbols):
            (rows.append(r) if isinstance(r, dict) else missing.append(r))
    return rows, missing
