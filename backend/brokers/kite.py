"""Zerodha Kite Connect v3, the parts IntelliStock uses: login, holdings, last traded price, limit orders, logout.

Each user brings their own Kite Connect app (api_key + api_secret from developers.kite.trade). The access token is valid
until about 6 AM IST the next day, after which the user logs in again (a Zerodha rule, not ours).

Order placement under the April 2026 retail-API rules: orders are only accepted from the static IP registered on the
user's Kite developer profile, at most 10 orders a second. IntelliStock sends one order per explicit confirmation, so it
stays far below that, but the server's IP must be registered by the user or Zerodha rejects the order.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlencode

import httpx

from backend.core.config import settings

IST = timezone(timedelta(hours=5, minutes=30))
SYMBOL = re.compile(r"^[A-Z0-9&_.-]{1,30}$")


class KiteError(Exception):
    """A Kite API error. `kind` is Kite's error_type (TokenException, InputException, PermissionException, ...)."""

    def __init__(self, message: str, kind: str = "KiteError", status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status

    @property
    def needs_login(self) -> bool:
        # Kite answers 403 for both expired tokens (TokenException) and plan limits (PermissionException).
        return self.kind == "TokenException" or (self.status == 403 and self.kind == "KiteError")


def api_base() -> str:
    return getattr(settings, "KITE_API_BASE", "https://api.kite.trade").rstrip("/")


def login_base() -> str:
    return getattr(settings, "KITE_LOGIN_BASE", "https://kite.zerodha.com").rstrip("/")


def login_url(api_key: str) -> str:
    return f"{login_base()}/connect/login?{urlencode({'v': 3, 'api_key': api_key})}"


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256((api_key + request_token + api_secret).encode()).hexdigest()


def token_expiry(login_at: datetime) -> datetime:
    """Kite tokens lapse at 6 AM IST on the next morning (or this morning, if you logged in before 6)."""
    local = login_at.astimezone(IST)
    six = datetime.combine(local.date(), time(6, 0), IST)
    return (six if local < six else six + timedelta(days=1)).astimezone(timezone.utc)


@dataclass
class Kite:
    api_key: str
    access_token: str | None = None
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=15))

    def _headers(self) -> dict:
        h = {"X-Kite-Version": "3"}
        if self.access_token:
            h["Authorization"] = f"token {self.api_key}:{self.access_token}"
        return h

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.client.request(method, api_base() + path, headers=self._headers(), **kw)
        except httpx.HTTPError as e:
            raise KiteError(f"Could not reach Zerodha ({type(e).__name__}).", "NetworkException") from None
        try:
            body = r.json()
        except ValueError:
            raise KiteError(f"Zerodha answered with an unreadable response (HTTP {r.status_code}).", "DataException", r.status_code) from None
        if r.status_code >= 400 or body.get("status") != "success":
            raise KiteError(str(body.get("message") or f"HTTP {r.status_code}").rstrip(". ")[:300], str(body.get("error_type") or "KiteError"), r.status_code)
        return body.get("data")

    # ── session ──
    def create_session(self, request_token: str, api_secret: str) -> dict:
        if not re.fullmatch(r"[A-Za-z0-9]{6,64}", request_token or ""):
            raise KiteError("That login link is not valid. Start the Zerodha login again.", "InputException")
        data = self._call("POST", "/session/token", data={"api_key": self.api_key, "request_token": request_token,
                                                           "checksum": checksum(self.api_key, request_token, api_secret)})
        if not data or not data.get("access_token"):
            raise KiteError("Zerodha did not return an access token.", "DataException")
        self.access_token = data["access_token"]
        return data

    def logout(self) -> None:
        if self.access_token:
            self._call("DELETE", "/session/token", params={"api_key": self.api_key, "access_token": self.access_token})

    # ── data ──
    def holdings(self) -> list[dict]:
        rows = self._call("GET", "/portfolio/holdings") or []
        out = []
        for h in rows:
            qty = float(h.get("quantity") or 0) + float(h.get("t1_quantity") or 0)
            if qty <= 0:
                continue
            out.append({"ticker": str(h.get("tradingsymbol", "")).upper(), "exchange": h.get("exchange", "NSE"), "quantity": qty,
                        "avg_buy_price": float(h.get("average_price") or 0), "last_price": h.get("last_price"),
                        "pnl": h.get("pnl"), "isin": h.get("isin")})
        return out

    def ltp(self, tickers: list[str], exchange: str = "NSE") -> dict[str, float]:
        keys = [f"{exchange}:{t.upper()}" for t in tickers if SYMBOL.match(t.upper())]
        if not keys:
            return {}
        data = self._call("GET", "/quote/ltp", params=[("i", k) for k in keys[:500]]) or {}
        return {k.split(":", 1)[1]: float(v["last_price"]) for k, v in data.items() if v and v.get("last_price") is not None}

    # ── orders ──
    def place_limit_order(self, *, tradingsymbol: str, exchange: str, side: str, quantity: int, price: float,
                          product: str, tag: str = "intellistock") -> str:
        data = self._call("POST", "/orders/regular", data={
            "tradingsymbol": tradingsymbol, "exchange": exchange, "transaction_type": side, "order_type": "LIMIT",
            "quantity": int(quantity), "price": f"{price:.2f}", "product": product, "validity": "DAY", "tag": tag[:20]})
        oid = (data or {}).get("order_id")
        if not oid:
            raise KiteError("Zerodha did not return an order id. Check the Kite app before trying again.", "DataException")
        return str(oid)
