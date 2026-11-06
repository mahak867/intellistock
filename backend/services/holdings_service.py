"""Holdings with corporate actions applied, current prices, and performance (XIRR vs NIFTY 50)."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from backend.data import providers
from backend.models.db_models import BrokerConnection, CorporateAction, PortfolioEntry
from backend.tools import corpactions as CA
from backend.tools import portfolio as PF

MIN_DAYS_TO_ANNUALISE = 365


def _d(x) -> date:
    return x.date() if isinstance(x, datetime) else x


async def adjusted(session, user_id: str) -> list[dict]:
    entries = (await session.execute(select(PortfolioEntry).where(PortfolioEntry.user_id == user_id))).scalars().all()
    acts = (await session.execute(select(CorporateAction).where(CorporateAction.user_id == user_id))).scalars().all()
    by_t: dict[str, list[dict]] = {}
    for a in acts:
        by_t.setdefault(a.ticker, []).append({"kind": a.kind, "ex_date": a.ex_date, "amount": a.amount, "ratio_new": a.ratio_new, "ratio_old": a.ratio_old})
    out = []
    for e in entries:
        adj = CA.adjust(e.quantity, e.avg_buy_price, _d(e.buy_date), by_t.get(e.ticker, []))
        out.append({"id": str(e.id), "ticker": e.ticker, "exchange": e.exchange, "account": e.account or "Me", "quantity": adj["quantity"], "avg_buy_price": adj["avg_price"],
                    "raw_quantity": e.quantity, "raw_avg_buy_price": e.avg_buy_price, "invested_value": e.quantity * e.avg_buy_price,
                    "buy_date": e.buy_date.isoformat(), "notes": e.notes, "adjustments": [{**x, "ex_date": str(x["ex_date"])} for x in adj["applied"]],
                    "dividends": [{**x, "ex_date": str(x["ex_date"])} for x in adj["dividends"]], "dividends_received": adj["dividends_total"]})
    return out


async def prices_for(session, user_id: str, tickers: list[str]) -> tuple[dict[str, float], str, bool]:
    """(prices, source, real). Live from the user's Zerodha session when possible, else the server's latest close."""
    from backend.services import broker_service as B

    conn = (await session.execute(select(BrokerConnection).where(BrokerConnection.user_id == user_id))).scalar_one_or_none()
    if conn and B.session_valid(conn) and tickers:
        try:
            got = await B.run(B.client(conn).ltp, tickers)
            if got:
                return got, "zerodha-live", True
        except Exception:
            pass
    px, real, source = {}, True, "none"
    for t in tickers:
        try:
            p = await asyncio.to_thread(providers.get_prices, t, 260)
            px[t] = float(p.df["close"].iloc[-1])
            source, real = p.source, real and not p.synthetic
        except Exception:
            continue
    return px, source, real and bool(px)


def performance(holdings: list[dict], prices: dict[str, float], today: date) -> dict:
    index = providers.index_series("NIFTY 50")
    rows, all_flows, total_value, total_cost, total_div = [], [], 0.0, 0.0, 0.0
    for h in holdings:
        p = prices.get(h["ticker"])
        bd = date.fromisoformat(h["buy_date"][:10])
        cost = h["raw_quantity"] * h["raw_avg_buy_price"]
        flows = [(bd, -cost)] + [(date.fromisoformat(d["ex_date"]), d["cash"]) for d in h["dividends"]]
        row = {"ticker": h["ticker"], "account": h.get("account", "Me"), "buy_date": str(bd), "invested": round(cost, 2), "dividends": h["dividends_received"],
               "price": p, "value": None, "gain": None, "return_pct": None, "xirr": None, "nifty_xirr": None, "note": None}
        if p:
            value = h["quantity"] * p
            row.update(value=round(value, 2), gain=round(value + h["dividends_received"] - cost, 2),
                       return_pct=round((value + h["dividends_received"] - cost) / cost * 100, 2))
            if (today - bd).days >= MIN_DAYS_TO_ANNUALISE:
                x = PF.xirr(flows + [(today, value)])
                row["xirr"] = None if x is None else round(x * 100, 2)
                if index is not None:
                    try:
                        bx = PF.benchmark_xirr(flows, index, value, today)
                        row["nifty_xirr"] = None if bx is None else round(bx * 100, 2)
                    except ValueError:
                        pass
            else:
                row["note"] = "Held under a year: shown as plain return, not annualised."
            all_flows += flows
            total_value += value
            total_cost += cost
            total_div += h["dividends_received"]
        else:
            row["note"] = "No price for this stock."
        rows.append(row)
    summary = {"invested": round(total_cost, 2), "value": round(total_value, 2), "dividends": round(total_div, 2),
               "gain": round(total_value + total_div - total_cost, 2), "xirr": None, "nifty_xirr": None,
               "benchmark_note": None if index is not None else "NIFTY 50 comparison needs real NSE index data on this server."}
    if all_flows and (today - min(d for d, _ in all_flows)).days >= MIN_DAYS_TO_ANNUALISE:
        x = PF.xirr(all_flows + [(today, total_value)])
        summary["xirr"] = None if x is None else round(x * 100, 2)
        if index is not None:
            try:
                bx = PF.benchmark_xirr(all_flows, index, total_value, today)
                summary["nifty_xirr"] = None if bx is None else round(bx * 100, 2)
            except ValueError:
                summary["benchmark_note"] = "NIFTY 50 data does not reach back to your earliest purchase."
    return {"as_of": str(today), "holdings": rows, "total": summary}


IST = timezone(timedelta(hours=5, minutes=30))


def today_ist() -> date:
    return datetime.now(timezone.utc).astimezone(IST).date()
