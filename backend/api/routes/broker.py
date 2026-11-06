"""
Broker link (Zerodha Kite Connect). Each user connects their own Kite Connect app.

• GET    /broker/status              — connected? session valid? login link
• PUT    /broker/kite/keys           — save your Kite Connect API key and secret (encrypted)
• POST   /broker/kite/session        — finish the Zerodha login with the request_token from the redirect
• DELETE /broker                     — log out of Zerodha here and forget the keys
• GET    /broker/holdings            — your holdings, live from Zerodha
• POST   /broker/holdings/import     — copy them into your IntelliStock portfolio
• GET    /broker/quotes?tickers=     — last traded prices (needs the Kite market-data add-on)
• POST   /broker/orders/preview      — check a limit order and get a 2-minute confirmation
• POST   /broker/orders              — send that exact order (one confirmation, one order)
• GET    /broker/orders              — orders IntelliStock has sent for you
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.api.routes.auth import get_current_user
from backend.core.config import settings
from backend.core.database import get_session
from backend.models.db_models import OrderLog, PortfolioEntry
from backend.services import broker_service as B
from backend.tools import costs as CO

router = APIRouter()


def _fail(e: B.BrokerProblem):
    raise HTTPException(status_code=e.status, detail=str(e))


class KeysIn(BaseModel):
    api_key: str = Field(pattern=r"^[A-Za-z0-9]{6,32}$")
    api_secret: str = Field(pattern=r"^[A-Za-z0-9]{6,64}$")


class SessionIn(BaseModel):
    request_token: str = Field(pattern=r"^[A-Za-z0-9]{6,64}$")


class ImportIn(BaseModel):
    mode: Literal["merge", "replace"] = "merge"


class OrderIn(BaseModel):
    tradingsymbol: str = Field(min_length=1, max_length=30)
    exchange: Literal["NSE", "BSE"] = "NSE"
    side: Literal["BUY", "SELL"]
    quantity: int = Field(ge=1, le=100_000)
    price: float = Field(gt=0, lt=10_000_000, allow_inf_nan=False)
    product: Literal["CNC", "MIS"] = "CNC"

    @field_validator("tradingsymbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        v = v.strip().upper()
        if not B.K.SYMBOL.match(v):
            raise ValueError("letters, digits and & _ . - only")
        return v

    @field_validator("price")
    @classmethod
    def _tick(cls, v: float) -> float:
        return round(v, 2)


class PlaceIn(OrderIn):
    confirm_token: str = Field(min_length=10, max_length=200)


@router.get("/status")
async def broker_status(user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as s:
        return B.status(await B.get_conn(s, user["sub"]))


@router.put("/kite/keys")
async def save_keys(b: KeysIn, user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as s:
        c = await B.save_keys(s, user["sub"], b.api_key, b.api_secret)
        return {"message": "Keys saved. Now log in with Zerodha.", **B.status(c)}


@router.post("/kite/session")
async def finish_login(b: SessionIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        async with get_session() as s:
            c = await B.finish_login(s, user["sub"], b.request_token)
            return {"message": f"Connected to Zerodha as {c.broker_user_id or 'your account'}.", **B.status(c)}
    except B.BrokerProblem as e:
        _fail(e)


@router.delete("", status_code=204, response_model=None)
async def disconnect(user: dict = Depends(get_current_user)) -> None:
    async with get_session() as s:
        if not await B.disconnect(s, user["sub"]):
            raise HTTPException(status_code=404, detail="No broker connected.")


@router.get("/holdings")
async def holdings(user: dict = Depends(get_current_user)) -> dict:
    try:
        async with get_session() as s:
            k = B.client(await B.get_conn(s, user["sub"]))
        rows = await B.run(k.holdings)
    except B.BrokerProblem as e:
        _fail(e)
    return {"source": "kite", "as_of": datetime.now(timezone.utc).isoformat(), "holdings": rows}


@router.post("/holdings/import")
async def import_holdings(b: ImportIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        async with get_session() as s:
            k = B.client(await B.get_conn(s, user["sub"]))
        rows = await B.run(k.holdings)
    except B.BrokerProblem as e:
        _fail(e)
    today = datetime.now(timezone.utc)
    note = f"Imported from Zerodha on {today:%d %b %Y}. Zerodha does not give the buy date, so returns since purchase are not exact."
    added = updated = removed = 0
    async with get_session() as s:
        existing = (await s.execute(select(PortfolioEntry).where(PortfolioEntry.user_id == user["sub"]))).scalars().all()
        if b.mode == "replace":
            removed = len(existing)
            await s.execute(delete(PortfolioEntry).where(PortfolioEntry.user_id == user["sub"]))
            existing = []
        by_ticker: dict[str, list[PortfolioEntry]] = {}
        for e in existing:
            by_ticker.setdefault(e.ticker, []).append(e)
        for h in rows:
            if not h["ticker"] or h["avg_buy_price"] <= 0:
                continue
            same = by_ticker.get(h["ticker"], [])
            if same:
                keep, *extra = same
                keep.quantity, keep.avg_buy_price, keep.exchange = h["quantity"], h["avg_buy_price"], h["exchange"]
                for x in extra:
                    await s.delete(x)
                updated += 1
            else:
                s.add(PortfolioEntry(user_id=user["sub"], ticker=h["ticker"][:20], exchange=h["exchange"][:10], quantity=h["quantity"],
                                     avg_buy_price=h["avg_buy_price"], buy_date=today, notes=note))
                added += 1
    return {"added": added, "updated": updated, "removed": removed, "mode": b.mode,
            "note": "Holdings you have in IntelliStock but not at Zerodha were left alone." if b.mode == "merge" else None}


@router.get("/quotes")
async def quotes(tickers: str = Query(min_length=1, max_length=1500), exchange: Literal["NSE", "BSE"] = "NSE",
                 user: dict = Depends(get_current_user)) -> dict:
    names = list(dict.fromkeys(t.strip().upper() for t in tickers.split(",") if t.strip()))[:100]
    try:
        async with get_session() as s:
            k = B.client(await B.get_conn(s, user["sub"]))
        prices = await B.run(k.ltp, names, exchange)
    except B.BrokerProblem as e:
        _fail(e)
    return {"source": "kite", "live": True, "as_of": datetime.now(timezone.utc).isoformat(), "prices": prices,
            "missing": [n for n in names if n not in prices]}


def _segment(product: str) -> str:
    return "equity_delivery" if product == "CNC" else "equity_intraday"


@router.post("/orders/preview")
async def preview(o: OrderIn, user: dict = Depends(get_current_user)) -> dict:
    if not settings.BROKER_ORDERS_ENABLED:
        raise HTTPException(status_code=403, detail="Order placement is turned off on this server.")
    try:
        async with get_session() as s:
            k = B.client(await B.get_conn(s, user["sub"]))
        try:
            ltp = (await B.run(k.ltp, [o.tradingsymbol], o.exchange)).get(o.tradingsymbol)
        except B.BrokerProblem as e:
            if e.status == 401:
                raise
            ltp = None  # no market-data add-on: preview without a live price
    except B.BrokerProblem as e:
        _fail(e)
    notional = o.price * o.quantity
    if notional > B.MAX_ORDER_VALUE:
        raise HTTPException(status_code=422, detail=f"Order value ₹{notional:,.0f} is above the ₹{B.MAX_ORDER_VALUE:,.0f} per-order limit in IntelliStock. Use the Kite app for large orders.")
    warnings, gap = [], None
    if ltp:
        gap = (o.price - ltp) / ltp
        if abs(gap) > B.MAX_PRICE_GAP:
            raise HTTPException(status_code=422, detail=f"Your price ₹{o.price:,.2f} is {gap * 100:+.0f}% from the last price ₹{ltp:,.2f}. That looks like a typo, so it was not accepted.")
        if (o.side == "BUY" and o.price > ltp * 1.02) or (o.side == "SELL" and o.price < ltp * 0.98):
            warnings.append(f"This limit is {abs(gap) * 100:.1f}% {'above' if o.side == 'BUY' else 'below'} the last price, so it will probably fill at once near the last price.")
    else:
        warnings.append("No live price available (your Kite plan may not include market data), so the price could not be sanity-checked.")
    cost = CO.trade_cost(_segment(o.product), o.side.lower(), o.price, o.quantity)
    if o.product == "MIS":
        warnings.append("Intraday (MIS): Zerodha squares it off automatically before the close if you do not.")
    warnings.append("Orders from a server must come from the static IP on your Kite developer profile, or Zerodha rejects them.")
    return {"order": o.model_dump(), "order_type": "LIMIT", "validity": "DAY", "value": round(notional, 2), "last_price": ltp,
            "gap_from_last_pct": None if gap is None else round(gap * 100, 2), "charges_estimate": round(cost.total, 2),
            "warnings": warnings, "confirm_token": B.confirm_token(user["sub"], o.model_dump()), "expires_in_seconds": B.CONFIRM_SECONDS}


@router.post("/orders")
async def place(p: PlaceIn, user: dict = Depends(get_current_user)):
    if not settings.BROKER_ORDERS_ENABLED:
        raise HTTPException(status_code=403, detail="Order placement is turned off on this server.")
    o = p.model_dump(exclude={"confirm_token"})
    try:
        sig = B.check_confirm(user["sub"], o, p.confirm_token)
        async with get_session() as s:
            k = B.client(await B.get_conn(s, user["sub"]))
    except B.BrokerProblem as e:
        _fail(e)
    # Claim the confirmation first: the unique signature makes a double click or a replay fail here, before Zerodha.
    try:
        async with get_session() as s:
            log = OrderLog(user_id=user["sub"], broker="kite", tradingsymbol=o["tradingsymbol"], exchange=o["exchange"], side=o["side"],
                           quantity=o["quantity"], price=o["price"], product=o["product"], status="sending", confirm_sig=sig)
            s.add(log)
            await s.flush()
            log_id = log.id
    except IntegrityError:
        raise HTTPException(status_code=409, detail="This order was already sent. Check your orders before sending another.") from None
    status_code, body = 200, {}
    try:
        oid = await B.run(k.place_limit_order, tradingsymbol=o["tradingsymbol"], exchange=o["exchange"], side=o["side"],
                          quantity=o["quantity"], price=o["price"], product=o["product"])
        new_status, msg = "sent", "Sent to Zerodha. Check the order status in Kite."
        body = {"message": msg, "broker_order_id": oid}
    except B.BrokerProblem as e:
        oid, new_status, msg = None, "rejected" if e.status in (400, 422) else "error", str(e)[:300]
        status_code, body = e.status, {"detail": msg}
    async with get_session() as s:
        log = (await s.execute(select(OrderLog).where(OrderLog.id == log_id))).scalar_one()
        log.status, log.broker_order_id, log.message = new_status, oid, msg
    return JSONResponse(status_code=status_code, content={**body, "log_id": log_id, "status": new_status})


@router.get("/orders")
async def order_log(user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as s:
        rows = (await s.execute(select(OrderLog).where(OrderLog.user_id == user["sub"]).order_by(OrderLog.created_at.desc()).limit(50))).scalars().all()
        return {"orders": [{"id": r.id, "time": r.created_at.isoformat() if r.created_at else None, "symbol": r.tradingsymbol, "exchange": r.exchange,
                            "side": r.side, "quantity": r.quantity, "price": r.price, "product": r.product, "status": r.status,
                            "broker_order_id": r.broker_order_id, "message": r.message} for r in rows]}
