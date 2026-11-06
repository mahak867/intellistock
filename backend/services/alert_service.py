"""Check stored alert rules against the latest prices and tell the user.

Prices here are END-OF-DAY closes, never live. Three rule types are supported:
  price_above / price_below   price_target is the level
  vol_spike                   price_target is a multiple: fires when the last day's high-low range is that many times the
                              stock's normal range (average of the 60 days before it)
When prices are placeholders or unlicensed, rules are still checked so you can see them work, but the result is labelled
and nothing is sent outside the app.

Users who have connected Zerodha (and whose Kite plan includes market data) get price alerts checked against the LIVE
last traded price from their own account instead of the end-of-day close.
"""
from __future__ import annotations

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from loguru import logger
from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import get_session
from backend.data import providers
from backend.models.db_models import AlertRule, BrokerConnection, User
from backend.tools import alerts as A

SUPPORTED = ("price_above", "price_below", "vol_spike")
MAX_RULES_PER_USER = 50


def snapshot(df) -> dict:
    """Latest bar plus the stock's normal daily range, from the 60 days before the latest bar."""
    last = df.iloc[-1]
    prior = df.iloc[-61:-1]
    normal = None
    if len(prior) >= 20:
        vals = [A._parkinson_daily(float(h), float(l)) for h, l in zip(prior["high"], prior["low"]) if h > 0 and l > 0 and h >= l]
        if vals:
            normal = sum(vals) / len(vals)
    return {"price": float(last["close"]), "day_high": float(last["high"]), "day_low": float(last["low"]),
            "forecast_daily_vol": normal if normal and math.isfinite(normal) else None}


def _rule(r: AlertRule) -> A.Rule:
    default = 2.0 if r.alert_type == "vol_spike" else 0.0
    return A.Rule(id=str(r.id), symbol=r.ticker, kind=r.alert_type, value=float(r.price_target or default), once=True)


def _telegram(token: str, chat_id: str):
    return A.TelegramSender(token, chat_id)


async def check_alerts(user_id: str | None = None, make_sender: Callable[[str, str], object] = _telegram) -> dict:
    async with get_session() as session:
        q = (select(AlertRule, User).join(User, User.id == AlertRule.user_id)
             .where(AlertRule.is_active.is_(True), AlertRule.deleted_at.is_(None), User.is_active.is_(True),
                    AlertRule.alert_type.in_(SUPPORTED)))
        if user_id:
            q = q.where(AlertRule.user_id == user_id)
        rows = (await session.execute(q)).all()

        snaps: dict[str, tuple[dict | None, providers.Prices | None, str | None]] = {}
        for t in sorted({r.ticker for r, _ in rows}):
            try:
                pr = await asyncio.to_thread(providers.get_prices, t, 120)
                snaps[t] = (snapshot(pr.df), pr, None)
            except providers.NoData as e:
                snaps[t] = (None, None, str(e))
            except Exception as e:  # one bad stock must not stop the others
                logger.warning(f"alert check: {t}: {e}")
                snaps[t] = (None, None, "could not read prices")

        live = await _live_prices(session, rows)

        token = settings.TELEGRAM_BOT_TOKEN
        fired, skipped = [], []
        source, real = "synthetic", False
        for rule, user in rows:
            snap, pr, err = snaps[rule.ticker]
            if snap is None or pr is None:
                skipped.append({"ticker": rule.ticker, "reason": err})
                continue
            bar_day: date = pr.df.index[-1].date()
            source, real = pr.source, not pr.synthetic
            lp = live.get(rule.user_id, {}).get(rule.ticker) if rule.alert_type in ("price_above", "price_below") else None
            if lp is not None:
                snap = {**snap, "price": lp}
            if rule.last_triggered is not None and rule.last_triggered.date() >= bar_day and rule.alert_type == "vol_spike":
                continue  # already fired for this day's bar
            hit = A.evaluate([_rule(rule)], {rule.ticker: snap}, bar_day)
            if not hit:
                continue
            if lp is not None:
                text = f"{hit[0].message} (live price from your Zerodha account, {datetime.now(IST):%d %b %H:%M} IST)"[:300]
                can_send = bool(token) and bool(user.telegram_chat_id)  # the user's own licensed feed
            else:
                note = "" if real else "[placeholder prices, not real] "
                text = f"{note}{hit[0].message} (close of {bar_day:%d %b %Y})"[:300]
                can_send = real and providers.licensed() and bool(token) and bool(user.telegram_chat_id)
            delivered: bool | None = None
            if can_send:
                try:
                    delivered = bool(await asyncio.to_thread(make_sender(token, user.telegram_chat_id).send, text))
                except Exception as e:
                    logger.warning(f"telegram send failed: {type(e).__name__}")
                    delivered = False
            rule.last_triggered = datetime.now(timezone.utc)
            rule.last_message = text
            rule.trigger_count = (rule.trigger_count or 0) + 1
            if rule.alert_type != "vol_spike":
                rule.is_active = False  # one-shot: re-arm it from the Alerts page
            fired.append({"id": str(rule.id), "ticker": rule.ticker, "message": text, "delivered": delivered, "live": lp is not None})
        return {"checked": len(rows), "fired": fired, "skipped": skipped, "data_source": source, "real_data": real}


IST = timezone(timedelta(hours=5, minutes=30))


async def _live_prices(session, rows) -> dict[str, dict[str, float]]:
    """{user_id: {ticker: last price}} for users with a working Zerodha session. Any failure means end-of-day instead."""
    from backend.services import broker_service as B

    users = {r.user_id for r, _ in rows if r.alert_type in ("price_above", "price_below")}
    if not users:
        return {}
    conns = (await session.execute(select(BrokerConnection).where(BrokerConnection.user_id.in_(users)))).scalars().all()
    out: dict[str, dict[str, float]] = {}
    for c in conns:
        if not B.session_valid(c):
            continue
        tickers = sorted({r.ticker for r, _ in rows if r.user_id == c.user_id})
        try:
            out[c.user_id] = await B.run(B.client(c).ltp, tickers)
        except Exception as e:  # no market-data add-on, expired token, network: fall back quietly
            logger.info(f"live prices unavailable for one user: {type(e).__name__}")
    return out


def check_alerts_sync() -> dict:
    """Entry point for the Celery worker, which has no event loop of its own."""
    from backend.core import database

    async def run() -> dict:
        await database.init_db()
        try:
            return await check_alerts()
        finally:
            await database.close_db()

    return asyncio.run(run())
