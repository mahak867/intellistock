"""Load licensed vendor data into the local store (DATA_PROVIDER=local).

    python scripts/import_vendor_csv.py vendor.csv --adjusted

The CSV needs: date, symbol, open, high, low, close, volume (any column order; names are matched loosely).
Use prices your vendor has ALREADY adjusted for splits and bonus: the exchange's previous-close
column that this project normally uses to detect them is not there, so nothing is adjusted here.
Pass --adjusted to confirm that. Writes DATA_DIR/prices.csv.gz and replaces what was there.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

NAMES = {"date": ["date", "timestamp", "datetime"], "symbol": ["symbol", "ticker", "scrip"], "open": ["open"], "high": ["high"],
         "low": ["low"], "close": ["close", "adj close", "adj_close"], "volume": ["volume", "vol"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--adjusted", action="store_true", help="confirm the vendor prices are already split/bonus adjusted")
    ap.add_argument("--dir", default=os.environ.get("DATA_DIR", "./data"))
    a = ap.parse_args()
    if not a.adjusted:
        print("Refusing: pass --adjusted to confirm the vendor prices are already split and bonus adjusted (see the docstring).")
        return 2
    df = pd.read_csv(a.file)
    low = {c.strip().lower(): c for c in df.columns}
    pick = {}
    for k, opts in NAMES.items():
        hit = next((low[o] for o in opts if o in low), None)
        if hit is None:
            print(f"Missing a '{k}' column. Found: {list(df.columns)}")
            return 1
        pick[k] = hit
    out = pd.DataFrame({k: df[v] for k, v in pick.items()})
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out = out.dropna(subset=["date", "close"]).sort_values(["symbol", "date"])
    out["series"] = "EQ"
    out["prev_close"] = out.groupby("symbol")["close"].shift(1).fillna(out["close"])
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    out[["date", "symbol", "series", "open", "high", "low", "close", "prev_close", "volume"]].to_csv(d / "prices.csv.gz", index=False, compression="gzip")
    (d / "FIXTURE").unlink(missing_ok=True)
    print(f"Stored {len(out)} rows, {out['symbol'].nunique()} symbols, {out['date'].min().date()} to {out['date'].max().date()} in {d.resolve()}")
    print("Now set DATA_PROVIDER=local in .env and restart the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
