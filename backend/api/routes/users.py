"""
IntelliStock — Users API
──────────────────────────
Account-scoped resources that aren't auth itself:
• PATCH  /users/me                  — update own profile
• GET    /users/portfolio           — list portfolio entries
• POST   /users/portfolio           — add a portfolio entry
• DELETE /users/portfolio/{id}      — remove a portfolio entry
• GET    /users/alerts              — list alert rules
• POST   /users/alerts              — create an alert rule
• DELETE /users/alerts/{id}         — remove an alert rule
"""


import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.api.routes.auth import get_current_user
from backend.api.types import Exchange, NoNul, OptNoNul
from backend.core.database import get_session
from backend.models.db_models import AlertRule, PortfolioEntry

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    full_name: OptNoNul = Field(default=None, min_length=1, max_length=100)


class PortfolioAddRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._&-]+$")
    exchange: Exchange = "NSE"
    quantity: float = Field(gt=0)
    avg_buy_price: float = Field(gt=0)
    buy_date: datetime
    notes: OptNoNul = Field(default=None, max_length=500)


class AlertAddRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._&-]+$")
    alert_type: str = Field(pattern="^(signal|price_above|price_below)$")
    signal_filter: str | None = Field(default=None, pattern="^(BUY|SELL|HOLD)$")
    price_target: float | None = Field(default=None, gt=0)
    min_confidence: float = Field(default=0.7, ge=0, le=1)


# ─── Profile ──────────────────────────────────────────────────────────────────


@router.patch("/me", summary="Update own profile")
async def update_profile(
    payload: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    from backend.services.user_service import UserService

    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    user = await UserService.update_profile(current_user["sub"], **fields)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Profile updated", "full_name": user.full_name}


# ─── Portfolio ────────────────────────────────────────────────────────────────


@router.get("/portfolio", summary="Get user's portfolio")
async def get_portfolio(current_user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(PortfolioEntry).where(
                PortfolioEntry.user_id == current_user["sub"]
            )
        )
        entries = result.scalars().all()
        return {
            "portfolio": [
                {
                    "id": str(e.id),
                    "ticker": e.ticker,
                    "exchange": e.exchange,
                    "quantity": e.quantity,
                    "avg_buy_price": e.avg_buy_price,
                    "invested_value": e.invested_value,
                    "buy_date": e.buy_date.isoformat(),
                    "notes": e.notes,
                }
                for e in entries
            ],
            "count": len(entries),
        }


@router.post(
    "/portfolio",
    status_code=status.HTTP_201_CREATED,
    summary="Add a portfolio entry",
)
async def add_portfolio_entry(
    payload: PortfolioAddRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    async with get_session() as session:
        entry = PortfolioEntry(
            user_id=current_user["sub"],
            ticker=payload.ticker.upper(),
            exchange=payload.exchange,
            quantity=payload.quantity,
            avg_buy_price=payload.avg_buy_price,
            buy_date=payload.buy_date,
            notes=payload.notes,
        )
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        return {"message": "Portfolio entry added", "id": str(entry.id)}


@router.delete(
    "/portfolio/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a portfolio entry",
    response_model=None,
)
async def remove_portfolio_entry(
    entry_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
) -> None:
    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(PortfolioEntry).where(
                PortfolioEntry.id == entry_id,
                PortfolioEntry.user_id == current_user["sub"],
            )
        )
        entry = result.scalar_one_or_none()
        if not entry:
            raise HTTPException(status_code=404, detail="Portfolio entry not found")
        await session.delete(entry)


# ─── Alerts ───────────────────────────────────────────────────────────────────


@router.get("/alerts", summary="Get user's alert rules")
async def get_alerts(current_user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AlertRule).where(AlertRule.user_id == current_user["sub"])
        )
        rules = result.scalars().all()
        return {
            "alerts": [
                {
                    "id": str(r.id),
                    "ticker": r.ticker,
                    "alert_type": r.alert_type,
                    "signal_filter": r.signal_filter,
                    "price_target": r.price_target,
                    "min_confidence": r.min_confidence,
                    "is_active": r.is_active,
                    "trigger_count": r.trigger_count,
                }
                for r in rules
            ],
            "count": len(rules),
        }


@router.post(
    "/alerts", status_code=status.HTTP_201_CREATED, summary="Create an alert rule"
)
async def add_alert(
    payload: AlertAddRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    async with get_session() as session:
        rule = AlertRule(
            user_id=current_user["sub"],
            ticker=payload.ticker.upper(),
            alert_type=payload.alert_type,
            signal_filter=payload.signal_filter,
            price_target=payload.price_target,
            min_confidence=payload.min_confidence,
        )
        session.add(rule)
        await session.flush()
        await session.refresh(rule)
        return {"message": "Alert created", "id": str(rule.id)}


@router.delete(
    "/alerts/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an alert rule",
    response_model=None,
)
async def remove_alert(
    alert_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
) -> None:
    async with get_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AlertRule).where(
                AlertRule.id == alert_id, AlertRule.user_id == current_user["sub"]
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        await session.delete(rule)
