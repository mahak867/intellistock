"""
IntelliStock — Predictions API
────────────────────────────────
• GET /predictions/{ticker}         — predict next N days for a ticker
• GET /predictions/{ticker}/signal  — BUY/SELL/HOLD signal
• GET /predictions/batch            — multiple tickers in one call
• GET /predictions/{ticker}/history — historical prediction accuracy log

All responses are Redis-cached. Cache is invalidated on model retrain.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.api.routes.auth import get_current_user
from backend.core.config import settings

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


# ─── Response schemas ────────────────────────────────────────────────────────────


class PredictionPoint(BaseModel):
    date: str
    predicted_close: float
    lower_bound: float     # 90% confidence interval
    upper_bound: float


class SignalResponse(BaseModel):
    ticker: str
    signal: str            # BUY | SELL | HOLD
    confidence: float
    current_price: float
    predicted_price: float
    predicted_return_pct: float
    rsi: float
    macd_bullish: bool
    generated_at: datetime
    model_version: str


class PredictionResponse(BaseModel):
    ticker: str
    exchange: str = "NSE"
    currency: str = "INR"
    predictions: list[PredictionPoint]
    signal: SignalResponse
    metrics: dict          # RMSE, MAE, MAPE, DA from last evaluation
    model_version: str
    cached: bool = False
    generated_at: datetime


class BatchPredictionRequest(BaseModel):
    tickers: list[str] = Field(max_length=10, description="Max 10 tickers per batch call")
    horizon_days: int = Field(default=5, ge=1, le=30)


# ─── Cache helpers ───────────────────────────────────────────────────────────────


async def _get_from_cache(key: str) -> dict | None:
    from backend.core.redis_client import get_redis_client
    redis = await get_redis_client()
    raw = await redis.get(key)
    if raw:
        return json.loads(raw)
    return None


async def _set_cache(key: str, value: dict, ttl: int = settings.PREDICTION_CACHE_TTL) -> None:
    from backend.core.redis_client import get_redis_client
    redis = await get_redis_client()
    await redis.setex(key, ttl, json.dumps(value, default=str))


# ─── Routes ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{ticker}",
    response_model=PredictionResponse,
    summary="Predict stock prices for next N days",
)
@limiter.limit("30/minute")
async def predict_ticker(
    ticker: str,
    horizon_days: Annotated[int, Query(ge=1, le=30)] = 5,
    current_user: dict = Depends(get_current_user),
) -> PredictionResponse:
    """
    Generate LSTM price forecasts for the given NSE ticker.

    - Ticker format: RELIANCE, TCS, INFY (no .NS suffix needed)
    - Predictions include 90% confidence interval
    - Results cached for 15 minutes
    - Requires Bearer token authentication
    """
    ticker = ticker.upper().strip()
    cache_key = f"prediction:{ticker}:{horizon_days}"

    # ── Cache hit ────────────────────────────────────────────────────────────
    cached = await _get_from_cache(cache_key)
    if cached:
        cached["cached"] = True
        logger.debug(f"Cache hit: {cache_key}")
        return PredictionResponse(**cached)

    # ── Run inference ────────────────────────────────────────────────────────
    from backend.services.prediction_service import PredictionService

    try:
        result = await PredictionService.predict(ticker=ticker, horizon_days=horizon_days)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error(f"Prediction failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Prediction service temporarily unavailable")

    # ── Cache write ──────────────────────────────────────────────────────────
    await _set_cache(cache_key, result.model_dump())

    return result


@router.get(
    "/{ticker}/signal",
    response_model=SignalResponse,
    summary="Get BUY/SELL/HOLD trading signal",
)
@limiter.limit("60/minute")
async def get_signal(
    ticker: str,
    current_user: dict = Depends(get_current_user),
) -> SignalResponse:
    """
    Returns a trading signal (BUY/SELL/HOLD) combining:
    - LSTM price direction prediction
    - RSI overbought/oversold zones
    - MACD crossover confirmation
    """
    ticker = ticker.upper().strip()
    cache_key = f"signal:{ticker}"

    cached = await _get_from_cache(cache_key)
    if cached:
        return SignalResponse(**cached)

    from backend.services.prediction_service import PredictionService
    try:
        prediction = await PredictionService.predict(ticker=ticker, horizon_days=1)
        signal = prediction.signal
    except Exception as e:
        logger.error(f"Signal generation failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Signal service unavailable")

    await _set_cache(cache_key, signal.model_dump(), ttl=300)
    return signal


@router.post(
    "/batch",
    response_model=list[PredictionResponse],
    summary="Batch predict up to 10 tickers",
)
@limiter.limit("10/minute")
async def batch_predict(
    payload: BatchPredictionRequest,
    current_user: dict = Depends(get_current_user),
) -> list[PredictionResponse]:
    """
    Batch prediction endpoint — max 10 tickers per request.
    Failed tickers are skipped with a warning, not 500'd.
    Rate limited to 10 batch calls per minute.
    """
    from backend.services.prediction_service import PredictionService
    import asyncio

    async def safe_predict(ticker: str) -> PredictionResponse | None:
        try:
            return await PredictionService.predict(ticker=ticker, horizon_days=payload.horizon_days)
        except Exception as exc:
            logger.warning(f"Batch prediction skipped {ticker}: {exc}")
            return None

    results = await asyncio.gather(*[safe_predict(t) for t in payload.tickers])
    return [r for r in results if r is not None]


@router.get(
    "/{ticker}/history",
    summary="Historical prediction accuracy log",
)
async def prediction_history(
    ticker: str,
    days: Annotated[int, Query(ge=7, le=180)] = 30,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Returns the last N days of prediction vs actual prices for auditing.
    Used by the backtesting dashboard.
    """
    from backend.services.prediction_service import PredictionService
    ticker = ticker.upper().strip()
    try:
        history = await PredictionService.get_prediction_history(ticker=ticker, days=days)
        return {"ticker": ticker, "history": history, "days": days}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
