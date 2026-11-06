"""Screen stocks on fundamentals YOU supply (for example a Screener.in export). IntelliStock does not ship or fetch
fundamentals, so every number here is the number in your file. Rows missing a field you filter on are left out and counted.

Percent columns are plain percents (ROE 18 means 18%). Debt to equity is a ratio."""
from __future__ import annotations

import io
import math
import re

import pandas as pd

from backend.tools import fundamentals as FU

FIELDS = ("pe", "pb", "roe", "roce", "debt_equity", "promoter_holding", "pledge_pct", "profit_cagr_3y", "sales_growth",
          "market_cap_cr", "dividend_yield", "cfo_to_pat")

# Normalised header (lowercase letters and digits only) -> field. Covers common Screener.in / Trendlyne / manual headers.
ALIASES = {
    "pe": "pe", "peratio": "pe", "pricetoearnings": "pe", "stockpe": "pe",
    "pb": "pb", "pbratio": "pb", "pricetobook": "pb", "pricetobookvalue": "pb",
    "roe": "roe", "roepct": "roe", "returnonequity": "roe", "roe5yr": "roe",
    "roce": "roce", "rocepct": "roce", "returnoncapitalemployed": "roce",
    "debtequity": "debt_equity", "debttoequity": "debt_equity", "debteq": "debt_equity", "de": "debt_equity", "debtequityratio": "debt_equity",
    "promoterholding": "promoter_holding", "promoterholdingpct": "promoter_holding", "promhold": "promoter_holding", "promoter": "promoter_holding",
    "pledge": "pledge_pct", "pledgepct": "pledge_pct", "pledged": "pledge_pct", "pledgedpct": "pledge_pct",
    "profitcagr3y": "profit_cagr_3y", "profitvar3yrs": "profit_cagr_3y", "profitgrowth3y": "profit_cagr_3y", "profitgrowth3yrs": "profit_cagr_3y", "profitgrowth3yrspct": "profit_cagr_3y",
    "salesgrowth": "sales_growth", "salesgrowth3yrs": "sales_growth", "salesgrowth3y": "sales_growth", "salesvar3yrs": "sales_growth", "salescagr3y": "sales_growth",
    "marketcapcr": "market_cap_cr", "marcaprscr": "market_cap_cr", "marketcap": "market_cap_cr", "marketcaprscr": "market_cap_cr", "mcapcr": "market_cap_cr",
    "dividendyield": "dividend_yield", "divyld": "dividend_yield", "divyldpct": "dividend_yield", "dividendyieldpct": "dividend_yield",
    "cfotopat": "cfo_to_pat", "cfopat": "cfo_to_pat",
}
NAME_COLS = ("symbol", "ticker", "nsecode", "nsesymbol", "scrip", "name", "company", "companyname", "stock")
MAX_ROWS = 5000
MAX_FILTERS = 12


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "").replace("%", "").replace("₹", "")
    if s in ("", "-", "--", "nan", "NaN", "None", "NA", "N/A"):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def parse(csv_text: str) -> tuple[pd.DataFrame, dict]:
    """Returns (rows with symbol + known fields, info about which columns were recognised)."""
    try:
        raw = pd.read_csv(io.StringIO(csv_text), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"Could not read the CSV: {type(e).__name__}") from None
    if raw.empty:
        raise ValueError("The CSV has no rows.")
    if len(raw) > MAX_ROWS:
        raise ValueError(f"Too many rows ({len(raw)}); the limit is {MAX_ROWS}.")
    norm = {c: _norm(c) for c in raw.columns}
    name_col = next((c for want in NAME_COLS for c, n in norm.items() if n == want), None)
    if name_col is None:
        raise ValueError(f"CSV needs a symbol or name column. Found: {list(raw.columns)[:12]}")
    found: dict[str, str] = {}
    for c, n in norm.items():
        f = ALIASES.get(n)
        if f and f not in found:
            found[f] = c
    if not found:
        raise ValueError(f"No known fundamentals columns (like P/E, ROE, ROCE, Debt/Equity). Found: {list(raw.columns)[:12]}")
    out = pd.DataFrame({"symbol": raw[name_col].astype(str).str.strip().str.upper()})
    for f, c in found.items():
        out[f] = [_num(v) for v in raw[c]]
    out = out[out.symbol != ""].drop_duplicates("symbol", keep="last").reset_index(drop=True)
    return out, {"name_column": name_col, "recognised": {f: c for f, c in found.items()}, "rows": int(len(out))}


def screen(csv_text: str, filters: list[dict], sort: str = "quality", limit: int = 50) -> dict:
    if len(filters) > MAX_FILTERS:
        raise ValueError(f"At most {MAX_FILTERS} filters.")
    if sort != "quality" and sort not in FIELDS:
        raise ValueError(f"Cannot sort by {sort}.")
    df, info = parse(csv_text)
    keep = pd.Series(True, index=df.index)
    excluded: dict[str, int] = {}
    unavailable = []
    for f in filters:
        name, lo, hi = f["field"], f.get("min"), f.get("max")
        if name not in FIELDS:
            raise ValueError(f"Unknown field {name}.")
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"{name}: min is above max.")
        if name not in df.columns:
            unavailable.append(name)
            keep &= False  # a filter on a column the file does not have matches nothing, never everything
            continue
        col = df[name]
        missing = col.isna() & keep
        excluded[name] = int(missing.sum())
        ok = col.notna()
        if lo is not None:
            ok &= col >= lo
        if hi is not None:
            ok &= col <= hi
        keep &= ok
    hit = df[keep].copy()
    scored = []
    for _, r in hit.iterrows():
        q = FU.quality_score({k: (None if pd.isna(r[k]) else float(r[k])) for k in df.columns if k in FU.COMPONENTS})
        scored.append((q["score"], q.get("coverage_pct", 0.0), q["grade"], q["missing"]))
    hit["quality_score"] = [s[0] for s in scored]
    hit["quality_coverage_pct"] = [s[1] for s in scored]
    hit["quality_grade"] = [s[2] for s in scored]
    if sort == "quality":
        hit = hit.sort_values("quality_score", ascending=False, na_position="last")
    else:
        hit = hit.sort_values(sort, ascending=sort in ("pe", "pb", "debt_equity", "pledge_pct"), na_position="last")
    shown = hit.head(limit)
    rows = [{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in rec.items()} for rec in shown.to_dict("records")]
    return {"total": info["rows"], "matched": int(len(hit)), "shown": len(rows), "rows": rows, "columns_recognised": info["recognised"],
            "left_out_for_missing_data": excluded, "filters_on_missing_columns": unavailable,
            "note": "Numbers are exactly what you uploaded. The quality score is a transparent rule (see Fundamentals score), not a forecast or a recommendation."}
