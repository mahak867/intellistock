"""
Everything you own, in one place.

• GET    /assets                       — bank balances, deposits, PPF/EPF/NPS, bonds, gold... plus net worth with stocks and funds
• POST   /assets                       — add one by hand
• DELETE /assets/{id}                  — remove one
• POST   /assets/import-bank           — latest balance from a bank statement (CSV/Excel)
• POST   /assets/import-holdings       — stocks from a broker holdings export (Zerodha, Groww, Upstox, Angel...)
• POST   /assets/import-depository     — NSDL/CDSL CAS PDF: stocks, funds, bonds and NPS from all demat accounts
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select

from backend.api.routes.auth import get_current_user
from backend.core.database import get_session
from backend.models.db_models import FundHolding, FundTransaction, OtherAsset, PortfolioEntry
from backend.tools import assets as AS
from backend.tools import cas as CAS

router = APIRouter()
IST = timezone(timedelta(hours=5, minutes=30))
NAME = r"^[A-Za-z0-9 ._&()-]{1,40}$"
MAX_FILE = 10 * 1024 * 1024


def _today() -> date:
    return datetime.now(IST).date()


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=413, detail="The file is over 10 MB.")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")
    return data


class AssetIn(BaseModel):
    kind: Literal[AS.KINDS]  # type: ignore[valid-type]
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^\x00<>]+$")
    amount: float = Field(gt=0, lt=1e12, allow_inf_nan=False)
    rate: float | None = Field(default=None, ge=0, le=50, allow_inf_nan=False)
    start_date: date | None = None
    maturity_date: date | None = None
    account: str = Field(default="Me", pattern=NAME)

    @model_validator(mode="after")
    def _dates(self):
        if self.start_date and self.maturity_date and self.maturity_date < self.start_date:
            raise ValueError("maturity is before the start date")
        if self.kind in ("fd", "rd") and (self.rate is None or self.start_date is None):
            raise ValueError("a deposit needs its interest rate and start date")
        return self


def _value(a: OtherAsset, today: date) -> float:
    if a.kind in ("fd", "rd"):
        return AS.fd_value(a.amount, a.rate, a.start_date, a.maturity_date, today)
    return a.amount


def _row(a: OtherAsset, today: date) -> dict:
    return {"id": a.id, "account": a.account, "kind": a.kind, "name": a.name, "amount": a.amount, "value": _value(a, today), "rate": a.rate,
            "start_date": str(a.start_date) if a.start_date else None, "maturity_date": str(a.maturity_date) if a.maturity_date else None,
            "as_of": str(a.as_of) if a.as_of else None, "source": a.source,
            "matured": bool(a.maturity_date and a.maturity_date <= today)}


@router.get("")
async def list_assets(user: dict = Depends(get_current_user)) -> dict:
    from backend.api.routes.funds import list_funds
    from backend.services import holdings_service as H

    today = _today()
    async with get_session() as s:
        rows = (await s.execute(select(OtherAsset).where(OtherAsset.user_id == user["sub"]).order_by(OtherAsset.kind, OtherAsset.name))).scalars().all()
        hold = await H.adjusted(s, user["sub"])
        prices, source, real = await H.prices_for(s, user["sub"], sorted({h["ticker"] for h in hold}))
    other = [_row(a, today) for a in rows]
    stocks_by: dict[str, float] = {}
    for h in hold:
        p = prices.get(h["ticker"])
        if p:
            stocks_by[h["account"]] = stocks_by.get(h["account"], 0) + h["quantity"] * p
    funds = await list_funds(user)
    funds_by: dict[str, float] = {}
    for f in funds["funds"]:
        funds_by[f["account"]] = funds_by.get(f["account"], 0) + (f["value"] or 0)
    other_by: dict[str, float] = {}
    for a in other:
        other_by[a["account"]] = other_by.get(a["account"], 0) + a["value"]
    people = sorted(set(stocks_by) | set(funds_by) | set(other_by))
    by_person = [{"account": p, "stocks": round(stocks_by.get(p, 0), 2) if real else None, "funds": round(funds_by.get(p, 0), 2),
                  "other": round(other_by.get(p, 0), 2)} for p in people]
    for r in by_person:
        r["total"] = None if r["stocks"] is None else round(r["stocks"] + r["funds"] + r["other"], 2)
    stocks_total = round(sum(stocks_by.values()), 2) if real else None
    total = None if stocks_total is None else round(stocks_total + sum(funds_by.values()) + sum(other_by.values()), 2)
    by_kind: dict[str, float] = {}
    for a in other:
        by_kind[a["kind"]] = by_kind.get(a["kind"], 0) + a["value"]
    return {"assets": other, "net_worth": {"stocks": stocks_total, "funds": round(sum(funds_by.values()), 2), "other": round(sum(other_by.values()), 2),
                                            "total": total, "by_kind": {k: round(v, 2) for k, v in by_kind.items()}, "by_person": by_person,
                                            "stock_prices": source, "note": None if real else "Stock prices on this server are placeholders, so stocks are left out of the total. Connect Zerodha or load NSE data."},
            "as_of": str(today)}


@router.post("", status_code=201)
async def add_asset(b: AssetIn, user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as s:
        a = OtherAsset(user_id=user["sub"], account=b.account.strip(), kind=b.kind, name=b.name.strip(), amount=b.amount, rate=b.rate,
                       start_date=b.start_date, maturity_date=b.maturity_date, source="manual")
        s.add(a)
        await s.flush()
        return _row(a, _today())


@router.delete("/{asset_id}", status_code=204, response_model=None)
async def delete_asset(asset_id: uuid.UUID, user: dict = Depends(get_current_user)) -> None:
    async with get_session() as s:
        a = (await s.execute(select(OtherAsset).where(OtherAsset.id == str(asset_id), OtherAsset.user_id == user["sub"]))).scalar_one_or_none()
        if not a:
            raise HTTPException(status_code=404, detail="Not found")
        await s.delete(a)


@router.post("/import-bank")
async def import_bank(file: UploadFile = File(...), account: str = Form(default="Me", pattern=NAME),
                      name: str = Form(default="", max_length=100), user: dict = Depends(get_current_user)) -> dict:
    data = await _read(file)
    try:
        info = await asyncio.to_thread(AS.bank_balance, data, file.filename or "statement.csv")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    label = (name.strip() or " ".join(x for x in (info["bank"], "savings", info["account_hint"]) if x) or "Bank account")[:100]
    async with get_session() as s:
        a = (await s.execute(select(OtherAsset).where(OtherAsset.user_id == user["sub"], OtherAsset.kind == "bank",
                                                      OtherAsset.name == label, OtherAsset.account == account.strip()))).scalar_one_or_none()
        if a is None:
            a = OtherAsset(user_id=user["sub"], account=account.strip(), kind="bank", name=label, amount=max(info["balance"], 0.01), source="bank_statement")
            s.add(a)
        a.amount, a.as_of = max(info["balance"], 0.01), info["as_of"]
        await s.flush()
        return {"message": f"{label}: balance ₹{info['balance']:,.2f}" + (f" on {info['as_of']}" if info["as_of"] else ""), **_row(a, _today()),
                "note": "Only the closing balance is kept, not your transactions." + (" The balance is negative (overdraft), so it was recorded as zero." if info["balance"] <= 0 else "")}


@router.post("/import-holdings")
async def import_holdings(file: UploadFile = File(...), account: str = Form(default="Me", pattern=NAME),
                          mode: Literal["merge", "replace"] = Form(default="merge"), user: dict = Depends(get_current_user)) -> dict:
    data = await _read(file)
    try:
        rows = await asyncio.to_thread(AS.broker_holdings, data, file.filename or "holdings.csv")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not rows:
        raise HTTPException(status_code=422, detail="No holdings found in the file.")
    return await _upsert_stocks(user["sub"], account.strip(), [{"ticker": r["symbol"], "qty": r["qty"], "avg": r["avg_price"]} for r in rows], mode,
                                "Imported from a broker holdings export; buy date unknown, so returns since purchase are not exact.")


async def _upsert_stocks(user_id: str, account: str, rows: list[dict], mode: str, note: str) -> dict:
    now = datetime.now(timezone.utc)
    added = updated = removed = 0
    async with get_session() as s:
        mine = (await s.execute(select(PortfolioEntry).where(PortfolioEntry.user_id == user_id, PortfolioEntry.account == account))).scalars().all()
        if mode == "replace":
            removed = len(mine)
            await s.execute(delete(PortfolioEntry).where(PortfolioEntry.user_id == user_id, PortfolioEntry.account == account))
            mine = []
        by: dict[str, list] = {}
        for e in mine:
            by.setdefault(e.ticker, []).append(e)
        for r in rows:
            t = r["ticker"][:20]
            if not t:
                continue
            same = by.get(t, [])
            if same:
                keep, *extra = same
                keep.quantity, keep.avg_buy_price = r["qty"], r["avg"]
                for x in extra:
                    await s.delete(x)
                updated += 1
            else:
                s.add(PortfolioEntry(user_id=user_id, account=account, ticker=t, exchange="NSE", quantity=r["qty"], avg_buy_price=r["avg"], buy_date=now, notes=note))
                added += 1
    return {"added": added, "updated": updated, "removed": removed, "account": account}


@router.post("/import-depository")
async def import_depository(file: UploadFile = File(...), password: str = Form(..., min_length=1, max_length=64),
                            account: str = Form(default="Me", pattern=NAME), user: dict = Depends(get_current_user)) -> dict:
    data = await _read(file)
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="That is not a PDF. Upload the CAS PDF emailed by NSDL or CDSL.")
    try:
        parsed = await asyncio.wait_for(asyncio.to_thread(CAS.read_pdf, data, password), timeout=90)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Reading the statement took too long.") from None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if parsed.get("accounts") is None:
        raise HTTPException(status_code=422, detail="This is a CAMS/KFintech fund statement. Import it on the Funds page; this button is for NSDL/CDSL statements.")
    got = AS.depository_assets(parsed)
    acct = account.strip()
    skipped = [e["name"] or e["isin"] for e in got["equities"] if not e["symbol"] or not e["price"]]
    stocks = [{"ticker": e["symbol"], "qty": e["qty"], "avg": e["price"]} for e in got["equities"] if e["symbol"] and e["price"]]
    res = await _upsert_stocks(user["sub"], acct, stocks, "merge",
                               "Imported from an NSDL/CDSL statement. The statement has no purchase cost, so cost is the statement price: edit it for correct returns.")
    today = _today()
    async with get_session() as s:
        old = (await s.execute(select(FundHolding.id).where(FundHolding.user_id == user["sub"], FundHolding.source == "cas", FundHolding.account == acct))).scalars().all()
        if old:
            await s.execute(delete(FundTransaction).where(FundTransaction.holding_id.in_(old)))
            await s.execute(delete(FundHolding).where(FundHolding.id.in_(old)))
        nf = 0
        for f in got["funds"]:
            if f["units"] <= 1e-6:
                continue
            key = (f["scheme_code"] or f["isin"] or f["scheme_name"])[:20]
            s.add(FundHolding(user_id=user["sub"], account=acct, folio=f["folio"], scheme_key=key, scheme_code=(f["scheme_code"] or None) and f["scheme_code"][:10],
                              isin=(f["isin"] or None) and f["isin"][:12], scheme_name=f["scheme_name"], units=f["units"], invested=f["invested"],
                              last_nav=f["last_nav"], source="cas"))
            nf += 1
        await s.execute(delete(OtherAsset).where(OtherAsset.user_id == user["sub"], OtherAsset.account == acct, OtherAsset.source == "cas"))
        no = 0
        for b in got["bonds"]:
            if b["value"]:
                s.add(OtherAsset(user_id=user["sub"], account=acct, kind="bond", name=b["name"], amount=b["value"], as_of=today, source="cas"))
                no += 1
        if got["nps"]:
            s.add(OtherAsset(user_id=user["sub"], account=acct, kind="nps", name=got["nps"]["name"] or "NPS", amount=got["nps"]["value"], as_of=today, source="cas"))
            no += 1
    return {"stocks_added": res["added"], "stocks_updated": res["updated"], "funds": nf, "other_assets": no, "skipped_stocks": skipped,
            "message": f"Imported {res['added'] + res['updated']} stocks, {nf} funds and {no} other holdings for {acct}. The password was not stored.",
            "note": "Stock cost is set to the statement price because depository statements do not include purchase cost; edit each holding for correct returns."}
