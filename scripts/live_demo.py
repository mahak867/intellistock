"""
Test the forecaster on REAL NSE data and report honestly what works.

    pip install yfinance pandas scikit-learn numpy
    python scripts/live_demo.py                       # 8 NIFTY stocks
    python scripts/live_demo.py TCS INFY --horizon 5
    python scripts/live_demo.py --synthetic           # offline check, fake prices

For each stock it runs the walk-forward test twice: price history only, and
with NIFTY 50 + India VIX added. It reports direction accuracy, whether the
direction forecast has a statistically real edge over "no change", whether the
volatility forecast beats a naive one, and how often the 80% range held.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from ml.forecast.quick_forecast import forecast  # noqa: E402
from ml.forecast.synthetic import synthetic_ohlcv  # noqa: E402

DEFAULT = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "MARUTI"]


def _download(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(symbol, period="6y", interval="1d", auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"no data for {symbol}")
    df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.dropna(subset=["close"])


def load_market(synthetic: bool) -> pd.DataFrame | None:
    if synthetic:
        idx = synthetic_ohlcv("NIFTY", 900)
        vix = (idx["close"].pct_change().rolling(10).std() * 100 * 16).bfill()
        return pd.DataFrame({"index_close": idx["close"], "vix": vix})
    try:
        nifty, vix = _download("^NSEI"), _download("^INDIAVIX")
        return pd.DataFrame({"index_close": nifty["close"], "vix": vix["close"]})
    except Exception as e:
        print(f"(market index/VIX unavailable: {e}; running price-only)")
        return None


def load(ticker: str, synthetic: bool) -> pd.DataFrame:
    return synthetic_ohlcv(ticker, 900) if synthetic else _download(f"{ticker}.NS")[["open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", default=DEFAULT)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()

    market = load_market(a.synthetic)
    rows, edge_p, edge_m, vol_wins, n = [], 0, 0, 0, 0
    for t in a.tickers:
        try:
            df = load(t.upper(), a.synthetic)
            base = forecast(df, a.horizon)["metrics"]
            full = forecast(df, a.horizon, market=market) if market is not None else None
            fm = full["metrics"] if full else base
            last = (full or forecast(df, a.horizon))["fan"][-1]
        except Exception as e:
            print(f"{t}: skipped ({e})")
            continue
        n += 1
        edge_p += base["has_edge"]
        edge_m += fm["has_edge"]
        vol_wins += fm["vol_beats_naive"]
        rows.append({
            "ticker": t.upper(),
            "days": base["walk_forward_samples"],
            "direction": f"{base['directional_accuracy']:.0%}",
            "edge(price)": "YES" if base["has_edge"] else "no",
            "edge(+mkt)": "YES" if fm["has_edge"] else "no",
            "vol>naive": "yes" if fm["vol_beats_naive"] else "no",
            "range_hits": f"{fm['band_coverage_80']:.0%}",
            f"{a.horizon}d_range": f"{last['lo']:.0f}-{last['hi']:.0f} (mid {last['mean']:.0f})",
        })
    if not rows:
        sys.exit("No tickers could be loaded.")
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\nDirection edge: {edge_p}/{n} price-only, {edge_m}/{n} with market features.")
    print(f"Volatility forecast beat naive on {vol_wins}/{n}.")
    print("'edge' means a statistically significant gain over assuming no change. "
          "Without it the app shows the range only. Not investment advice.")


if __name__ == "__main__":
    main()
