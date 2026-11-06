"""Trader and investor tools. Stateless calculations: nothing here touches the database.
In development the routes are open for local previews; otherwise a valid login is required."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
import math
from typing import Literal

from pydantic import BaseModel, Field

from backend.api.routes.auth import get_current_user
from backend.api.safe import SafeRoute
from backend.core.config import settings
from backend.tools import announcements as AN
from backend.tools import calendar as CAL
from backend.tools import costs as CO
from backend.tools import fundamentals as FU
from backend.tools import fundscreen as FS
from backend.tools import taxlots as TL
from backend.tools import journal as J
from backend.tools import options as O
from backend.tools import planner as PL
from backend.tools import portfolio as PF
from backend.tools import risklimits as RL
from backend.tools import sizing as SZ
from backend.tools import tax as TX

router = APIRouter(route_class=SafeRoute, dependencies=[] if settings.is_development else [Depends(get_current_user)])


def _bad(e: Exception):
    raise HTTPException(status_code=422, detail=str(e))


# ── trader ──────────────────────────────────────────────────────────────────
class SizeIn(BaseModel):
    entry: float = Field(gt=0)
    stop: float | None = Field(default=None, gt=0)
    daily_vol_pct: float | None = Field(default=None, gt=0, description="used to place the stop when stop is omitted")
    stop_k: float = 1.5
    hold_days: int = Field(default=5, ge=1)
    risk_amount: float | None = Field(default=None, gt=0)
    capital: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, gt=0, le=100)
    side: str = "long"
    lot_size: int = Field(default=1, ge=1)
    cost_per_share_roundtrip: float = Field(default=0.0, ge=0)
    max_position_pct_of_capital: float | None = None


@router.post("/position-size")
def position_size(b: SizeIn):
    try:
        stop = b.stop
        if stop is None:
            if b.daily_vol_pct is None:
                raise ValueError("give a stop, or daily_vol_pct to place one outside normal noise")
            stop = SZ.volatility_stop(b.entry, b.daily_vol_pct / 100, b.side, b.stop_k, b.hold_days)
        r = SZ.position_size(b.entry, stop, b.risk_amount, b.capital, b.risk_pct, b.side, b.lot_size,
                             cost_per_share_roundtrip=b.cost_per_share_roundtrip,
                             max_position_pct_of_capital=b.max_position_pct_of_capital)
        return {**asdict(r), "stop_was_computed": b.stop is None}
    except ValueError as e:
        _bad(e)


class CostIn(BaseModel):
    segment: str
    buy_price: float = Field(gt=0)
    sell_price: float = Field(gt=0)
    qty: float = Field(gt=0)


@router.post("/costs")
def costs(b: CostIn):
    try:
        buy, sell = CO.trade_cost(b.segment, "buy", b.buy_price, b.qty), CO.trade_cost(b.segment, "sell", b.sell_price, b.qty)
        gross = (b.sell_price - b.buy_price) * b.qty
        return {"buy": asdict(buy), "sell": asdict(sell), "total_costs": round(buy.total + sell.total, 2), "gross_pnl": gross,
                "net_pnl": round(gross - buy.total - sell.total, 2),
                "breakeven_move_pct": CO.breakeven_move_pct(b.segment, b.buy_price, b.qty),
                "note": "Exchange charges and brokerage are approximate: compare with your contract note."}
    except ValueError as e:
        _bad(e)


class JournalIn(BaseModel):
    csv: str = Field(max_length=2_000_000)
    cost_per_trade: float = 0.0
    starting_equity: float = 0.0


@router.post("/journal")
def journal(b: JournalIn):
    try:
        trades = J.pair_trades(J.parse_tradebook(b.csv), b.cost_per_trade)
    except ValueError as e:
        _bad(e)
    a = J.analyse(trades, b.starting_equity)
    return {"stats": a, "flags": J.behaviour_flags(trades), "trades": [
        {**{k: v for k, v in asdict(t).items() if k not in ("entry_time", "exit_time")}, "entry_time": str(t.entry_time), "exit_time": str(t.exit_time)} for t in trades[:500]]}


class OptPriceIn(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    days: float = Field(gt=0)
    rate_pct: float = 6.5
    vol_pct: float | None = Field(default=None, gt=0)
    market_price: float | None = Field(default=None, gt=0)
    kind: str = "call"
    dividend_pct: float = 0.0
    expected_daily_vol_pct: float | None = Field(default=None, gt=0)


@router.post("/options/analyse")
def options_analyse(b: OptPriceIn):
    t, r, q = b.days / 365, b.rate_pct / 100, b.dividend_pct / 100
    try:
        iv = O.implied_vol(b.market_price, b.spot, b.strike, t, r, b.kind, q) if b.market_price else None
        vol = (b.vol_pct / 100) if b.vol_pct else iv
        if vol is None:
            raise ValueError("give vol_pct, or a market_price that implies a volatility")
        res = {"theoretical_price": O.bs_price(b.spot, b.strike, t, r, vol, b.kind, q), "vol_used": vol,
               "implied_vol": iv, "greeks": O.greeks(b.spot, b.strike, t, r, vol, b.kind, q)}
        if iv and b.expected_daily_vol_pct:
            res["vs_expected"] = O.iv_vs_expected(iv, b.expected_daily_vol_pct / 100)
        return res
    except ValueError as e:
        _bad(e)


class LegIn(BaseModel):
    kind: str
    strike: float = Field(gt=0)
    premium: float = Field(ge=0)
    qty: int


class PayoffIn(BaseModel):
    legs: list[LegIn] = Field(min_length=1, max_length=8)
    lo: float = Field(ge=0)
    hi: float = Field(gt=0)


@router.post("/options/payoff")
def options_payoff(b: PayoffIn):
    try:
        legs = [O.Leg(**lg.model_dump()) for lg in b.legs]
        c = O.payoff_curve(legs, b.lo, b.hi)
        return {**c, "net_premium": O.net_premium(legs),
                "note": "Margin for short options comes from your broker's SPAN calculator: it is not estimated here."}
    except ValueError as e:
        _bad(e)


class ChainRow(BaseModel):
    strike: float
    call_oi: float = Field(ge=0)
    put_oi: float = Field(ge=0)


@router.post("/options/chain")
def options_chain(rows: list[ChainRow]):
    chain = [r.model_dump() for r in rows]
    return {**O.put_call_ratio(chain), "max_pain": O.max_pain(chain)}


class DayIn(BaseModel):
    pnls: list[float]
    max_loss: float = Field(gt=0)
    max_trades: int | None = None
    max_consecutive_losses: int | None = 3


@router.post("/risk/day")
def risk_day(b: DayIn):
    return RL.day_status(b.pnls, RL.DayLimits(b.max_loss, b.max_trades, b.max_consecutive_losses))


@router.post("/risk/checklist")
def risk_checklist(answers: dict[str, bool]):
    return {**RL.checklist(answers), "items": [{"text": t, "required": r} for t, r in RL.DEFAULT_CHECKLIST]}


@router.get("/risk/checklist-items")
def checklist_items():
    return [{"text": t, "required": r} for t, r in RL.DEFAULT_CHECKLIST]


class ExpiryIn(BaseModel):
    year: int = Field(ge=2024, le=2035)
    month: int = Field(ge=1, le=12)
    exchange: str = "NSE"
    holidays: list[date] = []


@router.post("/calendar/expiries")
def expiries(b: ExpiryIn):
    wd = 1 if b.exchange.upper() == "NSE" else 3
    hol = set(b.holidays)
    first = date(b.year, b.month, 1)
    last = date(b.year + (b.month == 12), b.month % 12 + 1, 1)
    return {"exchange": b.exchange.upper(), "weekday": "Tuesday" if wd == 1 else "Thursday",
            "monthly": CAL.monthly_expiry(b.year, b.month, hol, wd).isoformat(),
            "weekly": [d.isoformat() for d in CAL.weekly_expiries(first, last, hol, wd) if d.month == b.month],
            "note": "Holidays are not built in: add the exchange's published holiday list."}


# ── investor ────────────────────────────────────────────────────────────────
class PortfolioIn(BaseModel):
    csv: str = Field(max_length=500_000)
    prices: dict[str, float]


@router.post("/portfolio/allocation")
def portfolio_allocation(b: PortfolioIn):
    try:
        return PF.allocation(PF.parse_holdings(b.csv), b.prices)
    except ValueError as e:
        _bad(e)


class FlowIn(BaseModel):
    date: date
    amount: float


@router.post("/portfolio/xirr")
def portfolio_xirr(flows: list[FlowIn]):
    r = PF.xirr([(f.date, f.amount) for f in flows])
    return {"xirr": r, "note": "Money in is negative, money out (and today's value) is positive."}


class SipIn(BaseModel):
    monthly: float = Field(gt=0)
    annual_return_pct: float = Field(ge=-50, le=100)
    years: int = Field(ge=1, le=60)
    step_up_pct: float = Field(default=0, ge=0, le=100)


@router.post("/planner/sip")
def planner_sip(b: SipIn):
    return PL.sip_future_value(b.monthly, b.annual_return_pct / 100, b.years, b.step_up_pct)


class GoalIn(BaseModel):
    goal_today: float = Field(gt=0)
    years: int = Field(ge=1, le=60)
    annual_return_pct: float = Field(ge=0, le=100)
    inflation_pct: float = Field(default=6, ge=0, le=30)
    step_up_pct: float = Field(default=0, ge=0, le=100)


@router.post("/planner/goal")
def planner_goal(b: GoalIn):
    return PL.required_sip(b.goal_today, b.years, b.annual_return_pct / 100, b.inflation_pct / 100, b.step_up_pct)


class RebalIn(BaseModel):
    values: dict[str, float]
    targets: dict[str, float]
    band_pct: float = 5
    new_cash: float = Field(default=0, ge=0)


@router.post("/planner/rebalance")
def planner_rebalance(b: RebalIn):
    try:
        return PL.rebalance(b.values, b.targets, b.band_pct / 100, b.new_cash)
    except (ValueError, ZeroDivisionError) as e:
        _bad(e)


class FillIn(BaseModel):
    symbol: str
    date: date
    side: str
    qty: float = Field(gt=0)
    price: float = Field(gt=0)
    fmv_31jan2018: float | None = None


@router.post("/tax/capital-gains")
def tax_gains(fills: list[FillIn]):
    try:
        g = TX.realised_gains([TX.Fill(**f.model_dump()) for f in fills])
    except ValueError as e:
        _bad(e)
    return {"summary": TX.tax_summary(g), "lots": [{**x, "sell_date": str(x["sell_date"]), "buy_date": str(x["buy_date"])} for x in g],
            "disclaimer": "Estimate for listed-equity delivery trades only. A chartered accountant must confirm before you file."}


class TaxLotsIn(BaseModel):
    csv: str = Field(max_length=5_000_000)
    prices: dict[str, float] | None = None  # symbol -> current price; missing symbols use the latest close on this server
    as_of: date | None = None


@router.post("/tax/lots", summary="FIFO tax lots, realised gains by year, and LTCG harvesting from your tradebook")
def tax_lots(b: TaxLotsIn):
    from backend.data import providers

    as_of = b.as_of or date.today()
    prices = {k.strip().upper(): float(v) for k, v in (b.prices or {}).items() if v and v > 0 and math.isfinite(v)}
    try:
        fills, _ = TL.parse_tradebook(b.csv)
    except ValueError as e:
        _bad(e)
    sources, placeholder = {}, False
    for s in sorted({f["symbol"] for f in fills} - set(prices))[:200]:
        try:
            pr = providers.get_prices(s, 260)
            prices[s] = float(pr.df["close"].iloc[-1])
            sources[s] = pr.source
            placeholder = placeholder or pr.synthetic
        except Exception:
            continue
    try:
        out = TL.report(b.csv, prices, as_of)
    except ValueError as e:
        _bad(e)
    out["price_sources"] = {**{k: "you" for k in (b.prices or {})}, **sources}
    if placeholder:
        out["warnings"].insert(0, "Some current prices are PLACEHOLDERS (this server has no real price data), so open-lot values and harvesting numbers are illustrations only. Enter real prices or connect Zerodha.")
    return out


@router.post("/fundamentals/score")
def fundamentals_score(f: dict[str, float | None]):
    return FU.quality_score(f)


class FundFilter(BaseModel):
    field: Literal[FS.FIELDS]  # type: ignore[valid-type]
    min: float | None = Field(default=None, allow_inf_nan=False, ge=-1e12, le=1e12)
    max: float | None = Field(default=None, allow_inf_nan=False, ge=-1e12, le=1e12)


class FundScreenIn(BaseModel):
    csv: str = Field(max_length=3_000_000)
    filters: list[FundFilter] = Field(default_factory=list, max_length=FS.MAX_FILTERS)
    sort: str = "quality"
    limit: int = Field(default=50, ge=1, le=200)


@router.post("/screener/fundamentals", summary="Filter and rank stocks on fundamentals from your own CSV")
def screener_fundamentals(b: FundScreenIn):
    try:
        return FS.screen(b.csv, [f.model_dump() for f in b.filters], b.sort, b.limit)
    except ValueError as e:
        _bad(e)


class LiveScreenIn(BaseModel):
    universe: Literal["nifty50", "custom"] = "nifty50"
    tickers: list[str] = Field(default_factory=list, max_length=200)
    filters: list[FundFilter] = Field(default_factory=list, max_length=FS.MAX_FILTERS)
    sort: str = "quality"
    limit: int = Field(default=50, ge=1, le=200)


@router.post("/screener/fundamentals/live", summary="Fundamentals screener on Yahoo Finance data (NIFTY 50 or your list)")
def screener_fundamentals_live(b: LiveScreenIn):
    import re as _re

    import pandas as pd

    from backend.data import fundamentals_feed as FF
    from ml.data.pipeline import NIFTY50_TICKERS

    syms = NIFTY50_TICKERS if b.universe == "nifty50" else [t.strip().upper() for t in b.tickers]
    syms = [s for s in dict.fromkeys(syms) if _re.fullmatch(r"[A-Z0-9&._-]{1,20}", s)]
    if not syms:
        _bad(ValueError("Give at least one valid symbol."))
    rows, missing = FF.fetch_many(syms)
    if not rows:
        raise HTTPException(status_code=502, detail="Yahoo Finance returned no fundamentals (unreachable or rate-limited). Try again later.")
    df = pd.DataFrame(rows)
    fields = [f for f in FS.FIELDS if f in df.columns and df[f].notna().any()]
    info = {"rows": len(df), "recognised": {f: "Yahoo Finance" for f in fields}}
    try:
        out = FS.screen_frame(df[["symbol", *fields]].copy(), info, [f.model_dump() for f in b.filters], b.sort, b.limit)
    except ValueError as e:
        _bad(e)
    names = {r["symbol"]: (r.get("name"), r.get("sector")) for r in rows}
    for r in out["rows"]:
        r["name"], r["sector"] = names.get(r["symbol"], (None, None))
    out.update(source="Yahoo Finance (its own compilation; check the annual report for anything important)", missing=missing)
    out["note"] = "Yahoo has no promoter holding or pledge data for Indian stocks, so filters on those match nothing here."
    return out


class AnnIn(BaseModel):
    symbol: str
    title: str
    date: date
    url: str = ""


@router.post("/announcements/digest")
def announcements(items: list[AnnIn]):
    return [{**x, "date": str(x["date"])} for x in AN.digest([i.model_dump() for i in items])]
