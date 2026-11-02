"""NSE cash-market end-of-day file ("UDiFF bhavcopy"): download, cache, parse.

Format checked against NSE's published file list and independent write-ups on 2026-11-02, but NOT
against a live download from this sandbox (it cannot reach NSE). Run scripts/fetch_data.py on your
own machine and read its summary before trusting anything built on it.

Data licence: these files are NSE's. Using them for your own analysis is one thing; selling or
redistributing them in a product is another and needs a licence from NSE or a data vendor.
"""
from __future__ import annotations

import io
import time
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
# Canonical field -> names it has gone by. UDiFF is the current layout; the others are NSE's older layouts,
# accepted so a changed or older file still loads instead of failing on a name.
ALIASES = {
    "date": ["TradDt", "TIMESTAMP", "DATE1", "Date"],
    "symbol": ["TckrSymb", "SYMBOL", "Symbol"],
    "series": ["SctySrs", "SERIES", "Series"],
    "open": ["OpnPric", "OPEN", "OPEN_PRICE", "Open"],
    "high": ["HghPric", "HIGH", "HIGH_PRICE", "High"],
    "low": ["LwPric", "LOW", "LOW_PRICE", "Low"],
    "close": ["ClsPric", "CLOSE", "CLOSE_PRICE", "Close"],
    "prev_close": ["PrvsClsgPric", "PREVCLOSE", "PREV_CLOSE", "PrevClose"],
    "volume": ["TtlTradgVol", "TOTTRDQTY", "TTL_TRD_QNTY", "Volume"],
}
REQUIRED = [a[0] for a in ALIASES.values()]  # the current-layout name of each field, used in error messages


def resolve_columns(cols) -> tuple[dict[str, str], list[str]]:
    """Map canonical field -> actual column name (case/space-insensitive). Returns (mapping, missing fields)."""
    norm = {str(c).strip().lower(): c for c in cols}
    found, missing = {}, []
    for field, names in ALIASES.items():
        hit = next((norm[n.lower()] for n in names if n.lower() in norm), None)
        if hit is None:
            missing.append(field)
        else:
            found[field] = hit
    return found, missing


class StaleFile(ValueError):
    """The exchange served a different day's file for the requested date."""


def parse_udiff(raw: bytes, expect: date | None = None) -> pd.DataFrame:
    """Raw bytes (zip or plain CSV) -> tidy rows: date, symbol, series, open, high, low, close, prev_close, volume."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if name is None:
                raise ValueError("zip has no CSV inside")
            raw = z.read(name)
    df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    m, missing = resolve_columns(df.columns)
    if missing:
        raise ValueError(f"unexpected file layout: cannot find {missing}. Columns present: {list(df.columns)[:14]}")
    for c in df.columns:
        df[c] = df[c].str.strip()
    out = pd.DataFrame({
        "date": pd.to_datetime(df[m["date"]], errors="coerce", format="mixed", dayfirst=False),
        "symbol": df[m["symbol"]], "series": df[m["series"]],
        "open": pd.to_numeric(df[m["open"]], errors="coerce"), "high": pd.to_numeric(df[m["high"]], errors="coerce"),
        "low": pd.to_numeric(df[m["low"]], errors="coerce"), "close": pd.to_numeric(df[m["close"]], errors="coerce"),
        "prev_close": pd.to_numeric(df[m["prev_close"]], errors="coerce"), "volume": pd.to_numeric(df[m["volume"]], errors="coerce"),
    }).dropna(subset=["date", "symbol", "close"])
    if out.empty:
        raise ValueError("file parsed but holds no usable rows")
    if "FinInstrmTp" in df.columns:  # keep stocks and ETFs, drop anything else the file may carry
        out = out[df.loc[out.index, "FinInstrmTp"].isin(["STK", "ETF", "STO"]) | df.loc[out.index, "FinInstrmTp"].isna()]
    if expect is not None:
        got = out["date"].dt.date.mode().iloc[0]
        if got != expect:
            raise StaleFile(f"asked for {expect} but the file is for {got}")
    return out.reset_index(drop=True)


def download_day(d: date, client, cache_dir: Path, delay: float = 2.0, retries: int = 3) -> pd.DataFrame | None:
    """One trading day. Returns None when NSE has no file (holiday, weekend, or not published yet).
    The raw file is saved unchanged so it can be re-parsed later."""
    raw_dir = cache_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f, none = raw_dir / f"{d:%Y%m%d}.csv.zip", raw_dir / f"{d:%Y%m%d}.none"
    if f.exists():
        return parse_udiff(f.read_bytes(), d)
    if none.exists():
        return None
    for attempt in range(retries):
        r = client.get(URL.format(d=d))
        if r.status_code == 200:
            df = parse_udiff(r.content, d)  # raises StaleFile / ValueError before we cache a bad file
            f.write_bytes(r.content)
            time.sleep(delay)
            return df
        if r.status_code == 404:
            if (date.today() - d).days > 7:  # old enough that "not published yet" is not the explanation
                none.write_text("404")
            time.sleep(delay)
            return None
        if r.status_code in (403, 429):
            time.sleep(delay * (attempt + 2) * 2)
            continue
        r.raise_for_status()
    raise RuntimeError(f"NSE kept refusing the request for {d} (403/429). Wait a while and run again; the cache keeps what is done.")
