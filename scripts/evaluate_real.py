"""Measure the forecast on real prices and print an honest scorecard.

    python scripts/evaluate_real.py --dir path/to/csvs --since 2016-01-01 --horizons 5,10,20

--dir takes a folder of one CSV per stock with columns Date, Open, High, Low, Close, Volume (the eod2_data layout:
https://github.com/BennyThadikaran/eod2_data, daily/). Prices should be adjusted for splits and bonuses.

For each stock and horizon it runs the same walk-forward test the app uses (train on the past, predict the future,
never peek) and reports:
  * direction: hit rate vs the "always up" baseline, and an edge test (needs t < -2 on squared-error loss vs no change)
  * volatility: error vs the naive "tomorrow looks like the last 20 days", and how often the 80% price range held
Because many stocks are tested, a few will look good by luck. The summary says how many to expect by chance.
Results are cached per stock and horizon in --out, so an interrupted run resumes.
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

MIN_DAYS = 600


def load_dir(folder: Path, since: str) -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(folder.glob("*.csv")):
        d = pd.read_csv(f, parse_dates=["Date"]).set_index("Date").sort_index()
        d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        d = d[~d.index.duplicated(keep="last")].loc[since:].dropna()
        d = d[(d.close > 0) & (d.volume >= 0)]
        if len(d) >= MIN_DAYS:
            out[f.stem.upper()] = d.astype(float)
    return out


def data_flags(d: pd.DataFrame) -> list[str]:
    r = d["close"].pct_change().abs()
    big = r[r > 0.25]
    return [f"{x.date()} moved {v * 100:.0f}% in a day (possible unadjusted split or bonus)" for x, v in big.items()]


def one(args) -> dict:
    sym, df, h = args
    from ml.forecast.quick_forecast import forecast

    res = forecast(df, h)
    m = res["metrics"]
    fwd = np.log(df["close"]).diff(h).shift(-h).dropna()
    up = float((fwd > 0).mean())
    return {"symbol": sym, "horizon": h, "rows": len(df), "up_rate": up, **m}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--since", default="2016-01-01")
    ap.add_argument("--horizons", default="5,10,20")
    ap.add_argument("--symbols", help="comma list to limit the run")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", default="evaluation.jsonl")
    a = ap.parse_args()

    data = load_dir(Path(a.dir), a.since)
    if a.symbols:
        keep = {s.strip().upper() for s in a.symbols.split(",")}
        data = {k: v for k, v in data.items() if k in keep}
    horizons = [int(x) for x in a.horizons.split(",")]
    out = Path(a.out)
    done = {}
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done[(r["symbol"], r["horizon"])] = r
    todo = [(s, d, h) for s, d in data.items() for h in horizons if (s, h) not in done]
    print(f"{len(data)} stocks, since {a.since}, horizons {horizons}: {len(done)} cached, {len(todo)} to run", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as ex, out.open("a") as fh:
        for r in ex.map(one, todo):
            done[(r["symbol"], r["horizon"])] = r
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            print(f"  {r['symbol']:11} h={r['horizon']:2} dir {r['directional_accuracy'] * 100:4.1f}% (always-up {r['up_rate'] * 100:4.1f}%) t={r['edge_t_stat']:+.2f}"
                  f"  vol beats naive: {r['vol_beats_naive']}  80% band held {r['band_coverage_80_holdout'] * 100:4.1f}% on newer data", flush=True)

    rows = pd.DataFrame([done[(s, h)] for s in data for h in horizons if (s, h) in done])
    if rows.empty:
        print("nothing evaluated")
        return 1
    print("\n=== SCORECARD (real prices, walk-forward, no peeking) ===")
    flags = {s: data_flags(d) for s, d in data.items()}
    for s, f in flags.items():
        if f:
            print(f"data warning {s}: {f[0]}" + (f" (+{len(f) - 1} more)" if len(f) > 1 else ""))
    for h in horizons:
        r = rows[rows.horizon == h]
        n = len(r)
        excess = (r.directional_accuracy - np.maximum(r.up_rate, 1 - r.up_rate)).mean()
        print(f"\nHorizon {h} days, {n} stocks")
        print(f"  direction hit rate        {r.directional_accuracy.mean() * 100:.1f}% on average (always-up baseline {r.up_rate.mean() * 100:.1f}%)")
        print(f"  beats always-up           {int((r.directional_accuracy > r.up_rate).sum())} of {n} stocks; mean {excess * 100:+.1f} points vs the better of up/down")
        print(f"  edge test passed (t<-2)   {int(r.has_edge.sum())} of {n}   (pure luck would pass about {0.025 * n:.1f})")
        print(f"  return error beats naive  {int(r.beats_naive.sum())} of {n}")
        print(f"  volatility beats naive    {int(r.vol_beats_naive.sum())} of {n}")
        c = r.band_coverage_80_holdout
        print(f"  80% range held (newer half, quantiles fitted on older half)  {c.mean() * 100:.1f}% on average (target 80%), worst {c.min() * 100:.0f}%, best {c.max() * 100:.0f}%")
        print(f"  typical range width       {r.band_width_pct.mean():.1f}% of price")
    print(f"\nrows saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
