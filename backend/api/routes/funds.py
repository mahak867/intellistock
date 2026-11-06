"""
Mutual funds.

• GET    /funds                 — your funds valued at the latest AMFI NAV, with XIRR where transactions are known
• POST   /funds/import-cas      — upload a CAS PDF (CAMS, KFintech, NSDL or CDSL) and its password; replaces imported funds
• POST   /funds                 — add a fund by hand (AMFI scheme code, units, amount invested, date)
• DELETE /funds/{id}            — remove one
• GET    /funds/schemes?q=      — search AMFI's scheme list by name
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from backend.api.routes.auth import get_current_user
from backend.core.database import get_session
from backend.data import amfi
from backend.models.db_models import FundHolding, FundTransaction
from backend.tools import cas as CAS
from backend.tools import portfolio as PF

router = APIRouter()
MAX_PDF = 10 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))


async def _navs() -> tuple[dict, str | None]:
    try:
        return await asyncio.to_thread(amfi.navs), None
    except Exception as e:
        return {}, f"AMFI NAVs unavailable right now ({type(e).__name__}); values use the NAV from your statement."


@router.get("/schemes")
async def schemes(q: str = Query(min_length=3, max_length=80), user: dict = Depends(get_current_user)) -> dict:
    data, err = await _navs()
    if err:
        raise HTTPException(status_code=502, detail=err.split(";")[0] + ".")
    return {"schemes": [{"scheme_code": n.code, "name": n.name, "nav": n.nav, "nav_date": str(n.date)} for n in amfi.search(data, q)]}


class ManualIn(BaseModel):
    scheme_code: str = Field(pattern=r"^\d{3,8}$")
    units: float = Field(gt=0, lt=1e9, allow_inf_nan=False)
    invested: float = Field(gt=0, lt=1e12, allow_inf_nan=False)
    date: date
    folio: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9/ -]*$")
    account: str = Field(default="Me", pattern=r"^[A-Za-z0-9 ._&()-]{1,40}$")


@router.post("", status_code=201)
async def add_manual(b: ManualIn, user: dict = Depends(get_current_user)) -> dict:
    data, err = await _navs()
    n = data.get(b.scheme_code)
    if n is None:
        raise HTTPException(status_code=422 if not err else 502, detail=err or "Unknown AMFI scheme code. Search for the fund by name.")
    if b.date > datetime.now(IST).date():
        raise HTTPException(status_code=422, detail="The date is in the future.")
    async with get_session() as s:
        h = FundHolding(user_id=user["sub"], folio=b.folio, scheme_key=b.scheme_code, scheme_code=b.scheme_code, isin=n.isins[0] if n.isins else None,
                        account=b.account.strip(), scheme_name=n.name[:200], units=b.units, invested=b.invested, last_nav=n.nav, last_nav_date=n.date, source="manual")
        s.add(h)
        try:
            await s.flush()
        except Exception:
            raise HTTPException(status_code=409, detail="You already have this fund in that folio.") from None
        s.add(FundTransaction(holding_id=h.id, date=b.date, kind="PURCHASE", amount=-b.invested, units=b.units))
        return {"id": h.id, "scheme_name": h.scheme_name}


@router.post("/import-cas")
async def import_cas(file: UploadFile = File(...), password: str = Form(..., min_length=1, max_length=64),
                     account: str = Form(default="Me", pattern=r"^[A-Za-z0-9 ._&()-]{1,40}$"), user: dict = Depends(get_current_user)) -> dict:
    """Importing for one family member replaces only that member's imported funds."""
    data = await file.read(MAX_PDF + 1)
    if len(data) > MAX_PDF:
        raise HTTPException(status_code=413, detail="The file is over 10 MB; a CAS statement is much smaller.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="That is not a PDF. Upload the CAS statement PDF from CAMS, KFintech, NSDL or CDSL.")
    try:
        parsed = await asyncio.wait_for(asyncio.to_thread(CAS.read_pdf, data, password), timeout=90)
        rows, notes = CAS.holdings_from(parsed)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=422, detail="Reading the statement took too long.") from None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    if not rows:
        raise HTTPException(status_code=422, detail="No mutual fund holdings found in this statement.")
    async with get_session() as s:
        old = (await s.execute(select(FundHolding.id).where(FundHolding.user_id == user["sub"], FundHolding.source == "cas", FundHolding.account == account.strip()))).scalars().all()
        if old:
            await s.execute(delete(FundTransaction).where(FundTransaction.holding_id.in_(old)))
            await s.execute(delete(FundHolding).where(FundHolding.id.in_(old)))
        kept = 0
        for r in rows:
            if r["units"] <= 1e-6:
                continue  # fully redeemed
            key = r["scheme_code"] or r["isin"] or r["scheme_name"][:20]
            h = FundHolding(user_id=user["sub"], account=account.strip(), folio=r["folio"], scheme_key=key[:20], scheme_code=(r["scheme_code"] or None) and r["scheme_code"][:10],
                            isin=(r["isin"] or None) and r["isin"][:12], scheme_name=r["scheme_name"], units=r["units"], invested=r["invested"],
                            last_nav=r["last_nav"], last_nav_date=r["last_nav_date"], source="cas")
            s.add(h)
            await s.flush()
            for t in r["transactions"]:
                s.add(FundTransaction(holding_id=h.id, date=t["date"], kind=t["kind"][:20], amount=t["amount"], units=t["units"]))
            kept += 1
    return {"imported": kept, "notes": notes, "message": f"Imported {kept} funds. Your password was used only to open the file and was not stored."}


@router.delete("/{holding_id}", status_code=204, response_model=None)
async def remove(holding_id: uuid.UUID, user: dict = Depends(get_current_user)) -> None:
    async with get_session() as s:
        h = (await s.execute(select(FundHolding).where(FundHolding.id == str(holding_id), FundHolding.user_id == user["sub"]))).scalar_one_or_none()
        if not h:
            raise HTTPException(status_code=404, detail="Not found")
        await s.execute(delete(FundTransaction).where(FundTransaction.holding_id == h.id))
        await s.delete(h)


@router.get("")
async def list_funds(user: dict = Depends(get_current_user)) -> dict:
    data, err = await _navs()
    isin_map = amfi.by_isin(data) if data else {}
    today = datetime.now(IST).date()
    async with get_session() as s:
        hs = (await s.execute(select(FundHolding).where(FundHolding.user_id == user["sub"]))).scalars().all()
        tx = (await s.execute(select(FundTransaction).where(FundTransaction.holding_id.in_([h.id for h in hs])))).scalars().all() if hs else []
    by_h: dict[str, list] = {}
    for t in tx:
        by_h.setdefault(t.holding_id, []).append(t)
    rows, all_flows, tv, ti = [], [], 0.0, 0.0
    for h in hs:
        n = data.get(h.scheme_code or "") or (isin_map.get(h.isin) if h.isin else None)
        nav, nav_date, src = (n.nav, n.date, "amfi") if n else (h.last_nav, h.last_nav_date, "statement")
        value = h.units * nav if nav else None
        flows = [(t.date, t.amount) for t in by_h.get(h.id, []) if t.amount]
        x = None
        if value and flows and any(a < 0 for _, a in flows) and (today - min(d for d, _ in flows)).days >= 365:
            x = PF.xirr(flows + [(today, value)])
            all_flows += flows
        rows.append({"id": h.id, "account": h.account or "Me", "scheme_name": h.scheme_name, "scheme_code": h.scheme_code, "folio": h.folio, "units": round(h.units, 4),
                     "nav": nav, "nav_date": str(nav_date) if nav_date else None, "nav_source": src, "invested": h.invested,
                     "value": round(value, 2) if value else None,
                     "gain": round(value - h.invested, 2) if value and h.invested else None,
                     "xirr": None if x is None else round(x * 100, 2), "source": h.source})
        tv += value or 0
        ti += h.invested or 0
    total_x = PF.xirr(all_flows + [(today, sum(r["value"] or 0 for r in rows if r["xirr"] is not None))]) if all_flows else None
    return {"funds": rows, "total": {"invested": round(ti, 2), "value": round(tv, 2), "gain": round(tv - ti, 2),
                                     "xirr_of_funds_with_history": None if total_x is None else round(total_x * 100, 2)},
            "nav_note": err, "as_of": str(today)}
