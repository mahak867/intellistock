"""
IntelliStock — Stocks API
──────────────────────────
• GET /stocks/search              — search NSE/BSE tickers by name
• GET /stocks/nifty50             — full NIFTY50 constituents list
• GET /stocks/{ticker}            — stock metadata + fundamentals
• GET /stocks/{ticker}/ohlcv      — historical OHLCV + indicators
• GET /stocks/{ticker}/indicators — just the technical indicators
• POST /stocks/watchlist          — add to user watchlist
• DELETE /stocks/watchlist/{id}   — remove from watchlist
• GET /stocks/watchlist           — get user's watchlist
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel

from backend.api.routes.auth import get_current_user
from backend.core.config import settings
from ml.data.pipeline import NIFTY50_TICKERS, fetch_ohlcv
from ml.features.engineer import FEATURE_COLS, compute_features

router = APIRouter()


# ─── Schemas ────────────────────────────────────────────────────────────────────


class WatchlistAddRequest(BaseModel):
    ticker: str
    exchange: str = "NSE"
    notes: str | None = None


class OHLCVResponse(BaseModel):
    ticker: str
    exchange: str
    currency: str = "INR"
    days: int
    data: list[dict]
    cached: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────────────────


async def _cached_ohlcv(ticker: str, days: int) -> list[dict]:
    """Fetch OHLCV, compute indicators, return as list of dicts. Redis-cached."""
    import hashlib
    import json

    from backend.core.redis_client import get_redis_client

    cache_key = f"ohlcv:{ticker}:{days}"
    redis = await get_redis_client()
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    df = fetch_ohlcv(ticker, lookback_years=max(1, days // 252 + 1))
    df = df.tail(days)
    feat = compute_features(df)

    # Select useful columns for the response
    cols = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "RSI",
        "MACD",
        "MACD_Signal",
        "BB_High",
        "BB_Low",
        "SMA_20",
        "SMA_50",
        "EMA_12",
        "Volatility_20",
    ]
    available = [c for c in cols if c in feat.columns]
    result = feat[available].reset_index().rename(columns={"Date": "date"})
    result["date"] = result["date"].astype(str)
    records = result.to_dict(orient="records")

    await redis.setex(cache_key, settings.CACHE_TTL_SECONDS, json.dumps(records))
    return records


# ─── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/nifty50", summary="NIFTY50 constituent tickers")
async def get_nifty50(current_user: dict = Depends(get_current_user)) -> dict:
    return {
        "tickers": NIFTY50_TICKERS,
        "count": len(NIFTY50_TICKERS),
        "exchange": "NSE",
        "index": "NIFTY50",
    }


@router.get("/search", summary="Search tickers by name or symbol")
async def search_stocks(
    q: Annotated[str, Query(min_length=1, max_length=50)],
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Simple symbol + name search against our metadata table.
    Falls back to substring match on NIFTY50 list if DB has no results.
    """
    from backend.services.stock_service import StockService

    q_upper = q.upper()
    results = await StockService.search(q_upper)

    # Fallback: match NIFTY50 tickers directly
    if not results:
        results = [
            {"ticker": t, "company_name": t, "exchange": "NSE", "is_nifty50": True}
            for t in NIFTY50_TICKERS
            if q_upper in t
        ]

    return {"query": q, "results": results[:20]}


@router.get("/{ticker}", summary="Stock metadata and fundamentals")
async def get_stock_info(
    ticker: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Returns company name, sector, market cap, P/E, EPS, dividend yield."""
    from backend.services.stock_service import StockService

    ticker = ticker.upper()
    info = await StockService.get_metadata(ticker)
    if not info:
        # Try fetching from yfinance and cache
        try:
            info = await StockService.fetch_and_cache_metadata(ticker)
        except Exception as exc:
            logger.warning(f"Metadata fetch failed for {ticker}: {exc}")
            raise HTTPException(status_code=404, detail=f"Stock {ticker} not found")
    return info


@router.get(
    "/{ticker}/ohlcv",
    response_model=OHLCVResponse,
    summary="Historical OHLCV + indicators",
)
async def get_ohlcv(
    ticker: str,
    days: Annotated[int, Query(ge=7, le=1825)] = 90,
    current_user: dict = Depends(get_current_user),
) -> OHLCVResponse:
    """
    Returns OHLCV data with pre-computed technical indicators.
    Max 1825 days (5 years). Cached for 5 minutes.
    """
    ticker = ticker.upper()
    try:
        data = await _cached_ohlcv(ticker, days)
    except Exception as exc:
        logger.error(f"OHLCV fetch failed for {ticker}: {exc}")
        raise HTTPException(
            status_code=500, detail="Market data temporarily unavailable"
        )

    if not data:
        raise HTTPException(status_code=404, detail=f"No data found for {ticker}")

    return OHLCVResponse(ticker=ticker, exchange="NSE", days=days, data=data)


@router.get("/{ticker}/indicators", summary="Latest technical indicator values")
async def get_indicators(
    ticker: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Returns only the latest row of indicators — lightweight for signal dashboards."""
    ticker = ticker.upper()
    try:
        data = await _cached_ohlcv(ticker, 60)  # need 60 days for warm-up
        if not data:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}")
        latest = data[-1]
        return {"ticker": ticker, "date": latest.get("date"), "indicators": latest}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Watchlist ────────────────────────────────────────────────────────────────────


@router.post(
    "/watchlist", status_code=status.HTTP_201_CREATED, summary="Add ticker to watchlist"
)
async def add_to_watchlist(
    payload: WatchlistAddRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    from backend.services.stock_service import StockService

    item = await StockService.add_watchlist(
        user_id=current_user["sub"],
        ticker=payload.ticker.upper(),
        exchange=payload.exchange,
        notes=payload.notes,
    )
    return {"message": "Added to watchlist", "id": str(item.id)}


@router.get("/watchlist", summary="Get user's watchlist")
async def get_watchlist(current_user: dict = Depends(get_current_user)) -> dict:
    from backend.services.stock_service import StockService

    items = await StockService.get_watchlist(user_id=current_user["sub"])
    return {"watchlist": items, "count": len(items)}


@router.delete(
    "/watchlist/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove from watchlist",
)
async def remove_from_watchlist(
    item_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    from backend.services.stock_service import StockService

    deleted = await StockService.remove_watchlist(
        item_id=item_id, user_id=current_user["sub"]
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
