"""Bring assets in from Indian statements.

* Depository CAS (NSDL / CDSL, one PDF for all your demat accounts): stocks, mutual funds, bonds and NPS.
* Broker holdings export (Zerodha Console, Groww, Upstox, Angel One...): CSV or Excel with symbol, quantity, average price.
* Bank statement (CSV or Excel from net banking): the latest balance, per account.
* Fixed deposits, PPF, EPF, gold and anything else: entered by hand; FDs grow at their rate until maturity.

Depository statements do not carry your purchase cost for stocks, so imported stocks use the statement price as cost
and are marked so; edit them for correct profit and returns.
"""
from __future__ import annotations

import io
import math
import re
from datetime import date

import pandas as pd

KINDS = ("bank", "fd", "rd", "ppf", "epf", "nps", "bond", "gold", "real_estate", "other")


def _f(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm")):
            raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str, engine="openpyxl")
        elif name.endswith(".xls"):
            raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str, engine="xlrd")
        else:
            import csv

            text = data.decode("utf-8-sig", errors="replace")
            lines = [l for l in text.splitlines() if l.strip()]
            delim = max((",", "\t", ";", "|"), key=lambda d: sum(l.count(d) for l in lines[:80]))
            rows = list(csv.reader(lines, delimiter=delim))  # title rows above the table have fewer cells: pad them
            width = max((len(r) for r in rows), default=0)
            raw = pd.DataFrame([r + [""] * (width - len(r)) for r in rows], dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read the file ({type(e).__name__}). Use CSV or Excel.") from None
    return raw.fillna("")


def _header_row(raw: pd.DataFrame, must: tuple[str, ...]) -> int:
    """Bank and broker files have logos, addresses and summaries above the table: find the real header row."""
    for i in range(min(len(raw), 60)):
        cells = " | ".join(str(x).lower() for x in raw.iloc[i].tolist())
        if all(m in cells for m in must):
            return i
    raise ValueError(f"Could not find a table header containing: {', '.join(must)}.")


def bank_balance(data: bytes, filename: str) -> dict:
    """Latest balance from a bank statement export (SBI, HDFC, ICICI, Axis, Kotak and similar layouts)."""
    raw = read_table(data, filename)
    h = _header_row(raw, ("balance",))
    cols = [str(c).strip().lower() for c in raw.iloc[h].tolist()]
    df = raw.iloc[h + 1:].copy()
    df.columns = cols
    bal_col = next(c for c in cols if "balance" in c)
    date_col = next((c for c in cols if "date" in c and "value" not in c), None) or next((c for c in cols if "date" in c), None)
    rows = []
    for _, r in df.iterrows():
        b = _f(str(r[bal_col]).replace("Cr", "").replace("CR", "").replace("Dr", "").strip())
        if b is None:
            continue
        d = pd.to_datetime(str(r[date_col]).strip(), dayfirst=True, errors="coerce") if date_col else pd.NaT
        rows.append((d, b))
    if not rows:
        raise ValueError("No balances found in the statement.")
    dated = [r for r in rows if not pd.isna(r[0])]
    # Statements run oldest-first or newest-first; take the balance on the latest date, last row of that date.
    if dated:
        latest = max(d for d, _ in dated)
        same = [b for d, b in dated if d == latest]
        first_d, last_d = dated[0][0], dated[-1][0]
        bal = same[-1] if first_d <= last_d else same[0]
        as_of = latest.date()
    else:
        bal, as_of = rows[-1][1], None
    text = " ".join(" ".join(str(x) for x in raw.iloc[i].tolist()) for i in range(min(h, 25)))
    acct = re.search(r"(?:a/?c|account)\s*(?:no\.?|number)?\s*[:\-]?\s*[xX*]*\s*(\d{3,})", text, re.I)
    bank = next((b for b in ("SBI", "State Bank", "HDFC", "ICICI", "Axis", "Kotak", "Yes Bank", "IDFC", "Bank of Baroda", "PNB", "Canara", "Union Bank", "IndusInd", "Federal") if b.lower() in text.lower()), None)
    return {"balance": round(bal, 2), "as_of": as_of, "account_hint": ("xx" + acct.group(1)[-4:]) if acct else None, "bank": bank}


def broker_holdings(data: bytes, filename: str) -> list[dict]:
    from backend.tools import portfolio as PF

    raw = read_table(data, filename)
    h = _header_row(raw, ("qty",)) if any("qty" in " ".join(map(str, raw.iloc[i].tolist())).lower() for i in range(min(len(raw), 60))) else _header_row(raw, ("quantity",))
    df = raw.iloc[h + 1:].copy()
    df.columns = [str(c).strip() for c in raw.iloc[h].tolist()]
    df = df[[c for c in df.columns if c]]
    hold = PF.parse_holdings(df.to_csv(index=False))
    return [{"symbol": re.sub(r"[^A-Z0-9&._-]", "", s.split("-")[0] if s.endswith(("-EQ", "-BE")) else s), "qty": float(q), "avg_price": float(a)}
            for s, q, a in zip(hold.symbol, hold.qty, hold.avg_price) if q > 0 and a > 0]


def depository_assets(cas: dict) -> dict:
    """From casparser's NSDL/CDSL output: stocks, funds, bonds and NPS across all demat accounts."""
    eq, mf, bonds = [], [], []
    for acc in cas.get("accounts") or []:
        dp = f"{acc.get('dp_id') or ''}{acc.get('client_id') or ''}"[-8:]
        for e in acc.get("equities") or []:
            n = _f(e.get("num_shares"))
            if n and n > 0:
                eq.append({"symbol": (e.get("symbol") or "").upper() or None, "isin": e.get("isin"), "name": e.get("name"),
                           "qty": n, "price": _f(e.get("price")), "value": _f(e.get("value")), "demat": dp})
        for m in acc.get("mutual_funds") or []:
            mf.append({"folio": str(m.get("folio") or dp)[:40], "scheme_name": str(m.get("name") or m.get("isin"))[:200], "isin": m.get("isin"),
                       "scheme_code": str(m.get("amfi") or "") or None, "units": _f(m.get("balance")) or 0.0, "invested": _f(m.get("total_cost")),
                       "last_nav": _f(m.get("nav")), "last_nav_date": None, "transactions": []})
        for b in acc.get("bonds") or []:
            bonds.append({"name": (b.get("name") or b.get("isin") or "Bond")[:100], "value": _f(b.get("value")), "isin": b.get("isin")})
    nps = cas.get("nps") or None
    return {"equities": eq, "funds": mf, "bonds": bonds,
            "nps": {"name": f"NPS {nps.get('pran') or ''}".strip(), "value": _f(nps.get("value"))} if nps and _f(nps.get("value")) else None}


def fd_value(principal: float, rate_pct: float | None, start: date | None, maturity: date | None, today: date) -> float:
    """Indian bank FDs compound quarterly. Value grows until maturity, then stays (it pays out or renews)."""
    if not rate_pct or not start:
        return principal
    end = min(today, maturity) if maturity else today
    years = max((end - start).days, 0) / 365.0
    return round(principal * (1 + rate_pct / 400) ** (4 * years), 2)
