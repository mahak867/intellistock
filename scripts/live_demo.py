"""
Run the ML forecaster on REAL NSE data and report how accurate it actually is.

    pip install yfinance pandas scikit-learn numpy
    python scripts/live_demo.py                       # default: 8 NIFTY stocks
    python scripts/live_demo.py TCS INFY --horizon 5
    python scripts/live_demo.py --synthetic           # offline check, fake prices

Needs internet access to Yahoo Finance. Prints per-stock walk-forward accuracy
versus a "price stays the same" baseline, then the latest forecast.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from ml.forecast.quick_forecast import forecast  # noqa: E402
from ml.forecast.synthetic import synthetic_ohlcv  # noqa: E402

DEFAULT = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "MARUTI"]


def load(ticker: str, synthetic: bool) -> pd.DataFrame:
    if synthetic:
        return synthetic_ohlcv(ticker, 900)
    import yfinance as yf

    df = yf.download(f"{ticker}.NS", period="5y", interval="1d", auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError("no data returned")
    df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].dropna()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", default=DEFAULT)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()

    rows, wins = [], 0
    for t in a.tickers:
        try:
            df = load(t.upper(), a.synthetic)
            res = forecast(df, a.horizon)
        except Exception as e:  # keep going on a bad ticker
            print(f"{t}: skipped ({e})")
            continue
        m, last = res["metrics"], res["fan"][-1]
        wins += m["beats_naive"]
        rows.append({
            "ticker": t.upper(),
            "days_tested": m["walk_forward_samples"],
            "direction_right": f"{m['directional_accuracy']:.0%}",
            "model_err": f"{m['mae_log_return']:.2%}",
            "no_change_err": f"{m['mae_naive_baseline']:.2%}",
            "beats_baseline": "yes" if m["beats_naive"] else "no",
            "band_hits": f"{m['band_coverage_80']:.0%}",
            f"{a.horizon}d_forecast": f"{last['mean']:.2f} ({last['lo']:.2f}-{last['hi']:.2f})",
        })
    if not rows:
        sys.exit("No tickers could be loaded.")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nBeat the no-change baseline on {wins} of {len(rows)} stocks. "
          "Direction near 50% and 'no' on the baseline means no usable edge. "
          "Forecasts are not investment advice.")


if __name__ == "__main__":
    main()
