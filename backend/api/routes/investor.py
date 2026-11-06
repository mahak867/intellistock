"""
Holdings extras (mounted under /users):

• GET    /users/portfolio/performance          — XIRR per holding and overall, against NIFTY 50, with dividends
• GET    /users/corporate-actions              — dividends, splits and bonuses you confirmed
• POST   /users/corporate-actions              — add one
• DELETE /users/corporate-actions/{id}         — remove one
• GET    /users/corporate-actions/lookup/{sym} — NSE's list for a stock, to pick from (not saved)
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.api.routes.auth import get_current_user
from backend.core.database import get_session
from backend.models.db_models import CorporateAction
from backend.services import holdings_service as H
from backend.tools import corpactions as CA

router = APIRouter()


class ActionIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._&-]+$")
    kind: Literal["dividend", "split", "bonus"]
    ex_date: date
    amount: float | None = Field(default=None, gt=0, lt=1e6, allow_inf_nan=False)
    ratio_new: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    ratio_old: float | None = Field(default=None, gt=0, le=1000, allow_inf_nan=False)
    source: Literal["manual", "nse"] = "manual"

    @model_validator(mode="after")
    def _fields(self):
        if self.kind == "dividend" and self.amount is None:
            raise ValueError("a dividend needs the amount per share")
        if self.kind in ("split", "bonus") and (self.ratio_new is None or self.ratio_old is None):
            raise ValueError("a split needs old and new face value; a bonus needs the ratio a:b")
        if self.kind == "split" and self.ratio_new <= self.ratio_old:
            raise ValueError("a split goes from a higher face value to a lower one (for example 10 to 2)")
        if self.ex_date > date(2100, 1, 1) or self.ex_date < date(1990, 1, 1):
            raise ValueError("ex-date out of range")
        return self


@router.get("/portfolio/performance")
async def portfolio_performance(account: str | None = Query(default=None, max_length=40), user: dict = Depends(get_current_user)) -> dict:
    """account: one family member's holdings only; omit for everyone together."""
    async with get_session() as s:
        everything = await H.adjusted(s, user["sub"])
        hold = [h for h in everything if account is None or h["account"] == account]
        prices, source, real = await H.prices_for(s, user["sub"], sorted({h["ticker"] for h in hold}))
    out = await asyncio.to_thread(H.performance, hold, prices, H.today_ist())
    out.update(price_source=source, real_prices=real, accounts=sorted({h["account"] for h in everything}), account=account)
    if not real:
        out["warning"] = "Prices are PLACEHOLDERS on this server, so values and returns are illustrations only. Connect Zerodha or load NSE data."
    return out


def _row(a: CorporateAction) -> dict:
    return {"id": a.id, "ticker": a.ticker, "kind": a.kind, "ex_date": str(a.ex_date), "amount": a.amount,
            "ratio_new": a.ratio_new, "ratio_old": a.ratio_old, "source": a.source}


@router.get("/corporate-actions")
async def list_actions(user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as s:
        rows = (await s.execute(select(CorporateAction).where(CorporateAction.user_id == user["sub"]).order_by(CorporateAction.ex_date.desc()))).scalars().all()
        return {"actions": [_row(a) for a in rows]}


@router.post("/corporate-actions", status_code=201)
async def add_action(b: ActionIn, user: dict = Depends(get_current_user)) -> dict:
    try:
        async with get_session() as s:
            a = CorporateAction(user_id=user["sub"], ticker=b.ticker.upper(), kind=b.kind, ex_date=b.ex_date,
                                amount=b.amount if b.kind == "dividend" else None,
                                ratio_new=b.ratio_new if b.kind != "dividend" else None, ratio_old=b.ratio_old if b.kind != "dividend" else None,
                                source=b.source)
            s.add(a)
            await s.flush()
            return _row(a)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="That action is already recorded for this stock and date.") from None


@router.delete("/corporate-actions/{action_id}", status_code=204, response_model=None)
async def delete_action(action_id: uuid.UUID, user: dict = Depends(get_current_user)) -> None:
    async with get_session() as s:
        a = (await s.execute(select(CorporateAction).where(CorporateAction.id == str(action_id), CorporateAction.user_id == user["sub"]))).scalar_one_or_none()
        if not a:
            raise HTTPException(status_code=404, detail="Not found")
        await s.delete(a)


@router.get("/corporate-actions/lookup/{ticker}")
async def lookup(ticker: str, user: dict = Depends(get_current_user)) -> dict:
    t = ticker.strip().upper()
    if not CA.re.fullmatch(r"[A-Z0-9&._-]{1,20}", t):
        raise HTTPException(status_code=422, detail="Not a valid NSE symbol.")
    try:
        rows = await asyncio.to_thread(CA.fetch_nse, t)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"NSE did not answer ({type(e).__name__}). Enter the action yourself from the company's announcement.") from None
    return {"ticker": t, "source": "nseindia.com (unofficial website API)", "actions": [{**r, "ex_date": str(r["ex_date"])} for r in rows],
            "note": "Check each against the company's announcement before adding it."}
