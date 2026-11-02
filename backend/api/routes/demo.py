"""Development-only demo endpoint: ML forecast on synthetic prices.

Registered only when ENVIRONMENT=development. It exists so the dashboards can
be previewed without market data access. Output is NOT a real market forecast.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from ml.forecast.quick_forecast import forecast
from ml.forecast.synthetic import synthetic_ohlcv

router = APIRouter()


@lru_cache(maxsize=256)
def _compute(ticker: str, horizon: int) -> dict:
    df = synthetic_ohlcv(ticker)
    res = forecast(df, horizon)
    candles = [
        {"time": d.strftime("%Y-%m-%d"), "open": r.open, "high": r.high,
         "low": r.low, "close": r.close, "volume": int(r.volume)}
        for d, r in df.tail(260).iterrows()
    ]
    return {"ticker": ticker, "synthetic": True, "candles": candles, **res}


@router.get("/forecast/{ticker}", summary="ML forecast on synthetic prices (dev only)")
async def demo_forecast(ticker: str, horizon: int = Query(10, ge=1, le=30)):
    t = ticker.upper().strip()
    if not t.replace("-", "").replace("&", "").isalnum() or len(t) > 20:
        raise HTTPException(status_code=422, detail="Invalid ticker")
    return await run_in_threadpool(_compute, t, horizon)


@lru_cache(maxsize=8)
def _quotes(tickers: tuple[str, ...]) -> list[dict]:
    from ml.forecast.quick_forecast import build_features

    out = []
    for t in tickers:
        df = synthetic_ohlcv(t, 700)
        c = df["close"]
        rsi = float(build_features(df)["rsi"].iloc[-1] * 100)
        out.append({"ticker": t, "price": float(c.iloc[-1]), "chg": float((c.iloc[-1] / c.iloc[-2] - 1) * 100),
                    "spark": [float(x) for x in c.tail(30)], "rsi": rsi})
    return out


@router.get("/quotes", summary="Synthetic quotes for the demo watchlist (dev only)")
async def demo_quotes(tickers: str = Query(..., max_length=600)):
    names = tuple(t.strip().upper() for t in tickers.split(",") if t.strip())[:60]
    return await run_in_threadpool(_quotes, names)


# ── data-dependent tools on SYNTHETIC prices (dev only) ──────────────────────
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from backend.tools import backtest as BT  # noqa: E402
from backend.tools import portfolio as PF  # noqa: E402
from backend.tools import portrisk as PR  # noqa: E402
from backend.tools import screener as SC  # noqa: E402


@lru_cache(maxsize=1)
def _screen_table() -> list[dict]:
    from ml.forecast.synthetic import synthetic_ohlcv as syn

    names = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "ITC", "MARUTI", "WIPRO", "ONGC", "NTPC", "COALINDIA",
             "HINDUNILVR", "NESTLEIND", "TATASTEEL", "JSWSTEEL", "KOTAKBANK", "AXISBANK", "TECHM", "HCLTECH"]
    t = SC.build_table({n: syn(n, 700) for n in names})
    return t.reset_index(names="symbol").replace({np.nan: None}).to_dict("records")


@router.get("/screener", summary="Screener on synthetic prices (dev only)")
async def demo_screener():
    return await run_in_threadpool(_screen_table)


@lru_cache(maxsize=64)
def _backtest(ticker: str, cost_bps: float, slip_bps: float) -> dict:
    c = synthetic_ohlcv(ticker, 1500)["close"]
    r = BT.run_backtest(c, BT.sma_signal(c, 20, 100), cost_bps, slip_bps)
    hold = BT.run_backtest(c, pd.Series(1.0, index=c.index), cost_bps, slip_bps)
    wf = BT.walk_forward(c, BT.sma_signal, [{"fast": 10, "slow": 50}, {"fast": 20, "slow": 100}, {"fast": 50, "slow": 200}], cost_bps=cost_bps, slippage_bps=slip_bps)
    boot = BT.bootstrap_drawdown(wf["returns"], sims=500)
    step = max(len(r.equity) // 200, 1)
    return {"ticker": ticker, "synthetic": True, "in_sample": r.metrics, "buy_and_hold": hold.metrics,
            "walk_forward_out_of_sample": wf["metrics"], "worst_case_drawdown": boot,
            "equity": [{"time": str(i.date()), "strategy": float(v), "hold": float(hold.equity.loc[i])} for i, v in r.equity.iloc[::step].items()]}


@router.get("/backtest/{ticker}", summary="Backtest with costs on synthetic prices (dev only)")
async def demo_backtest(ticker: str, cost_bps: float = Query(10, ge=0, le=200), slippage_bps: float = Query(5, ge=0, le=200)):
    return await run_in_threadpool(_backtest, ticker.upper()[:20], cost_bps, slippage_bps)


class DemoPortfolioIn(BaseModel):
    csv: str


@router.post("/portfolio-risk", summary="Portfolio allocation and risk on synthetic prices (dev only)")
async def demo_portfolio_risk(b: DemoPortfolioIn):
    def go():
        h = PF.parse_holdings(b.csv)
        px = pd.DataFrame({s: synthetic_ohlcv(s, 700)["close"] for s in h.symbol})
        idx = synthetic_ohlcv("NIFTY", 700)["close"]
        prices = {s: float(px[s].iloc[-1]) for s in px}
        alloc = PF.allocation(h, prices)
        rets = px.pct_change().dropna()
        w = pd.Series({p["symbol"]: p["weight"] for p in alloc["positions"]})
        cov = PR.ewma_cov(rets)
        port = (rets[w.index] * w).sum(axis=1)
        v = alloc["total_value"]
        beta = PR.betas(rets, idx.pct_change().dropna())
        return {"synthetic": True, "allocation": alloc, "correlation": PF.correlation(rets),
                "week": {"parametric": PR.parametric_range(w, cov, v, 5), "historical": PR.historical_range(port, v, 5)},
                "month": {"parametric": PR.parametric_range(w, cov, v, 21), "historical": PR.historical_range(port, v, 21)},
                "stress": PR.stress(w, beta, v)}
    try:
        return await run_in_threadpool(go)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
