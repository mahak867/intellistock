"""Capital gains on listed equity (delivery, Section 111A / 112A). ESTIMATE ONLY: have a chartered
accountant confirm before filing.

Rules encoded (verified 2026-11-01 against Budget 2024 summaries): for sales on or after 23 Jul 2024,
short-term (held 12 months or less) 20%; long-term (more than 12 months) 12.5% on gains above
Rs 1.25 lakh per financial year; grandfathering to the 31 Jan 2018 value for shares bought before
1 Feb 2018. Short-term losses set off against short- and long-term gains; long-term losses only
against long-term gains. 4% health and education cess added; surcharge, intraday and F&O
(business income) are NOT handled."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

RULE_START = date(2024, 7, 23)
STCG_RATE, LTCG_RATE, LTCG_EXEMPT, CESS = 0.20, 0.125, 125_000.0, 0.04


@dataclass
class Fill:
    symbol: str
    date: date
    side: str           # buy | sell
    qty: float
    price: float
    fmv_31jan2018: float | None = None  # supply for buys before 1 Feb 2018


def fy_of(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def realised_gains(fills: list[Fill]) -> list[dict]:
    lots: dict[str, list[list]] = {}
    out = []
    for f in sorted(fills, key=lambda x: (x.date, x.side != "buy")):
        book = lots.setdefault(f.symbol, [])
        if f.side == "buy":
            book.append([f.qty, f.price, f.date, f.fmv_31jan2018])
            continue
        if f.date < RULE_START:
            raise ValueError(f"Sale on {f.date} is before 23 Jul 2024: older rates apply and are not supported here.")
        need = f.qty
        while need > 1e-9:
            if not book:
                raise ValueError(f"Sold more {f.symbol} than bought: check for missing buy rows.")
            lot = book[0]
            q = min(need, lot[0])
            cost = lot[1]
            if lot[2] < date(2018, 2, 1):
                if lot[3] is None:
                    raise ValueError(f"{f.symbol} bought {lot[2]} (before 1 Feb 2018) needs fmv_31jan2018.")
                cost = max(lot[1], min(lot[3], f.price))  # grandfathering
            long_term = f.date > lot[2] + relativedelta(months=12)
            out.append({"symbol": f.symbol, "sell_date": f.date, "buy_date": lot[2], "qty": q, "cost": cost, "proceeds": f.price,
                        "gain": (f.price - cost) * q, "term": "long" if long_term else "short", "fy": fy_of(f.date)})
            lot[0] -= q
            need -= q
            if lot[0] < 1e-9:
                book.pop(0)
    return out


def tax_summary(gains: list[dict]) -> dict:
    res = {}
    for fy in sorted({g["fy"] for g in gains}):
        g = [x for x in gains if x["fy"] == fy]
        st = sum(x["gain"] for x in g if x["term"] == "short")
        lt = sum(x["gain"] for x in g if x["term"] == "long")
        stcg, stcl = max(st, 0.0), max(-st, 0.0)
        ltcg, ltcl = max(lt, 0.0), max(-lt, 0.0)
        # short-term loss first against short-term gain, remainder against long-term gain
        st_net = max(stcg - stcl, 0.0)
        stcl_left = max(stcl - stcg, 0.0)
        lt_net = max(ltcg - stcl_left - ltcl, 0.0)  # long-term loss only against long-term gain
        taxable_lt = max(lt_net - LTCG_EXEMPT, 0.0)
        tax = (st_net * STCG_RATE + taxable_lt * LTCG_RATE) * (1 + CESS)
        lt_after_st = max(ltcg - stcl_left, 0.0)
        carry = {"short_term_loss": max(stcl_left - ltcg, 0.0), "long_term_loss": max(ltcl - lt_after_st, 0.0)}
        res[fy] = {"stcg": st, "ltcg": lt, "taxable_stcg": st_net, "taxable_ltcg": taxable_lt,
                   "ltcg_exemption_used": min(lt_net, LTCG_EXEMPT), "estimated_tax_with_cess": round(tax, 2),
                   "loss_to_carry_forward": carry}
    return res


def ltcg_headroom(realised_ltcg_this_fy: float) -> float:
    """Long-term gain you can still book this year with no tax (before cess)."""
    return max(LTCG_EXEMPT - max(realised_ltcg_this_fy, 0.0), 0.0)
