"""Price-driven endpoints: forecast, quotes, screener, backtest and portfolio risk.

Prices come from backend.data.providers. With DATA_PROVIDER=nse they are real NSE end-of-day prices
from your local store; with the default "synthetic" they are placeholders, every response says so, and
outside development the endpoints refuse to serve them.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend.api.routes.auth import get_current_user
from backend.api.safe import SafeRoute
from backend.core.config import settings
from backend.data import providers
from backend.data.providers import NoData
from backend.tools import backtest as BT
from backend.tools import portfolio as PF
from backend.tools import portrisk as PR
from backend.tools import screener as SC
from backend.tools import timemachine as TM
from ml.forecast.quick_forecast import build_features, forecast


def _gate():
    if settings.is_development:
        return
    if providers.provider_name() not in providers.STORE_PROVIDERS or providers.store_source() == "fixture":
        raise HTTPException(status_code=503, detail="No real market data source is configured. Run scripts/fetch_data.py and set DATA_PROVIDER=nse (or local, for licensed vendor data).")
    if not providers.licensed():
        raise HTTPException(status_code=503, detail="NSE end-of-day files are NSE's data: serving them to users needs an NSE Data & Analytics agreement. "
                            "Set NSE_DATA_LICENSED=true once you hold one, or load licensed vendor data with DATA_PROVIDER=local. See LICENSING.md.")


router = APIRouter(route_class=SafeRoute, dependencies=[Depends(_gate)] + ([] if settings.is_development else [Depends(get_current_user)]))


def _ver() -> tuple:
    p = providers.data_dir() / "prices.csv.gz"
    return (providers.provider_name(), str(p), p.stat().st_mtime_ns if p.exists() else 0)


def _ticker(t: str) -> str:
    t = t.upper().strip()
    if not t.replace("-", "").replace("&", "").isalnum() or len(t) > 20:
        raise HTTPException(status_code=422, detail="Invalid ticker")
    return t


def _prices(t: str, days: int):
    try:
        return providers.get_prices(t, days)
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))


def _meta(p: providers.Prices) -> dict:
    return {"synthetic": p.synthetic, "source": p.source, "as_of": str(p.df.index[-1].date()), "quality": p.quality}


@router.get("/status")
def status():
    return providers.status()


@lru_cache(maxsize=256)
def _forecast(t: str, horizon: int, ver: tuple) -> dict:
    p = providers.get_prices(t, 700)
    try:
        res = forecast(p.df, horizon, market=providers.market_frame(p.df.index))
    except ValueError as e:
        raise NoData(f"{t}: {e}")
    candles = [{"time": d.strftime("%Y-%m-%d"), "open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": int(r.volume)}
               for d, r in p.df.tail(260).iterrows()]
    return {"ticker": t, **_meta(p), "candles": candles, **res}


@router.get("/forecast/{ticker}", summary="Likely price range and model quality for a stock")
async def market_forecast(ticker: str, horizon: int = Query(10, ge=1, le=30)):
    t = _ticker(ticker)
    try:
        return await run_in_threadpool(_forecast, t, horizon, _ver())
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))


@lru_cache(maxsize=16)
def _quotes(tickers: tuple[str, ...], ver: tuple) -> list[dict]:
    out = []
    for t in tickers:
        try:
            p = providers.get_prices(t, 300)
        except NoData:
            continue
        df = p.df
        c = df["close"]
        out.append({"ticker": t, "price": float(c.iloc[-1]), "chg": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
                    "spark": [float(x) for x in c.tail(30)], "rsi": float(build_features(df)["rsi"].iloc[-1] * 100),
                    "synthetic": p.synthetic, "source": p.source, "as_of": str(df.index[-1].date())})
    return out


@router.get("/quotes", summary="Last close, daily change and sparkline for a watchlist")
async def market_quotes(tickers: str = Query(..., max_length=600)):
    names = tuple(_ticker(t) for t in tickers.split(",") if t.strip())[:60]
    return await run_in_threadpool(_quotes, names, _ver())


@lru_cache(maxsize=2)
def _screen(ver: tuple) -> dict:
    names = providers.universe()
    frames, asof, src, syn = {}, None, "synthetic", True
    for n in names:
        try:
            p = providers.get_prices(n, 400)
        except NoData:
            continue
        frames[n], asof, src, syn = p.df, p.df.index[-1], p.source, p.synthetic
    if not frames:
        raise NoData("No symbols with enough history. Fetch a longer range.")
    t = SC.build_table(frames)
    rows = t.reset_index(names="symbol").replace({np.nan: None}).to_dict("records")
    return {"synthetic": syn, "source": src, "as_of": str(asof.date()), "universe": len(rows), "rows": rows}


@router.get("/screener", summary="Rank the most liquid stocks by momentum, volatility and volume")
async def market_screener():
    try:
        return await run_in_threadpool(_screen, _ver())
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))


@lru_cache(maxsize=64)
def _backtest(t: str, cost_bps: float, slip_bps: float, ver: tuple) -> dict:
    p = providers.get_prices(t, 1500)
    c = p.df["close"]
    if len(c) < 700:
        raise NoData(f"{t} has {len(c)} days; the walk-forward test needs at least 700. Fetch a longer range.")
    r = BT.run_backtest(c, BT.sma_signal(c, 20, 100), cost_bps, slip_bps)
    hold = BT.run_backtest(c, pd.Series(1.0, index=c.index), cost_bps, slip_bps)
    wf = BT.walk_forward(c, BT.sma_signal, [{"fast": 10, "slow": 50}, {"fast": 20, "slow": 100}, {"fast": 50, "slow": 200}],
                         cost_bps=cost_bps, slippage_bps=slip_bps)
    boot = BT.bootstrap_drawdown(wf["returns"], sims=500)
    step = max(len(r.equity) // 200, 1)
    return {"ticker": t, **_meta(p), "in_sample": r.metrics, "buy_and_hold": hold.metrics,
            "walk_forward_out_of_sample": wf["metrics"], "worst_case_drawdown": boot,
            "equity": [{"time": str(i.date()), "strategy": float(v), "hold": float(hold.equity.loc[i])} for i, v in r.equity.iloc[::step].items()]}


@router.get("/backtest/{ticker}", summary="Moving-average backtest with costs, walk-forward and worst-case drawdown")
async def market_backtest(ticker: str, cost_bps: float = Query(10, ge=0, le=200), slippage_bps: float = Query(5, ge=0, le=200)):
    try:
        return await run_in_threadpool(_backtest, _ticker(ticker), cost_bps, slippage_bps, _ver())
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))


@lru_cache(maxsize=64)
def _time_machine(t: str, entry: float | None, stop: float | None, target: float | None, stop_pct: float | None,
                  target_pct: float | None, side: str, horizon: int, cost_bps: float, lookback: int, ver: tuple) -> dict:
    p = providers.get_prices(t, lookback + horizon + 10)
    last = float(p.df["close"].iloc[-1])
    e = entry or last
    sign = 1 if side == "long" else -1
    if stop is None:
        if stop_pct is None:
            raise ValueError("give a stop price or a stop distance in %")
        stop = e * (1 - sign * stop_pct / 100)
    if target is None:
        if target_pct is None:
            raise ValueError("give a target price or a target distance in %")
        target = e * (1 + sign * target_pct / 100)
    plan = TM.Plan(round(e, 2), round(stop, 2), round(target, 2), side, horizon, cost_bps)
    out = {"ticker": t, **_meta(p), "last_close": round(last, 2),
           "plan": {"entry": plan.entry, "stop": plan.stop, "target": plan.target, "side": side,
                    "horizon_days": horizon, "cost_bps": cost_bps, "entry_from": "you" if entry else "last close"},
           "replays": TM.simulate(TM.build_pool(p.df, lookback), plan),
           "history": TM.history_replay(p.df, plan, lookback)}
    if abs(e / last - 1) > 0.10:
        out["replays"]["notes"].insert(0, f"Your entry is {100 * (e / last - 1):+.0f}% from the last close {last:,.2f}; "
                                          "the replays start at your entry, not today's price.")
    return out


@router.get("/time-machine/{ticker}", summary="Replay a planned trade on the stock's own past days (10,000 simulations plus history)")
async def market_time_machine(ticker: str, entry: float | None = Query(None, gt=0),
                              stop: float | None = Query(None, gt=0), target: float | None = Query(None, gt=0),
                              stop_pct: float | None = Query(None, gt=0, lt=100), target_pct: float | None = Query(None, gt=0, le=500),
                              side: str = Query("long", pattern="^(long|short)$"), horizon: int = Query(10, ge=1, le=120),
                              cost_bps: float = Query(15, ge=0, le=500), lookback: int = Query(500, ge=150, le=1500)):
    try:
        return await run_in_threadpool(_time_machine, _ticker(ticker), entry, stop, target, stop_pct, target_pct,
                                       side, horizon, cost_bps, lookback, _ver())
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class PortfolioIn(BaseModel):
    csv: str


@lru_cache(maxsize=4)
def _proxy_returns(ver: tuple) -> tuple[pd.Series, str]:
    """Market stand-in for betas: NSE index files are not in the store, so use the average of the most liquid stocks."""
    if providers.provider_name() not in providers.STORE_PROVIDERS:
        return providers.get_prices("NIFTY", 700).df["close"].pct_change().dropna(), "synthetic index"
    nifty = providers.index_series("NIFTY 50")
    if nifty is not None:
        return nifty.pct_change().dropna(), "Nifty 50 index"
    rets = {}
    for n in providers.universe(30):
        try:
            rets[n] = providers.get_prices(n, 700).df["close"].pct_change()
        except NoData:
            continue
    return pd.DataFrame(rets).mean(axis=1).dropna(), f"average of the {len(rets)} most liquid stocks (no index file loaded)"


@router.post("/portfolio-risk", summary="Allocation, loss range, correlation and crash scenarios for your holdings")
async def market_portfolio_risk(b: PortfolioIn):
    def go():
        h = PF.parse_holdings(b.csv)
        px = pd.DataFrame({s: providers.get_prices(s, 700).df["close"] for s in h.symbol}).dropna()
        if len(px) < 60:
            raise ValueError("fewer than 60 shared trading days across your holdings")
        prices = {s: float(px[s].iloc[-1]) for s in px}
        alloc = PF.allocation(h, prices)
        rets = px.pct_change().dropna()
        w = pd.Series({p["symbol"]: p["weight"] for p in alloc["positions"]})
        cov = PR.ewma_cov(rets)
        port = (rets[w.index] * w).sum(axis=1)
        v = alloc["total_value"]
        proxy, proxy_name = _proxy_returns(_ver())
        beta = PR.betas(rets, proxy.reindex(rets.index).dropna())
        src = providers.store_source() if providers.provider_name() in providers.STORE_PROVIDERS else "synthetic"
        syn = src in ("synthetic", "fixture")
        return {"synthetic": syn, "source": src, "as_of": str(px.index[-1].date()), "market_proxy": proxy_name,
                "allocation": alloc, "correlation": PF.correlation(rets),
                "week": {"parametric": PR.parametric_range(w, cov, v, 5), "historical": PR.historical_range(port, v, 5)},
                "month": {"parametric": PR.parametric_range(w, cov, v, 21), "historical": PR.historical_range(port, v, 21)},
                "stress": PR.stress(w, beta, v)}
    try:
        return await run_in_threadpool(go)
    except NoData as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ── Fundamentals and news (third-party sources, labelled) ──────────────────────
@router.get("/fundamentals/{ticker}", summary="Company fundamentals (Yahoo Finance), cached a day")
async def fundamentals(ticker: str) -> dict:
    import asyncio

    from backend.data import fundamentals_feed as FF

    t = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9&._-]{1,20}", t):
        raise HTTPException(status_code=422, detail="Not a valid symbol.")
    try:
        return await asyncio.to_thread(FF.fetch_one, t)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Yahoo Finance did not answer ({type(e).__name__}).") from None


@router.get("/news/{ticker}", summary="Recent headlines (Google News) and NSE announcements")
async def stock_news(ticker: str) -> dict:
    import asyncio

    from backend.data import news as N

    t = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9&._-]{1,20}", t):
        raise HTTPException(status_code=422, detail="Not a valid symbol.")
    company = None
    try:
        from backend.data import fundamentals_feed as FF
        company = (await asyncio.to_thread(FF.fetch_one, t)).get("name")
    except Exception:
        pass
    out = {"ticker": t, "news": [], "announcements": [], "errors": []}
    try:
        out["news"] = await asyncio.to_thread(N.news, t, company)
    except Exception as e:
        out["errors"].append(f"News unavailable ({type(e).__name__}).")
    try:
        out["announcements"] = await asyncio.to_thread(N.announcements, t)
    except Exception as e:
        out["errors"].append(f"NSE announcements unavailable ({type(e).__name__}); NSE often blocks cloud servers.")
    return out
