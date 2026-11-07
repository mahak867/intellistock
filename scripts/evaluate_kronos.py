"""Does Kronos earn a place in the app? Test it on NSE prices before anyone sees its forecast.

    pip install -r requirements-kronos.txt
    python scripts/evaluate_kronos.py run TCS INFY --out results/        # one JSON per stock
    python scripts/evaluate_kronos.py summary results/                    # the scorecard (markdown)

For each stock: adjusted daily prices from Yahoo Finance (5 years). Every `--step` trading days over the last
`--span` days, Kronos sees the previous `--context` days only and draws `--samples` paths `--horizon` days ahead.
Origins are `--step` days apart, so no two forecasts share a scored day (the scores are independent).

Scored at 5 and 10 days, in log returns from the last close:
  * range: how often the real price landed inside Kronos's 10th-90th percentile (should be close to 80%)
  * pinball loss at the 10th, 50th and 90th percentiles, against the app-style baseline: the stock's own past
    h-day returns over the same context window (lower is better; the baseline needs no model at all)
  * middle forecast error against "no change"
  * direction: how often the median got the sign right, against always-up; and the app's edge test
    (t < -2 on absolute error vs no change). Many stocks are tested, so about 1 in 40 passes by luck.

Pass mark to ship a Kronos range in the app: range coverage within 75-85% on average, and pinball loss below the
baseline on most stocks. Direction is reported but never shown as a call unless the edge test passes widely.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

QS = (0.1, 0.5, 0.9)
HS = (5, 10)


def pinball(y: np.ndarray, q: np.ndarray) -> float:
    """Mean pinball loss over QS. y: (n,), q: (len(QS), n)."""
    return float(np.mean([np.mean(np.maximum(a * (y - q[i]), (a - 1) * (y - q[i]))) for i, a in enumerate(QS)]))


def load(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    d = yf.download(f"{ticker}.NS", period="5y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    d.index = pd.DatetimeIndex(d.index).tz_localize(None)
    return d


def evaluate(ticker: str, df: pd.DataFrame, kp, context: int, span: int, step: int, samples: int, batch: int) -> dict:
    H = max(HS)
    lc = np.log(df["close"].to_numpy())
    origins = list(range(len(df) - H - span, len(df) - H, step))
    origins = [o for o in origins if o >= context]
    if len(origins) < 8:
        raise ValueError(f"only {len(origins)} origins; need more history")
    paths = []
    for i in range(0, len(origins), batch):
        chunk = origins[i:i + batch]
        paths.append(kp.paths([df.iloc[o - context:o] for o in chunk], H, samples, seed=i))
    P = np.log(np.concatenate(paths))                             # (n, samples, H), log prices
    out = {"ticker": ticker, "origins": len(origins), "from": str(df.index[origins[0]].date()),
           "to": str(df.index[origins[-1]].date()), "samples": samples, "context": context}
    for h in HS:
        base = np.array([lc[o - 1] for o in origins])             # last close the model saw
        y = np.array([lc[o - 1 + h] for o in origins]) - base     # real h-day log return
        kq = np.quantile(P[:, :, h - 1], QS, axis=1) - base       # Kronos quantiles, (3, n)
        hist = []                                                  # baseline: past h-day returns, same window
        for o in origins:
            w = lc[o - context:o]
            hist.append(np.quantile(w[h:] - w[:-h], QS))
        bq = np.array(hist).T
        med = kq[1]
        d = np.abs(y - med) - np.abs(y)
        se = d.std(ddof=1) / np.sqrt(len(d))
        t = float(d.mean() / se) if se > 0 else 0.0
        out[f"h{h}"] = {
            "coverage": float(np.mean((y >= kq[0]) & (y <= kq[2]))),
            "baseline_coverage": float(np.mean((y >= bq[0]) & (y <= bq[2]))),
            "pinball": pinball(y, kq), "baseline_pinball": pinball(y, bq),
            "mae": float(np.mean(np.abs(y - med))), "no_change_mae": float(np.mean(np.abs(y))),
            "direction": float(np.mean(np.sign(med) == np.sign(y))), "up_rate": float(np.mean(y > 0)),
            "edge_t": t, "edge": bool(d.mean() < 0 and t < -2.0),
            "width": float(np.mean(kq[2] - kq[0])), "baseline_width": float(np.mean(bq[2] - bq[0])),
        }
    return out


def run(a) -> int:
    from ml.kronos.forecast import KronosPaths
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    kp = KronosPaths()
    bad = 0
    for t in a.tickers:
        f = out / f"{t}.json"
        if f.exists():
            continue
        t0 = time.time()
        try:
            r = evaluate(t, load(t), kp, a.context, a.span, a.step, a.samples, a.batch)
        except Exception as e:  # one bad stock must not sink the shard
            print(f"{t}: FAILED {type(e).__name__}: {e}", flush=True)
            bad += 1
            continue
        f.write_text(json.dumps(r, indent=1))
        h = r["h10"]
        print(f"{t}: {r['origins']} origins in {time.time() - t0:.0f}s  10d range {h['coverage']:.0%} "
              f"pinball {h['pinball']:.4f} vs {h['baseline_pinball']:.4f}  dir {h['direction']:.0%}", flush=True)
    return 1 if bad == len(a.tickers) else 0


def summary(a) -> int:
    rs = [json.loads(p.read_text()) for p in sorted(Path(a.dir).glob("*.json"))]
    if not rs:
        print("No results.")
        return 1
    n = len(rs)
    lines = [f"## Kronos-small on NSE: {n} stocks, {sum(r['origins'] for r in rs)} forecasts",
             f"{rs[0]['from']} to {rs[0]['to']}, {rs[0]['samples']} paths each, {rs[0]['context']} days of context. "
             "Origins 20 trading days apart, so every scored day is used once.", "",
             "| Test | 5 days | 10 days |", "|---|---|---|"]
    def row(name, f):
        lines.append(f"| {name} | " + " | ".join(f(h) for h in HS) + " |")
    col = lambda h, k: np.array([r[f"h{h}"][k] for r in rs])  # noqa: E731
    row("Real price inside the 10-90% range (target 80%)", lambda h: f"{col(h,'coverage').mean():.1%} (history baseline {col(h,'baseline_coverage').mean():.1%})")
    row("Range width, average", lambda h: f"{col(h,'width').mean():.1%} (baseline {col(h,'baseline_width').mean():.1%})")
    row("Pinball loss better than the history baseline", lambda h: f"{int((col(h,'pinball') < col(h,'baseline_pinball')).sum())} of {n} stocks")
    row("Pinball loss, average (lower is better)", lambda h: f"{col(h,'pinball').mean():.4f} vs {col(h,'baseline_pinball').mean():.4f}")
    row("Middle forecast beats no change (error)", lambda h: f"{int((col(h,'mae') < col(h,'no_change_mae')).sum())} of {n} stocks")
    row("Direction hit rate (always-up baseline)", lambda h: f"{col(h,'direction').mean():.1%} ({col(h,'up_rate').mean():.1%})")
    row("Stocks passing the edge test (luck gives about 1)", lambda h: f"{int(col(h,'edge').sum())} of {n}")
    cov = col(10, "coverage").mean()
    wins = int((col(10, "pinball") < col(10, "baseline_pinball")).sum())
    ok = 0.75 <= cov <= 0.85 and wins > n / 2
    lines += ["", f"**Verdict: {'passes' if ok else 'does not pass'} the bar to show a Kronos range in the app** "
              f"(10-day coverage {cov:.1%}, needs 75-85%; better pinball on {wins} of {n}, needs more than half)."]
    text = "\n".join(lines)
    print(text)
    if a.md:
        Path(a.md).write_text(text + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("tickers", nargs="+")
    r.add_argument("--out", default="kronos_results")
    r.add_argument("--context", type=int, default=256)
    r.add_argument("--span", type=int, default=480, help="trading days of origins, ending 10 days before today")
    r.add_argument("--step", type=int, default=20)
    r.add_argument("--samples", type=int, default=30)
    r.add_argument("--batch", type=int, default=4)
    s = sub.add_parser("summary")
    s.add_argument("dir")
    s.add_argument("--md")
    a = ap.parse_args()
    return run(a) if a.cmd == "run" else summary(a)


if __name__ == "__main__":
    sys.exit(main())
