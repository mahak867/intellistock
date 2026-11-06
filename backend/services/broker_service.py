"""Per-user broker link: store keys, log in, read holdings and live prices, and send confirmed limit orders."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select

from backend.brokers import kite as K
from backend.brokers.vault import VaultError, seal, unseal
from backend.core.config import settings
from backend.models.db_models import BrokerConnection

CONFIRM_SECONDS = 120
MAX_ORDER_VALUE = 1_000_000.0   # rupees per order; a typo guard, not a risk limit
MAX_PRICE_GAP = 0.20            # a limit price more than 20% from the live price is almost always a typo

make_client: Callable[[str, str | None], K.Kite] = lambda api_key, token: K.Kite(api_key, token)  # noqa: E731


class BrokerProblem(Exception):
    """Something the user can fix; `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


async def get_conn(session, user_id: str) -> BrokerConnection | None:
    return (await session.execute(select(BrokerConnection).where(BrokerConnection.user_id == user_id))).scalar_one_or_none()


def session_valid(c: BrokerConnection | None) -> bool:
    exp = _aware(c.token_expires_at) if c else None
    return bool(c and c.access_token_enc and exp and exp > _now())


def status(c: BrokerConnection | None) -> dict:
    if not c:
        return {"connected": False, "broker": None, "session_valid": False, "orders_enabled": settings.BROKER_ORDERS_ENABLED}
    return {"connected": True, "broker": c.broker, "api_key": c.api_key[:4] + "…" if c.api_key else None,
            "session_valid": session_valid(c), "broker_user_id": c.broker_user_id, "broker_user_name": c.broker_user_name,
            "session_expires_at": _aware(c.token_expires_at).isoformat() if c.token_expires_at else None,
            "login_url": K.login_url(c.api_key), "orders_enabled": settings.BROKER_ORDERS_ENABLED}


def client(c: BrokerConnection | None) -> K.Kite:
    if not c:
        raise BrokerProblem("No broker connected. Add your Kite Connect keys on the Broker page.", 409)
    if not session_valid(c):
        raise BrokerProblem("Your Zerodha session has ended (they end every morning at 6 AM). Log in with Zerodha again.", 401)
    try:
        return make_client(c.api_key, unseal(c.access_token_enc))
    except VaultError as e:
        raise BrokerProblem(str(e), 409) from None


async def run(fn, *args, **kw):
    """Kite calls are blocking HTTP; keep them off the event loop and turn Kite errors into user-facing ones."""
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except K.KiteError as e:
        if e.needs_login:
            raise BrokerProblem(f"Zerodha says: {e}. Log in with Zerodha again.", 401) from None
        if e.kind == "PermissionException":
            raise BrokerProblem(f"Zerodha says: {e}. Your Kite Connect plan may not include this (live prices need the market data add-on).", 403) from None
        if e.kind == "NetworkException":
            raise BrokerProblem(str(e), 502) from None
        raise BrokerProblem(f"Zerodha says: {e}", 422 if e.kind == "InputException" else 502) from None


async def save_keys(session, user_id: str, api_key: str, api_secret: str) -> BrokerConnection:
    c = await get_conn(session, user_id)
    if c is None:
        c = BrokerConnection(user_id=user_id, broker="kite", api_key=api_key, api_secret_enc=seal(api_secret))
        session.add(c)
    else:
        c.api_key, c.api_secret_enc = api_key, seal(api_secret)
        c.access_token_enc, c.token_expires_at, c.broker_user_id, c.broker_user_name = None, None, None, None
    await session.flush()
    return c


async def finish_login(session, user_id: str, request_token: str) -> BrokerConnection:
    c = await get_conn(session, user_id)
    if not c:
        raise BrokerProblem("Save your Kite Connect keys first.", 409)
    try:
        secret = unseal(c.api_secret_enc)
    except VaultError as e:
        raise BrokerProblem(str(e), 409) from None
    k = make_client(c.api_key, None)
    data = await run(k.create_session, request_token, secret)
    c.access_token_enc = seal(data["access_token"])
    c.token_expires_at = K.token_expiry(_now())
    c.broker_user_id = str(data.get("user_id") or "")[:32] or None
    c.broker_user_name = str(data.get("user_name") or "")[:100] or None
    await session.flush()
    return c


async def disconnect(session, user_id: str) -> bool:
    c = await get_conn(session, user_id)
    if not c:
        return False
    if session_valid(c):
        try:
            await run(client(c).logout)
        except BrokerProblem:
            pass  # forgetting the token locally is what matters
    await session.delete(c)
    return True


# ── order confirmation ──
def _order_key(user_id: str, o: dict) -> str:
    return f"{user_id}|{o['tradingsymbol']}|{o['exchange']}|{o['side']}|{int(o['quantity'])}|{o['price']:.2f}|{o['product']}"


def confirm_token(user_id: str, o: dict, now: float | None = None) -> str:
    exp = int((now or time.time()) + CONFIRM_SECONDS)
    sig = hmac.new(settings.SECRET_KEY.encode(), f"{_order_key(user_id, o)}|{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def check_confirm(user_id: str, o: dict, token: str, now: float | None = None) -> str:
    """Returns the signature (stored so the same confirmation cannot send a second order)."""
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except (ValueError, AttributeError):
        raise BrokerProblem("Preview the order again before sending.", 400) from None
    good = hmac.new(settings.SECRET_KEY.encode(), f"{_order_key(user_id, o)}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        raise BrokerProblem("The order changed after the preview. Preview it again.", 400)
    if (now or time.time()) > exp:
        raise BrokerProblem("The preview expired (2 minutes). Preview the order again.", 400)
    return sig
