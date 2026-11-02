"""NSE index end-of-day file: Nifty 50 and India VIX for betas and market features.

URL pattern verified from a published list of NSE sources (2026-11-02); the column layout below is from
memory of NSE's file and is matched loosely by name, because it was NOT verified against a live download.
Run scripts/check_nse_format.py on your machine to confirm.
"""
from __future__ import annotations

import io
import time
from datetime import date
from pathlib import Path

import pandas as pd

URL = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
WANT = {"nifty 50": "NIFTY 50", "india vix": "INDIA VIX", "nifty bank": "NIFTY BANK", "nifty next 50": "NIFTY NEXT 50"}


def _col(cols, *needles) -> str | None:
    for c in cols:
        low = str(c).strip().lower()
        if all(n in low for n in needles):
            return c
    return None


def parse_index_file(raw: bytes, expect: date | None = None) -> pd.DataFrame:
    """-> rows of date, index (upper-case name), close, for the indices we use."""
    df = pd.read_csv(io.BytesIO(raw), dtype=str, skipinitialspace=True)
    df.columns = [str(c).strip() for c in df.columns]
    name, close = _col(df.columns, "index", "name"), _col(df.columns, "clos")
    dt = _col(df.columns, "date")
    if not (name and close):
        raise ValueError(f"unexpected index file layout. Columns present: {list(df.columns)[:12]}")
    names = df[name].str.strip().str.lower()
    keep = names.isin(WANT)
    if not keep.any():
        raise ValueError("index file has none of Nifty 50, India VIX, Nifty Bank, Nifty Next 50")
    out = pd.DataFrame({"index": names[keep].map(WANT), "close": pd.to_numeric(df.loc[keep, close].str.replace(",", ""), errors="coerce")})
    if dt:
        out["date"] = pd.to_datetime(df.loc[keep, dt], errors="coerce", format="mixed", dayfirst=True)
    elif expect:
        out["date"] = pd.Timestamp(expect)
    else:
        raise ValueError("index file has no date column")
    out = out.dropna(subset=["date", "close"])
    if out.empty:
        raise ValueError("index file parsed but holds no usable rows")
    if expect is not None and out["date"].dt.date.mode().iloc[0] != expect:
        from backend.data.bhavcopy import StaleFile

        raise StaleFile(f"asked for {expect} but the index file is for {out['date'].dt.date.mode().iloc[0]}")
    return out[["date", "index", "close"]].reset_index(drop=True)


def download_index_day(d: date, client, cache_dir: Path, delay: float = 2.0) -> pd.DataFrame | None:
    raw_dir = cache_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    f, none = raw_dir / f"idx_{d:%Y%m%d}.csv", raw_dir / f"idx_{d:%Y%m%d}.none"
    if f.exists():
        return parse_index_file(f.read_bytes(), d)
    if none.exists():
        return None
    for attempt in range(3):
        r = client.get(URL.format(d=d))
        if r.status_code == 200:
            df = parse_index_file(r.content, d)
            f.write_bytes(r.content)
            time.sleep(delay)
            return df
        if r.status_code == 404:
            if (date.today() - d).days > 7:
                none.write_text("404")
            time.sleep(delay)
            return None
        if r.status_code in (403, 429):
            time.sleep(delay * (attempt + 2) * 2)
            continue
        r.raise_for_status()
    raise RuntimeError(f"NSE kept refusing the index file request for {d} (403/429).")


def rebuild_indices(cache_dir: Path) -> int:
    frames = []
    for f in sorted((cache_dir / "raw").glob("idx_*.csv")):
        try:
            frames.append(parse_index_file(f.read_bytes()))
        except ValueError:
            continue
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["date", "index"], keep="last").sort_values(["index", "date"])
    df.to_csv(cache_dir / "indices.csv.gz", index=False, compression="gzip")
    return len(df)


def load_indices(cache_dir: Path) -> pd.DataFrame | None:
    p = cache_dir / "indices.csv.gz"
    return pd.read_csv(p, parse_dates=["date"]) if p.exists() else None
