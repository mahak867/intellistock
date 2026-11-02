"""Indian trading costs. Rates are data, not logic: edit RATES when rules change.

STT rows were checked against Zerodha's support page and NSE circular NSE/FATAX/73524 on
2026-11-01 (F&O STT raised 1 Apr 2026). Exchange transaction charges and the DP charge change
often and differ by broker: treat them as approximate and compare with your contract note.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RATES = {
    # fraction of turnover unless noted
    "stt_sell": {"equity_delivery": 0.001, "equity_intraday": 0.00025, "futures": 0.0005, "options": 0.0015},
    "stt_buy": {"equity_delivery": 0.001, "equity_intraday": 0.0, "futures": 0.0, "options": 0.0},
    "stamp_buy": {"equity_delivery": 0.00015, "equity_intraday": 0.00003, "futures": 0.00002, "options": 0.00003},
    "exchange_txn": {"equity_delivery": 0.0000297, "equity_intraday": 0.0000297, "futures": 0.0000173, "options": 0.0003503},
    "sebi": 0.000001,  # Rs 10 per crore
    "gst": 0.18,       # on brokerage + exchange charges + SEBI fee
    "dp_charge_sell_delivery": 13.5 * 1.18,  # per scrip per day, approximate
}


@dataclass
class Brokerage:
    flat_per_order: float = 20.0   # discount-broker style
    pct_cap: float = 0.0003        # min(pct of turnover, flat)
    delivery_free: bool = True


@dataclass
class CostBreakdown:
    turnover: float
    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    sebi: float = 0.0
    stamp: float = 0.0
    gst: float = 0.0
    dp: float = 0.0
    total: float = field(init=False, default=0.0)

    def __post_init__(self):
        self.total = round(self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst + self.dp, 4)


def trade_cost(segment: str, side: str, price: float, qty: float, brokerage: Brokerage | None = None) -> CostBreakdown:
    """One order. For options, price is the premium per unit and qty is units (lots x lot size)."""
    if segment not in RATES["stt_sell"]:
        raise ValueError(f"unknown segment {segment}")
    if side not in ("buy", "sell"):
        raise ValueError("side must be buy or sell")
    if price <= 0 or qty <= 0:
        raise ValueError("price and qty must be positive")
    b = brokerage or Brokerage()
    turnover = price * qty
    if segment == "equity_delivery" and b.delivery_free:
        brk = 0.0
    else:
        brk = min(turnover * b.pct_cap, b.flat_per_order)
    stt = turnover * (RATES["stt_sell"][segment] if side == "sell" else RATES["stt_buy"][segment])
    exch = turnover * RATES["exchange_txn"][segment]
    sebi = turnover * RATES["sebi"]
    stamp = turnover * RATES["stamp_buy"][segment] if side == "buy" else 0.0
    gst = (brk + exch + sebi) * RATES["gst"]
    dp = RATES["dp_charge_sell_delivery"] if (segment == "equity_delivery" and side == "sell") else 0.0
    return CostBreakdown(turnover, round(brk, 4), round(stt, 4), round(exch, 4), round(sebi, 4), round(stamp, 4), round(gst, 4), round(dp, 4))


def roundtrip_cost(segment: str, buy_price: float, sell_price: float, qty: float, brokerage: Brokerage | None = None) -> float:
    return round(trade_cost(segment, "buy", buy_price, qty, brokerage).total + trade_cost(segment, "sell", sell_price, qty, brokerage).total, 2)


def breakeven_move_pct(segment: str, price: float, qty: float, brokerage: Brokerage | None = None) -> float:
    """% the price must move just to cover costs (flat-price round trip)."""
    return roundtrip_cost(segment, price, price, qty, brokerage) / (price * qty) * 100
