"""Turn a parsed CAS statement (casparser) into mutual fund holdings with dated cash flows.

Detailed CAMS/KFintech statements carry every transaction, so XIRR is exact. Summary statements and NSDL/CDSL
statements only carry the current balance and total cost, so there is one cash flow and XIRR is not computed.
"""
from __future__ import annotations

import io
import json
from datetime import date

BUY = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER", "DIVIDEND_REINVEST", "GIFT_IN"}
SELL = {"REDEMPTION", "SWITCH_OUT", "SWITCH_OUT_MERGER", "GIFT_OUT"}
CASH_IN = {"DIVIDEND_PAYOUT"}


def _f(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _d(x) -> date | None:
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def holdings_from(cas: dict) -> tuple[list[dict], list[str]]:
    out, notes = [], list(cas.get("parse_warnings") or [])
    for folio in cas.get("folios") or []:
        for s in folio.get("schemes") or []:
            units = _f(s.get("close")) or 0.0
            val = s.get("valuation") or {}
            txns = []
            for t in s.get("transactions") or []:
                kind, amt, u, d = str(t.get("type") or ""), _f(t.get("amount")), _f(t.get("units")), _d(t.get("date"))
                if d is None or amt is None:
                    continue
                if kind in BUY and kind != "DIVIDEND_REINVEST":
                    txns.append({"date": d, "kind": kind, "amount": -abs(amt), "units": abs(u or 0)})
                elif kind == "DIVIDEND_REINVEST":
                    txns.append({"date": d, "kind": kind, "amount": 0.0, "units": abs(u or 0)})  # no new money
                elif kind in SELL:
                    txns.append({"date": d, "kind": kind, "amount": abs(amt), "units": -abs(u or 0)})
                elif kind in CASH_IN:
                    txns.append({"date": d, "kind": kind, "amount": abs(amt), "units": 0.0})
            if units <= 1e-6 and not txns:
                continue
            out.append({"folio": str(folio.get("folio") or "")[:40], "amc": folio.get("amc"), "scheme_name": str(s.get("scheme") or "")[:200],
                        "isin": s.get("isin"), "scheme_code": str(s.get("amfi") or "") or None, "units": units,
                        "invested": _f(val.get("cost")), "last_nav": _f(val.get("nav")), "last_nav_date": _d(val.get("date")), "transactions": txns})
    for m in cas.get("mutual_funds") or []:  # NSDL / CDSL statements
        out.append({"folio": "", "amc": None, "scheme_name": str(m.get("name") or m.get("isin"))[:200], "isin": m.get("isin"),
                    "scheme_code": str(m.get("amfi") or "") or None, "units": _f(m.get("balance")) or 0.0, "invested": _f(m.get("total_cost")),
                    "last_nav": _f(m.get("nav")), "last_nav_date": None, "transactions": []})
    if cas.get("mutual_funds") is not None:
        notes.append("Depository (NSDL/CDSL) statements list holdings without transactions, so XIRR is not available for them.")
    return out, notes


def read_pdf(data: bytes, password: str) -> dict:
    import casparser

    try:
        return json.loads(casparser.read_cas_pdf(io.BytesIO(data), password, output="json"))
    except Exception as e:
        name = type(e).__name__
        if "password" in str(e).lower() or "Incorrect" in name:
            raise ValueError("Wrong password. CAS statements are usually locked with the password you chose when requesting them.") from None
        raise ValueError(f"Could not read this file as a CAS statement ({name}). Use the PDF emailed by CAMS, KFintech, NSDL or CDSL.") from None
