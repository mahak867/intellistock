"""Local price store: a gzip CSV of every symbol-day, built from cached NSE files."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from backend.data import indices
from backend.data.bhavcopy import StaleFile, download_day

STORE = "prices.csv.gz"
DTYPES = {"symbol": "string", "series": "string"}


def weekdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def fetch_range(start: date, end: date, cache_dir: Path, client, delay: float = 2.0,
                progress: Callable[[str], None] = lambda s: None, with_indices: bool = True) -> dict:
    """Download every missing weekday (plus that day's index file), then rebuild the store from all cached raw files."""
    got, none, stale, failed = 0, 0, 0, []
    idx_days = 0
    for d in weekdays(start, end):
        try:
            df = download_day(d, client, cache_dir, delay)
        except StaleFile:
            stale += 1
            continue
        except Exception as e:  # keep going: one bad day must not lose the rest
            failed.append(f"{d}: {e}")
            if "refusing" in str(e):
                break
            continue
        got, none = (got + 1, none) if df is not None else (got, none + 1)
        progress(f"{d} {'ok' if df is not None else 'no file'}")
        if df is not None and with_indices:
            try:
                if indices.download_index_day(d, client, cache_dir, delay) is not None:
                    idx_days += 1
            except Exception as e:  # indices are optional: note it and carry on
                failed.append(f"{d} index file: {e}")
    n = rebuild(cache_dir)
    return {"downloaded_or_cached_days": got, "no_file_days": none, "stale_days": stale, "failed": failed, "store_rows": n,
            "index_days": idx_days, "index_rows": indices.rebuild_indices(cache_dir) if with_indices else 0}


def rebuild(cache_dir: Path) -> int:
    from backend.data.bhavcopy import parse_udiff

    frames = []
    for f in sorted((cache_dir / "raw").glob("*.csv.zip")):
        try:
            frames.append(parse_udiff(f.read_bytes()))
        except ValueError:
            continue
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True).drop_duplicates(["date", "symbol", "series"], keep="last").sort_values(["symbol", "date"])
    df.to_csv(cache_dir / STORE, index=False, compression="gzip")
    return len(df)


_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def load(cache_dir: Path) -> pd.DataFrame | None:
    p = cache_dir / STORE
    if not p.exists():
        return None
    m = p.stat().st_mtime
    hit = _cache.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    df = pd.read_csv(p, parse_dates=["date"], dtype=DTYPES)
    _cache[str(p)] = (m, df)
    return df
