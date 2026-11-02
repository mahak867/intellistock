"""Check, on YOUR machine, that NSE's current files match what this project expects.

    python scripts/check_nse_format.py                  # downloads the latest available equity and index file and checks both
    python scripts/check_nse_format.py --file path.csv  # check a file you downloaded in a browser (zip or csv)
    python scripts/check_nse_format.py --file idx.csv --kind index

Paste the output back if it says FAIL: it lists the exact columns NSE sent, which is all a fix needs.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pandas as pd  # noqa: E402

from backend.data import indices  # noqa: E402
from backend.data.bhavcopy import DEFAULT_UA, URL, parse_udiff, resolve_columns  # noqa: E402


def check_equity(raw: bytes) -> list[str]:
    import io
    import zipfile

    body = zipfile.ZipFile(io.BytesIO(raw)).read(next(n for n in zipfile.ZipFile(io.BytesIO(raw)).namelist() if n.lower().endswith(".csv"))) if raw[:2] == b"PK" else raw
    cols = list(pd.read_csv(io.BytesIO(body), nrows=0).columns)
    print("Columns NSE sent:", [c.strip() for c in cols])
    mapping, missing = resolve_columns([c.strip() for c in cols])
    print("Matched fields:", mapping)
    fails = []
    if missing:
        return [f"cannot find fields {missing}"]
    df = parse_udiff(raw)
    print(f"Rows: {len(df)}   Date in file: {df['date'].dt.date.mode().iloc[0]}   Series: {df['series'].value_counts().head(5).to_dict()}")
    eq = df[df["series"] == "EQ"]
    print("Sample:\n", eq.head(3).to_string(index=False))
    if len(eq) < 1000:
        fails.append(f"only {len(eq)} EQ rows; a normal day has around 2,000+")
    ok = ((eq["low"] <= eq["close"] * 1.0001) & (eq["close"] <= eq["high"] * 1.0001)).mean()
    if ok < 0.98:
        fails.append(f"close is outside the day's range on {1 - ok:.1%} of rows: columns may be mislabelled")
    ratio = (eq["close"] / eq["prev_close"]).dropna()
    if not (0.5 < ratio.median() < 2) or (ratio.sub(1).abs() < 0.3).mean() < 0.9:
        fails.append("close vs previous close looks wrong for most rows")
    return fails


def check_index(raw: bytes) -> list[str]:
    df = indices.parse_index_file(raw)
    print("Index rows kept:\n", df.to_string(index=False))
    need = {"NIFTY 50", "INDIA VIX"} - set(df["index"])
    return [f"missing {sorted(need)}"] if need else []


def latest(client, url_fn, binary_ok=(200,)):
    d = date.today()
    for _ in range(12):
        if d.weekday() < 5:
            r = client.get(url_fn(d))
            print(f"  {d}: HTTP {r.status_code}")
            if r.status_code == 200:
                return d, r.content
        d -= timedelta(days=1)
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--kind", choices=["equity", "index"], default="equity")
    a = ap.parse_args()
    results: dict[str, list[str]] = {}
    if a.file:
        raw = Path(a.file).read_bytes()
        results[a.kind] = (check_equity if a.kind == "equity" else check_index)(raw)
    else:
        headers = {"User-Agent": os.environ.get("DATA_USER_AGENT", DEFAULT_UA), "Accept": "*/*"}
        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as c:
            print("Equity file:")
            d, raw = latest(c, lambda d: URL.format(d=d))
            results["equity"] = check_equity(raw) if raw else ["could not download any file in the last 12 days: open the URL in a browser and use --file"]
            print("\nIndex file:")
            d, raw = latest(c, lambda d: indices.URL.format(d=d))
            results["index"] = check_index(raw) if raw else ["could not download any index file: open the URL in a browser and use --file --kind index"]
    print("\n=== RESULT ===")
    bad = False
    for k, f in results.items():
        print(f"{k}: {'PASS' if not f else 'FAIL'}")
        for x in f:
            print("   -", x)
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
