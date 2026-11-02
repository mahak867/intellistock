"""Alert rules and delivery. Rules are evaluated on a snapshot you supply; delivery is Telegram
or WhatsApp Cloud API. Delivery needs your own tokens and cannot be tested without them."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import httpx


@dataclass(frozen=True)
class Rule:
    id: str
    symbol: str
    kind: str                # price_above | price_below | range_breakout | vol_spike | event_soon | expiry_soon
    value: float = 0.0       # price level, vol multiple, or days ahead
    once: bool = True


@dataclass
class Fired:
    rule_id: str
    symbol: str
    message: str


def _parkinson_daily(high: float, low: float) -> float:
    return math.log(high / low) / (2 * math.sqrt(math.log(2)))


def evaluate(rules: list[Rule], snap: dict[str, dict], today: date, events: list[dict] | None = None,
             expiries: list[date] | None = None, already_fired: set[str] | None = None) -> list[Fired]:
    """snap[symbol] = {price, band_lo, band_hi, day_high, day_low, forecast_daily_vol}.
    A missing field means the rule is skipped (never guessed)."""
    done = already_fired or set()
    out: list[Fired] = []
    for r in rules:
        if r.once and r.id in done:
            continue
        s = snap.get(r.symbol, {})
        msg = None
        if r.kind == "price_above" and s.get("price") is not None and s["price"] >= r.value:
            msg = f"{r.symbol} is at {s['price']:.2f}, above your level {r.value:.2f}"
        elif r.kind == "price_below" and s.get("price") is not None and s["price"] <= r.value:
            msg = f"{r.symbol} is at {s['price']:.2f}, below your level {r.value:.2f}"
        elif r.kind == "range_breakout" and None not in (s.get("price"), s.get("band_lo"), s.get("band_hi")):
            if s["price"] > s["band_hi"]:
                msg = f"{r.symbol} broke above its expected range ({s['band_lo']:.2f}-{s['band_hi']:.2f}) at {s['price']:.2f}"
            elif s["price"] < s["band_lo"]:
                msg = f"{r.symbol} broke below its expected range ({s['band_lo']:.2f}-{s['band_hi']:.2f}) at {s['price']:.2f}"
        elif r.kind == "vol_spike" and None not in (s.get("day_high"), s.get("day_low"), s.get("forecast_daily_vol")):
            realised = _parkinson_daily(s["day_high"], s["day_low"])
            if s["forecast_daily_vol"] > 0 and realised >= r.value * s["forecast_daily_vol"]:
                msg = f"{r.symbol} is moving {realised / s['forecast_daily_vol']:.1f}x its normal daily range today"
        elif r.kind == "event_soon":
            for e in events or []:
                if e.get("symbol") == r.symbol and 0 <= (e["date"] - today).days <= int(r.value):
                    msg = f"{r.symbol}: {e['type']} on {e['date']:%d %b} ({(e['date'] - today).days} days)"
                    break
        elif r.kind == "expiry_soon":
            nxt = [d for d in (expiries or []) if 0 <= (d - today).days <= int(r.value)]
            if nxt:
                msg = f"F&O expiry on {nxt[0]:%a %d %b} ({(nxt[0] - today).days} days)"
        if msg:
            out.append(Fired(r.id, r.symbol, msg))
    return out


@dataclass
class TelegramSender:
    token: str
    chat_id: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=10))

    def send(self, text: str) -> bool:
        r = self.client.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                             json={"chat_id": self.chat_id, "text": text})
        return r.status_code == 200 and bool(r.json().get("ok"))


@dataclass
class WhatsAppCloudSender:
    """Meta WhatsApp Cloud API. Free-form text only works inside the 24-hour customer window;
    otherwise Meta requires a pre-approved template message."""
    token: str
    phone_number_id: str
    to: str
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=10))

    def send(self, text: str) -> bool:
        r = self.client.post(f"https://graph.facebook.com/v20.0/{self.phone_number_id}/messages",
                             headers={"Authorization": f"Bearer {self.token}"},
                             json={"messaging_product": "whatsapp", "to": self.to, "type": "text", "text": {"body": text}})
        return r.status_code == 200
