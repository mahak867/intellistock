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
