"""Portfolio tracker: holdings, XIRR vs a benchmark, allocation and concentration, correlation."""
from __future__ import annotations

import io
from datetime import date

import numpy as np
import pandas as pd


def parse_holdings(csv_text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(csv_text))
    low = {c.lower().strip(): c for c in df.columns}
    pick = lambda *n: next((low[x] for x in n if x in low), None)  # noqa: E731
    sym, qty, avg = pick("symbol", "instrument", "scrip"), pick("qty", "quantity"), pick("avg_price", "average price", "avg cost", "avg. cost", "average_price")
    if not (sym and qty and avg):
        raise ValueError(f"CSV needs symbol, qty and avg_price columns. Found: {list(df.columns)}")
    sec = pick("sector")
    out = pd.DataFrame({"symbol": df[sym].astype(str).str.upper().str.strip(),
                        "qty": pd.to_numeric(df[qty], errors="coerce"),
                        "avg_price": pd.to_numeric(df[avg], errors="coerce"),
                        "sector": df[sec].astype(str) if sec else "Unknown"}).dropna(subset=["qty", "avg_price"])
    return out[out.qty > 0].reset_index(drop=True)


def xirr(flows: list[tuple[date, float]], guess_lo: float = -0.999, guess_hi: float = 100.0) -> float | None:
    """Annualised internal rate of return on dated cash flows (negative = money in).
    Actual/365 day count, like Excel's XIRR. None if no sign change."""
    if len(flows) < 2:
        return None
    vals = [v for _, v in flows]
    if not (min(vals) < 0 < max(vals)):
        return None
    t0 = min(d for d, _ in flows)
    yrs = [((d - t0).days / 365.0, v) for d, v in flows]

    def npv(r: float) -> float:
        return sum(v / (1 + r) ** t for t, v in yrs)

    lo, hi = guess_lo, guess_hi
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def benchmark_xirr(flows: list[tuple[date, float]], index_close: pd.Series, end_value: float, end: date) -> float | None:
    """What if every rupee you invested had gone into the index on the same day?
    Contributions (negative flows) buy index units; withdrawals (positive) sell units."""
    s = index_close.sort_index()

    def px(d: date) -> float:
        i = s.index.searchsorted(pd.Timestamp(d), side="right") - 1
        if i < 0:
            raise ValueError(f"no index data on or before {d}")
        return float(s.iloc[i])

    units = 0.0
    for d, v in flows:
        units += (-v) / px(d)
    bench_end = units * px(end)
    return xirr(list(flows) + [(end, bench_end)])


def allocation(holdings: pd.DataFrame, prices: dict[str, float]) -> dict:
    h = holdings.copy()
    h["price"] = h.symbol.map(prices)
    missing = h[h.price.isna()].symbol.tolist()
    h = h.dropna(subset=["price"])
    h["value"] = h.qty * h.price
    h["cost"] = h.qty * h.avg_price
    total = float(h.value.sum())
    h["weight"] = h.value / total
    sector = h.groupby("sector").value.sum() / total
    return {
        "total_value": total, "total_cost": float(h.cost.sum()), "unrealised_pnl": total - float(h.cost.sum()),
        "positions": h[["symbol", "qty", "avg_price", "price", "value", "weight"]].sort_values("weight", ascending=False).to_dict("records"),
        "sector_weights": sector.sort_values(ascending=False).to_dict(),
        "top1": float(h.weight.max()), "top3": float(h.weight.nlargest(3).sum()),
        "hhi": float((h.weight ** 2).sum()), "effective_positions": float(1 / (h.weight ** 2).sum()),
        "missing_prices": missing,
    }


def correlation(returns: pd.DataFrame) -> dict:
    c = returns.corr()
    pairs = [(a, b, float(c.loc[a, b])) for i, a in enumerate(c.columns) for b in c.columns[i + 1:]]
    pairs.sort(key=lambda x: -x[2])
    return {"matrix": c.round(3).to_dict(), "most_correlated": pairs[:3],
            "avg_pairwise": float(np.mean([p[2] for p in pairs])) if pairs else None}
