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
• POST   /users/alerts/check        — check your alert rules now against the latest end-of-day prices
• POST   /users/alerts/{id}/rearm   — turn a fired price alert back on
• GET    /users/alerts/settings     — where alerts are delivered
• POST   /users/alerts/test-telegram — send a test message to your Telegram chat
• POST   /users/feedback            — send feedback
"""


import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from backend.api.routes.auth import get_current_user
from backend.api.types import Exchange, NoNul, OptNoNul
from backend.core.database import get_session
from backend.models.db_models import AlertRule, PortfolioEntry

router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────


class UpdateProfileRequest(BaseModel):
    full_name: OptNoNul = Field(default=None, min_length=1, max_length=100)
    # A Telegram chat id is a number (negative for groups). An empty string clears it.
    telegram_chat_id: str | None = Field(default=None, pattern=r"^(-?\d{5,20})?$")


class PortfolioAddRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._&-]+$")
    exchange: Exchange = "NSE"
    quantity: float = Field(gt=0)
    avg_buy_price: float = Field(gt=0)
    buy_date: datetime
    notes: OptNoNul = Field(default=None, max_length=500)


class AlertAddRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._&-]+$")
    # No BUY/SELL "signal" alerts: the forecast has no demonstrated edge, so the app does not issue signals.
    alert_type: str = Field(pattern="^(price_above|price_below|vol_spike)$")
    # price_above / price_below: the price level. vol_spike: how many times its normal daily range (1.2 to 10).
    price_target: float = Field(gt=0, lt=1e9)
    signal_filter: str | None = Field(default=None, pattern="^(BUY|SELL|HOLD)$")  # ignored, kept for old clients
    min_confidence: float = Field(default=0.7, ge=0, le=1)  # ignored, kept for old clients

    @model_validator(mode="after")
    def _spike_range(self):
        if self.alert_type == "vol_spike" and not 1.2 <= self.price_target <= 10:
            raise ValueError("vol_spike needs a multiple between 1.2 and 10")
        return self


class FeedbackRequest(BaseModel):
    category: str = Field(pattern="^(bug|data|feature|other)$")
    message: NoNul = Field(min_length=5, max_length=2000)
    page: OptNoNul = Field(default=None, max_length=100)


# ─── Profile ──────────────────────────────────────────────────────────────────


@router.patch("/me", summary="Update own profile")
async def update_profile(
    payload: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    from backend.services.user_service import UserService

    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    if payload.telegram_chat_id == "":
        fields["telegram_chat_id"] = None
    user = await UserService.update_profile(current_user["sub"], **fields)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"message": "Profile updated", "full_name": user.full_name}


# ─── Portfolio ────────────────────────────────────────────────────────────────


@router.get("/portfolio", summary="Get user's portfolio")
async def get_portfolio(current_user: dict = Depends(get_current_user)) -> dict:
    """Quantities and average prices include the splits and bonuses you recorded (raw_* are as entered)."""
    from backend.services.holdings_service import adjusted

    async with get_session() as session:
        rows = await adjusted(session, current_user["sub"])
        return {"portfolio": rows, "count": len(rows)}


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
                PortfolioEntry.id == str(entry_id),
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
                    "is_active": r.is_active,
                    "trigger_count": r.trigger_count,
                    "last_triggered": r.last_triggered.isoformat() if r.last_triggered else None,
                    "last_message": r.last_message,
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
        from sqlalchemy import func, select

        from backend.services.alert_service import MAX_RULES_PER_USER

        have = (await session.execute(
            select(func.count()).select_from(AlertRule).where(AlertRule.user_id == current_user["sub"])
        )).scalar_one()
        if have >= MAX_RULES_PER_USER:
            raise HTTPException(status_code=409, detail=f"You can have at most {MAX_RULES_PER_USER} alerts. Remove one first.")
        rule = AlertRule(
            user_id=current_user["sub"],
            ticker=payload.ticker.upper(),
            alert_type=payload.alert_type,
            price_target=payload.price_target,
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
                AlertRule.id == str(alert_id), AlertRule.user_id == current_user["sub"]
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        await session.delete(rule)


@router.post("/alerts/check", summary="Check your alerts now against the latest end-of-day prices")
async def check_my_alerts(current_user: dict = Depends(get_current_user)) -> dict:
    from backend.services.alert_service import check_alerts

    return await check_alerts(current_user["sub"])


@router.post("/alerts/{alert_id}/rearm", summary="Turn a fired alert back on")
async def rearm_alert(alert_id: uuid.UUID, current_user: dict = Depends(get_current_user)) -> dict:
    async with get_session() as session:
        from sqlalchemy import select

        rule = (await session.execute(
            select(AlertRule).where(AlertRule.id == str(alert_id), AlertRule.user_id == current_user["sub"])
        )).scalar_one_or_none()
        if not rule:
            raise HTTPException(status_code=404, detail="Alert rule not found")
        rule.is_active = True
        return {"message": "Alert is on again", "id": str(rule.id)}


@router.get("/alerts/settings", summary="Where alerts are delivered")
async def alert_settings(current_user: dict = Depends(get_current_user)) -> dict:
    from backend.core.config import settings
    from backend.data import providers
    from backend.services.user_service import UserService

    user = await UserService.get_by_id(current_user["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    st = providers.status()
    return {
        "telegram_chat_id": user.telegram_chat_id,
        "telegram_available": bool(settings.TELEGRAM_BOT_TOKEN),
        "real_data": bool(st.get("real_data")) and providers.licensed(),
        "check_every_minutes": settings.ALERT_CHECK_MINUTES,
        "note": "Alerts look at the latest end-of-day close, not live prices.",
    }


@router.post("/alerts/test-telegram", summary="Send a test message to your Telegram chat")
async def test_telegram(current_user: dict = Depends(get_current_user)) -> dict:
    import asyncio

    from backend.core.config import settings
    from backend.services.alert_service import _telegram
    from backend.services.user_service import UserService

    user = await UserService.get_by_id(current_user["sub"])
    if not user or not user.telegram_chat_id:
        raise HTTPException(status_code=400, detail="Save your Telegram chat id in Settings first.")
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=503, detail="This server has no Telegram bot configured (TELEGRAM_BOT_TOKEN).")
    try:
        ok = await asyncio.to_thread(_telegram(settings.TELEGRAM_BOT_TOKEN, user.telegram_chat_id).send,
                                     "IntelliStock test message. Alerts will arrive here.")
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram did not accept the message. Message the bot first, then check the chat id.")
    return {"message": "Test message sent"}


@router.post("/feedback", status_code=status.HTTP_201_CREATED, summary="Send feedback")
async def send_feedback(payload: FeedbackRequest, current_user: dict = Depends(get_current_user)) -> dict:
    from backend.models.db_models import Feedback

    async with get_session() as session:
        fb = Feedback(user_id=current_user["sub"], category=payload.category, message=payload.message, page=payload.page)
        session.add(fb)
        await session.flush()
        return {"message": "Thanks, saved", "id": str(fb.id)}
