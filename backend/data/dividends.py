"""Cash dividends, so price series can be turned into total-return series.

NSE's daily price file does not carry dividends, and this sandbox cannot reach NSE's corporate-actions
feed, so you supply the file: either a plain CSV (symbol, ex_date, amount) or an export of NSE's
corporate-actions table with a Purpose column such as "Interim Dividend - Rs 5 Per Share".
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd

AMOUNT = re.compile(r"(?:rs\.?|re\.?|inr|₹)\s*\.?\s*([0-9]+(?:\.[0-9]+)?)", re.I)


def amount_from_purpose(text: str) -> float | None:
    """'Interim Dividend - Rs 5 Per Share' -> 5.0. None when it is not a cash dividend or has no amount."""
    t = str(text)
    if "dividend" not in t.lower():
        return None
    m = AMOUNT.search(t)
    return float(m.group(1)) if m else None


def _find(cols, *names):
    low = {str(c).strip().lower().replace(" ", "").replace("_", "").replace("-", ""): c for c in cols}
    return next((low[n] for n in names if n in low), None)


def parse_dividends(csv_text: str) -> pd.DataFrame:
    """-> symbol, ex_date, amount. Rows that are not dividends or have no amount are skipped and counted in .attrs['skipped']."""
    df = pd.read_csv(io.StringIO(csv_text), dtype=str, skipinitialspace=True)
    sym = _find(df.columns, "symbol", "tckrsymb")
    exd = _find(df.columns, "exdate", "exdt", "ex")
    if not (sym and exd):
        raise ValueError(f"dividends file needs symbol and ex_date columns. Found: {list(df.columns)}")
    amt = _find(df.columns, "amount", "dividend", "dividendamount")
    purpose = _find(df.columns, "purpose", "subject")
    rows, skipped = [], 0
    for _, r in df.iterrows():
        a = None
        if amt is not None and pd.notna(r[amt]):
            try:
                a = float(str(r[amt]).replace(",", ""))
            except ValueError:
                a = None
        if a is None and purpose is not None and pd.notna(r[purpose]):
            a = amount_from_purpose(r[purpose])
        d = pd.to_datetime(r[exd], errors="coerce", format="mixed", dayfirst=True)
        if a is None or a <= 0 or pd.isna(d) or not str(r[sym]).strip():
            skipped += 1
            continue
        rows.append({"symbol": str(r[sym]).strip().upper(), "ex_date": d.normalize(), "amount": a})
    out = pd.DataFrame(rows, columns=["symbol", "ex_date", "amount"]).drop_duplicates(["symbol", "ex_date", "amount"])
    out.attrs["skipped"] = skipped
    return out


def load_dividends(cache_dir: Path) -> pd.DataFrame | None:
    p = cache_dir / "dividends.csv"
    if not p.exists():
        return None
    return parse_dividends(p.read_text(encoding="utf-8"))
