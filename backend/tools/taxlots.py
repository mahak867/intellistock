"""Tax lots from your broker tradebook: what you have sold (and the tax), what you still hold lot by lot, and how much
long-term gain you can still book this financial year inside the Rs 1.25 lakh exemption (tax-gain harvesting).

ESTIMATE ONLY. Listed equity delivery trades. Rules and limits:
  * Lots are matched first-in first-out, as the depository does when you sell.
  * Same-day buy and sell of one stock is treated as intraday (business income, not capital gains) and left out.
  * Tax is estimated only for financial years that fall wholly under the rules from 23 Jul 2024 (FY 2025-26 on).
    Earlier years are listed with their gains but no tax figure.
  * Shares bought before 1 Feb 2018 need their 31 Jan 2018 price (fmv_31jan2018 column) for grandfathering;
    without it the gain shown is overstated and flagged.
A chartered accountant should confirm anything before you file or trade on it.
"""
from __future__ import annotations

import io
import math
import re
from collections import defaultdict
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

from backend.tools import costs as CO
from backend.tools import tax as TX

FIRST_NEW_RULES_FY = "2025-26"
MAX_ROWS = 50_000

ALIASES = {
    "date": ("tradedate", "date", "tradedt", "orderdate", "executiondate"),
    "symbol": ("symbol", "tradingsymbol", "scrip", "stock", "scripname", "ticker"),
    "side": ("tradetype", "side", "type", "buysell", "transactiontype", "action"),
    "qty": ("quantity", "qty", "shares", "units"),
    "price": ("price", "rate", "tradeprice", "avgprice", "averageprice"),
    "segment": ("segment",),
    "fmv": ("fmv31jan2018", "fmv", "fmvon31jan2018", "grandfatheredprice"),
}


def _norm(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h).lower())


def _date(v: str) -> date:
    s = str(v).strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return pd.to_datetime(s, format=fmt).date()
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Cannot read the date {v!r}. Use YYYY-MM-DD or DD-MM-YYYY.")


def parse_tradebook(text: str) -> tuple[list[dict], list[str]]:
    """Zerodha Console tradebook, or any CSV with date, symbol, buy/sell, quantity and price columns."""
    try:
        raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"Could not read the CSV: {type(e).__name__}") from None
    if raw.empty:
        raise ValueError("The tradebook has no rows.")
    if len(raw) > MAX_ROWS:
        raise ValueError(f"Too many rows ({len(raw)}); the limit is {MAX_ROWS}.")
    cols = {_norm(c): c for c in raw.columns}
    pick = {k: next((cols[a] for a in names if a in cols), None) for k, names in ALIASES.items()}
    missing = [k for k in ("date", "symbol", "side", "qty", "price") if pick[k] is None]
    if missing:
        raise ValueError(f"Tradebook needs columns for {', '.join(missing)}. Found: {list(raw.columns)[:14]}")
    notes, fills, skipped_seg = [], [], 0
    for i, r in raw.iterrows():
        if pick["segment"] and str(r[pick["segment"]]).strip().upper() not in ("EQ", "EQUITY", "CASH", ""):
            skipped_seg += 1
            continue
        side = str(r[pick["side"]]).strip().lower()
        side = {"b": "buy", "s": "sell", "purchase": "buy", "sale": "sell"}.get(side, side)
        if side not in ("buy", "sell"):
            raise ValueError(f"Row {i + 2}: buy/sell value {r[pick['side']]!r} not understood.")
        try:
            qty = float(str(r[pick["qty"]]).replace(",", ""))
            price = float(str(r[pick["price"]]).replace(",", ""))
        except ValueError:
            raise ValueError(f"Row {i + 2}: quantity or price is not a number.") from None
        if not (math.isfinite(qty) and math.isfinite(price)) or qty <= 0 or price <= 0:
            raise ValueError(f"Row {i + 2}: quantity and price must be positive numbers.")
        fmv = None
        if pick["fmv"] and str(r[pick["fmv"]]).strip():
            try:
                fmv = float(str(r[pick["fmv"]]).replace(",", ""))
            except ValueError:
                fmv = None
        sym = str(r[pick["symbol"]]).strip().upper()
        if not sym:
            raise ValueError(f"Row {i + 2}: symbol is empty.")
        fills.append({"symbol": sym, "date": _date(r[pick["date"]]), "side": side, "qty": qty, "price": price, "fmv": fmv})
    if skipped_seg:
        notes.append(f"{skipped_seg} rows from other segments (F&O, currency, commodity) were left out.")
    if not fills:
        raise ValueError("No equity delivery trades in the file.")
    return fills, notes


def _net_intraday(fills: list[dict]) -> tuple[list[dict], float]:
    """Same stock bought and sold on one day: the matched quantity is intraday, not capital gains."""
    by = defaultdict(list)
    for f in fills:
        by[(f["symbol"], f["date"])].append(f)
    out, intraday = [], 0.0
    for (_, _), rows in by.items():
        b = sum(r["qty"] for r in rows if r["side"] == "buy")
        s = sum(r["qty"] for r in rows if r["side"] == "sell")
        m = min(b, s)
        if m <= 0:
            out += rows
            continue
        intraday += m
        for side in ("buy", "sell"):
            left = m
            for r in sorted((r for r in rows if r["side"] == side), key=lambda r: r["price"]):
                take = min(left, r["qty"])
                left -= take
                if r["qty"] - take > 1e-9:
                    out.append({**r, "qty": r["qty"] - take})
    return out, intraday


def build(fills: list[dict], as_of: date) -> dict:
    fills, intraday = _net_intraday(fills)
    lots: dict[str, list[dict]] = defaultdict(list)
    realised, warnings = [], []
    unmatched: dict[str, float] = defaultdict(float)
    for f in sorted(fills, key=lambda x: (x["date"], x["side"] != "buy")):
        book = lots[f["symbol"]]
        if f["side"] == "buy":
            book.append({"qty": f["qty"], "price": f["price"], "date": f["date"], "fmv": f["fmv"]})
            continue
        need = f["qty"]
        while need > 1e-9 and book:
            lot = book[0]
            q = min(need, lot["qty"])
            cost, flag = lot["price"], None
            if lot["date"] < date(2018, 2, 1):
                if lot["fmv"] is None:
                    flag = "bought before 1 Feb 2018 without a 31 Jan 2018 price: grandfathering not applied, gain overstated"
                else:
                    cost = max(lot["price"], min(lot["fmv"], f["price"]))
            long_term = f["date"] > lot["date"] + relativedelta(months=12)
            realised.append({"symbol": f["symbol"], "buy_date": lot["date"], "sell_date": f["date"], "qty": q, "cost": cost,
                             "proceeds": f["price"], "gain": (f["price"] - cost) * q, "term": "long" if long_term else "short",
                             "fy": TX.fy_of(f["date"]), "flag": flag})
            lot["qty"] -= q
            need -= q
            if lot["qty"] < 1e-9:
                book.pop(0)
        if need > 1e-9:
            unmatched[f["symbol"]] += need
    if intraday:
        warnings.append(f"{intraday:g} shares bought and sold on the same day were treated as intraday (business income) and left out.")
    for s, q in unmatched.items():
        warnings.append(f"{s}: sold {q:g} more shares than the file shows buying (bought before the file starts, or moved in from another broker). Those sales are not in the gains.")
    if any(r["flag"] for r in realised):
        warnings.append("Some sold shares were bought before 1 Feb 2018 without a 31 Jan 2018 price. Add an fmv_31jan2018 column for exact grandfathering.")
    open_lots = []
    for s, book in lots.items():
        for lot in book:
            lt_from = lot["date"] + relativedelta(months=12) + relativedelta(days=1)
            open_lots.append({"symbol": s, "buy_date": lot["date"], "qty": lot["qty"], "cost": lot["price"], "fmv": lot["fmv"],
                              "long_term": as_of >= lt_from, "long_term_from": lt_from})
    return {"realised": realised, "open_lots": open_lots, "warnings": warnings}


def fy_summary(realised: list[dict]) -> dict:
    out = {}
    for fy in sorted({r["fy"] for r in realised}):
        rows = [r for r in realised if r["fy"] == fy]
        if fy >= FIRST_NEW_RULES_FY:
            out[fy] = TX.tax_summary(rows)[fy]
        else:
            out[fy] = {"stcg": sum(r["gain"] for r in rows if r["term"] == "short"), "ltcg": sum(r["gain"] for r in rows if r["term"] == "long"),
                       "estimated_tax_with_cess": None, "note": "Older or mixed tax rules; no tax estimate."}
    return out


def harvest(open_lots: list[dict], prices: dict[str, float], realised: list[dict], as_of: date) -> dict:
    fy = TX.fy_of(as_of)
    this_fy = [r for r in realised if r["fy"] == fy]
    used = TX.tax_summary(this_fy)[fy]["ltcg_exemption_used"] if this_fy else 0.0
    headroom = max(TX.LTCG_EXEMPT - used, 0.0)
    left = headroom
    by_sym: dict[str, list[dict]] = defaultdict(list)
    for lot in sorted(open_lots, key=lambda x: x["buy_date"]):
        by_sym[lot["symbol"]].append(lot)
    gains_plan, losses = [], []
    # Sell in FIFO order only: the oldest shares leave your demat first, whatever you intend.
    candidates = []
    for s, book in by_sym.items():
        p = prices.get(s)
        if not p:
            continue
        lt_gain_qty, lt_gain = 0.0, 0.0
        for lot in book:
            if not lot["long_term"]:
                break
            g = p - (max(lot["cost"], min(lot["fmv"], p)) if lot["buy_date"] < date(2018, 2, 1) and lot["fmv"] else lot["cost"])
            if g <= 0:
                break
            lt_gain_qty += lot["qty"]
            lt_gain += g * lot["qty"]
        if lt_gain > 0:
            candidates.append((s, p, book))
        first = book[0]
        if p < first["cost"]:
            losses.append({"symbol": s, "qty": first["qty"], "loss": round((p - first["cost"]) * first["qty"], 2),
                           "term": "long" if first["long_term"] else "short", "price": p})
    for s, p, book in sorted(candidates, key=lambda c: -sum(l["qty"] for l in c[2])):
        if left <= 1:
            break
        qty, gain = 0, 0.0
        for lot in book:
            if not lot["long_term"]:
                break
            cost = max(lot["cost"], min(lot["fmv"], p)) if lot["buy_date"] < date(2018, 2, 1) and lot["fmv"] else lot["cost"]
            g = p - cost
            if g <= 0:
                break
            take = min(int(lot["qty"]), int((left - gain) // g))
            qty += take
            gain += take * g
            if take < lot["qty"]:
                break
        if qty <= 0:
            continue
        sell = CO.trade_cost("equity_delivery", "sell", p, qty).total
        buy = CO.trade_cost("equity_delivery", "buy", p, qty).total
        tax_saved = gain * TX.LTCG_RATE * (1 + TX.CESS)
        gains_plan.append({"symbol": s, "sell_qty": qty, "price": p, "long_term_gain_booked": round(gain, 2),
                           "future_tax_avoided": round(tax_saved, 2), "charges_to_sell_and_rebuy": round(sell + buy, 2),
                           "worth_it": tax_saved > (sell + buy)})
        left -= gain
    return {"financial_year": fy, "ltcg_exemption": TX.LTCG_EXEMPT, "exemption_used_so_far": round(used, 2),
            "headroom_left": round(headroom, 2), "suggested_sales": gains_plan,
            "headroom_after_suggestions": round(max(left, 0.0), 2), "loss_lots_first_in_line": losses,
            "notes": ["Selling and buying back resets your cost to today's price, so a later sale owes less tax. "
                      "India has no wash-sale rule today, but ask a chartered accountant about your case.",
                      "Charges are an estimate for one sell and one buy-back on delivery (STT, exchange, stamp, GST)."]}


def report(text: str, prices: dict[str, float], as_of: date) -> dict:
    fills, notes = parse_tradebook(text)
    b = build(fills, as_of)
    return {
        "as_of": str(as_of),
        "realised_by_year": fy_summary(b["realised"]),
        "realised": [{**r, "buy_date": str(r["buy_date"]), "sell_date": str(r["sell_date"]), "gain": round(r["gain"], 2)} for r in b["realised"]],
        "open_lots": [{**l, "buy_date": str(l["buy_date"]), "long_term_from": str(l["long_term_from"]),
                       "price": prices.get(l["symbol"]), "unrealised": round((prices[l["symbol"]] - l["cost"]) * l["qty"], 2) if prices.get(l["symbol"]) else None}
                      for l in b["open_lots"]],
        "harvest": harvest(b["open_lots"], prices, b["realised"], as_of),
        "warnings": notes + b["warnings"],
        "disclaimer": "Estimate for listed-equity delivery trades only. A chartered accountant must confirm before you file or trade on it.",
    }
