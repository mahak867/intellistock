"""Corporate actions on your holdings: dividends, bonus issues and splits.

You confirm each action (typed in, or picked from NSE's list). Holdings bought BEFORE the ex-date are entitled:
  * split from face value F1 to F2: shares x (F1 / F2), average price / (F1 / F2), cost unchanged
  * bonus a:b (a new for every b held): shares x (a + b) / b, average price adjusted the same way
  * dividend D per share: cash = D x shares held on the ex-date (after earlier splits and bonuses)
"""
from __future__ import annotations

import re
from datetime import date, datetime

import httpx

KINDS = ("dividend", "split", "bonus")

_DIV = re.compile(r"dividend[^-]*-\s*(?:rs\.?|re\.?|inr|₹)?\s*([\d]+(?:\.\d+)?)\s*(?:/-)?\s*(?:per\s*(?:sh|share))", re.I)
_BONUS = re.compile(r"bonus\s*(?:issue)?\s*(\d+)\s*:\s*(\d+)", re.I)
_SPLIT = re.compile(r"(?:split|sub-?division)[^\d]*?(?:from\s*)?(?:rs\.?|re\.?|₹)?\s*([\d]+(?:\.\d+)?)\s*(?:/-)?[^\d]*?to\s*(?:rs\.?|re\.?|₹)?\s*([\d]+(?:\.\d+)?)", re.I)


def share_factor(kind: str, ratio_new: float | None, ratio_old: float | None) -> float:
    if kind == "split":
        return float(ratio_new) / float(ratio_old)  # ratio_new = old face value, ratio_old = new face value (10 -> 2 gives 5)
    if kind == "bonus":
        return (float(ratio_new) + float(ratio_old)) / float(ratio_old)  # a:b -> (a+b)/b
    return 1.0


def adjust(qty: float, avg: float, buy_date: date, actions: list[dict]) -> dict:
    """actions: dicts with kind, ex_date (date), amount, ratio_new, ratio_old. Only those after buy_date apply."""
    q, a, divs, applied = float(qty), float(avg), [], []
    for act in sorted(actions, key=lambda x: x["ex_date"]):
        if act["ex_date"] <= buy_date:
            continue
        if act["kind"] == "dividend":
            cash = float(act["amount"] or 0) * q
            if cash > 0:
                divs.append({"ex_date": act["ex_date"], "per_share": float(act["amount"]), "shares": q, "cash": round(cash, 2)})
        else:
            f = share_factor(act["kind"], act["ratio_new"], act["ratio_old"])
            if f > 0 and f != 1:
                q, a = q * f, a / f
                applied.append({"kind": act["kind"], "ex_date": act["ex_date"], "factor": f})
    return {"quantity": q, "avg_price": a, "dividends": divs, "applied": applied,
            "dividends_total": round(sum(d["cash"] for d in divs), 2)}


def parse_subject(subject: str) -> list[dict]:
    """One NSE corporate-action description -> zero or more actions (a line can hold a dividend and a special dividend)."""
    s = " ".join(str(subject).split())
    out = []
    divs = [float(x) for x in _DIV.findall(s)]
    if divs:
        out.append({"kind": "dividend", "amount": round(sum(divs), 4)})
    m = _BONUS.search(s)
    if m and int(m.group(2)) > 0:
        out.append({"kind": "bonus", "ratio_new": float(m.group(1)), "ratio_old": float(m.group(2))})
    m = _SPLIT.search(s)
    if m and float(m.group(2)) > 0 and float(m.group(1)) > float(m.group(2)):
        out.append({"kind": "split", "ratio_new": float(m.group(1)), "ratio_old": float(m.group(2))})
    return out


def _date(v: str) -> date | None:
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def from_nse_rows(rows: list[dict]) -> list[dict]:
    """Rows from NSE's corporate-actions API (fields include symbol, subject, exDate)."""
    out = []
    for r in rows:
        d = _date(r.get("exDate") or r.get("ex_date") or "")
        if not d:
            continue
        for a in parse_subject(r.get("subject", "")):
            out.append({"ticker": str(r.get("symbol", "")).upper(), "ex_date": d, "source_text": r.get("subject", ""), **a})
    return out


NSE_HOME = "https://www.nseindia.com"
NSE_API = "https://www.nseindia.com/api/corporates-corporateActions"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch_nse(symbol: str, client: httpx.Client | None = None) -> list[dict]:
    """NSE's website API (unofficial: it needs the cookies its home page sets, and it changes without notice)."""
    own = client is None
    c = client or httpx.Client(timeout=20, headers={"User-Agent": UA, "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"}, follow_redirects=True)
    try:
        c.get(NSE_HOME)
        r = c.get(NSE_API, params={"index": "equities", "symbol": symbol.upper()}, headers={"Referer": f"{NSE_HOME}/companies-listing/corporate-filings-actions"})
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        return from_nse_rows(rows)
    finally:
        if own:
            c.close()
