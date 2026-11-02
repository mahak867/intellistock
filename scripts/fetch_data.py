"""Download NSE end-of-day files and build the local price store.

    python scripts/fetch_data.py --years 3
    python scripts/fetch_data.py --start 2024-01-02 --end 2026-10-30 --delay 3

Then set DATA_PROVIDER=nse in .env and restart the API. Safe to re-run: finished days are cached
under DATA_DIR (default ./data) and are not downloaded again. NSE's files are NSE's: read their terms
before using this data in anything you sell.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from backend.data import store  # noqa: E402
from backend.data.bhavcopy import DEFAULT_UA  # noqa: E402
from backend.data.prices import build_ohlcv  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=3.0)
    ap.add_argument("--start", type=date.fromisoformat)
    ap.add_argument("--end", type=date.fromisoformat, default=date.today())
    ap.add_argument("--delay", type=float, default=2.0, help="seconds between requests; be polite")
    ap.add_argument("--dir", default=os.environ.get("DATA_DIR", "./data"))
    a = ap.parse_args()
    start = a.start or (a.end - timedelta(days=int(a.years * 365)))
    cache = Path(a.dir)
    headers = {"User-Agent": os.environ.get("DATA_USER_AGENT", DEFAULT_UA), "Accept": "*/*"}
    print(f"Fetching {start} to {a.end} into {cache.resolve()} (about {sum(1 for _ in store.weekdays(start, a.end))} weekdays)")
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as c:
        res = store.fetch_range(start, a.end, cache, c, a.delay, progress=lambda s: print(" ", s, flush=True))
    print("\nSummary:", {k: v for k, v in res.items() if k != "failed"})
    for f in res["failed"][:10]:
        print("  FAILED", f)
    rows = store.load(cache)
    if rows is None:
        print("\nNo data was stored. Nothing to check. If every day failed, open the NSE file URL in your browser to see what it returns.")
        return 1
    print(f"\nStore: {rows['symbol'].nunique()} symbols, {rows['date'].min().date()} to {rows['date'].max().date()}")
    print("Spot check (read these against a chart you trust):")
    for s in ("RELIANCE", "TCS", "HDFCBANK", "INFY"):
        try:
            df, q = build_ohlcv(rows, s)
            print(f"  {s}: {q['rows']} days, last close {df['close'].iloc[-1]:.2f} on {q['last']}, "
                  f"{len(q['corporate_actions_adjusted'])} adjustments {[x['date'] + ' x' + format(x['factor'], '.3f') for x in q['corporate_actions_adjusted']]}")
            for i in q["issues"][:3]:
                print("     note:", i)
        except KeyError:
            print(f"  {s}: not found")
    print("\nNext: put DATA_PROVIDER=nse in .env and restart the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
