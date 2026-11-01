"""
OPTIONAL second opinion: Amazon Chronos-Bolt, a pretrained time-series model,
versus "no change" on the same walk-forward windows. Needs Hugging Face access.

    pip install chronos-forecasting torch yfinance pandas numpy
    python scripts/benchmark_chronos.py TCS INFY --horizon 5

NOTE: written against the documented Chronos-Bolt API but NOT run in the
development sandbox (no Hugging Face access there). If the API changed, adjust
the two marked lines. Apache-2.0 model: amazon/chronos-bolt-tiny.
"""
from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd
import torch

warnings.filterwarnings("ignore")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="*", default=["RELIANCE", "TCS", "INFY", "HDFCBANK"])
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--windows", type=int, default=150)
    a = ap.parse_args()

    import yfinance as yf
    from chronos import BaseChronosPipeline  # MARKED: API entry point

    pipe = BaseChronosPipeline.from_pretrained("amazon/chronos-bolt-tiny", device_map="cpu")
    rows = []
    for t in a.tickers:
        px = yf.download(f"{t}.NS", period="4y", interval="1d", auto_adjust=True, progress=False)["Close"].squeeze().dropna()
        lp = np.log(px.to_numpy())
        errs_m, errs_n, hits, cover = [], [], [], []
        for i in range(len(lp) - a.horizon - a.windows, len(lp) - a.horizon, 5):
            ctx = torch.tensor(lp[max(0, i - 512): i], dtype=torch.float32)
            q, _ = pipe.predict_quantiles(  # MARKED: returns (quantiles, mean)
                ctx.unsqueeze(0), prediction_length=a.horizon, quantile_levels=[0.1, 0.5, 0.9]
            )
            lo, med, hi = (float(q[0, -1, j]) - lp[i - 1] for j in range(3))
            real = lp[i - 1 + a.horizon] - lp[i - 1]
            errs_m.append(abs(real - med)); errs_n.append(abs(real))
            hits.append(np.sign(med) == np.sign(real)); cover.append(lo <= real <= hi)
        rows.append({"ticker": t, "direction": f"{np.mean(hits):.0%}",
                     "model_err": f"{np.mean(errs_m):.2%}", "no_change_err": f"{np.mean(errs_n):.2%}",
                     "beats": "yes" if np.mean(errs_m) < np.mean(errs_n) else "no", "range_hits": f"{np.mean(cover):.0%}"})
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
