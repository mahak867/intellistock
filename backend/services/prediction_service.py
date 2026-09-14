"""
IntelliStock — Prediction Service
─────────────────────────────────────
Runs inference with the in-memory model loaded by ModelService, and
assembles the API response (forecast points + BUY/SELL/HOLD signal).

NOTE — MVP simplification: the model is trained for a single-step
(next trading day) horizon. For `horizon_days` > 1 we repeat the
single-step forecast across the requested horizon and widen the
confidence interval linearly with distance, rather than re-feeding
predictions autoregressively through all 31 engineered features
(which would require simulating future OHLCV, not just price).
This is flagged clearly in the API docstring and the project report —
a true multi-step model is listed as future work.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from backend.services.model_service import ModelService
from backend.core.database import get_session
from backend.models.db_models import PredictionLog
from ml.data.pipeline import fetch_nifty50, fetch_ohlcv
from ml.features.engineer import compute_features, generate_signal


class PredictionService:
    """Generates price forecasts + trading signals for a given ticker."""

    @staticmethod
    async def predict(ticker: str, horizon_days: int = 5, user_id: str | None = None):
        # Imported here (not at module level) to avoid a circular import,
        # since predictions.py imports this service inside its route bodies.
        from backend.api.routes.predictions import (
            PredictionPoint,
            PredictionResponse,
            SignalResponse,
        )

        entry = ModelService.get(ticker)
        if entry is None:
            raise ValueError(
                f"No trained model available for {ticker} — "
                f"run `python train.py --ticker {ticker}` first"
            )

        model, fe, meta = entry["model"], entry["fe"], entry["meta"]

        # ── Recent data (enough for feature warm-up + one sequence window) ──
        df = fetch_ohlcv(ticker, lookback_years=1)
        start_str = df.index[0].strftime("%Y-%m-%d")
        end_str = df.index[-1].strftime("%Y-%m-%d")
        nifty = fetch_nifty50(start=start_str, end=end_str)

        X, _y = fe.transform(df, nifty_series=nifty)
        if len(X) == 0:
            raise ValueError(f"Not enough recent data to build a sequence for {ticker}")

        last_seq = X[-1:]  # most recent 60-day window
        y_pred_scaled = model.predict(last_seq, verbose=0).flatten()
        predicted_close = float(fe.inverse_transform_close(y_pred_scaled)[0])

        current_price = float(df["Close"].iloc[-1])
        rmse = float(meta["metrics"]["RMSE"])

        # ── Multi-day forecast (see MVP note in module docstring) ──────────
        today = datetime.now(timezone.utc)
        predictions = []
        for d in range(1, horizon_days + 1):
            spread = rmse * np.sqrt(d)  # widen CI with distance
            predictions.append(
                PredictionPoint(
                    date=(today + timedelta(days=d)).strftime("%Y-%m-%d"),
                    predicted_close=round(predicted_close, 2),
                    lower_bound=round(predicted_close - 1.645 * spread, 2),
                    upper_bound=round(predicted_close + 1.645 * spread, 2),
                )
            )

        # ── Signal (RSI + MACD confirmation on latest indicators) ──────────
        feat = compute_features(df).dropna().iloc[-1]
        sig = generate_signal(
            predicted_price=predicted_close,
            current_price=current_price,
            rsi=float(feat["RSI"]),
            macd=float(feat["MACD"]),
            macd_signal=float(feat["MACD_Signal"]),
        )

        signal = SignalResponse(
            ticker=ticker,
            signal=sig["signal"],
            confidence=sig["confidence"],
            current_price=sig["current_price"],
            predicted_price=sig["predicted_price"],
            predicted_return_pct=sig["predicted_return_pct"],
            rsi=sig["rsi"],
            macd_bullish=sig["macd_bullish"],
            generated_at=today,
            model_version=meta["run_id"],
        )

        target_date = today + timedelta(days=1)
        await PredictionService._log_prediction(
            ticker=ticker,
            model_version=meta["run_id"],
            predicted_close=predicted_close,
            signal=sig["signal"],
            confidence=sig["confidence"],
            rmse=rmse,
            user_id=user_id,
            target_date=target_date,
        )

        return PredictionResponse(
            ticker=ticker,
            predictions=predictions,
            signal=signal,
            metrics=meta["metrics"],
            model_version=meta["run_id"],
            cached=False,
            generated_at=today,
        )

    @staticmethod
    async def _log_prediction(
        ticker: str,
        model_version: str,
        predicted_close: float,
        signal: str,
        confidence: float,
        rmse: float,
        user_id: str | None,
        target_date: datetime,
    ) -> None:
        """Persist every prediction to prediction_logs for later backtesting."""
        async with get_session() as session:
            log = PredictionLog(
                user_id=user_id,
                ticker=ticker,
                model_version=model_version,
                prediction_date=datetime.now(timezone.utc),
                target_date=target_date,
                predicted_close=predicted_close,
                signal=signal,
                confidence=confidence,
                rmse_at_time=rmse,
            )
            session.add(log)
            await session.flush()

    @staticmethod
    async def get_prediction_history(ticker: str, days: int = 30) -> list[dict]:
        """
        Return the last `days` days of logged predictions for a ticker,
        newest first — used by the backtesting dashboard. Rows where
        actual_close hasn't been backfilled yet (no nightly job wired up
        in this MVP) simply show null accuracy fields.
        """
        from sqlalchemy import select

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with get_session() as session:
            result = await session.execute(
                select(PredictionLog)
                .where(PredictionLog.ticker == ticker, PredictionLog.created_at >= cutoff)
                .order_by(PredictionLog.created_at.desc())
            )
            rows = result.scalars().all()
            return [
                {
                    "prediction_date": r.prediction_date.isoformat(),
                    "target_date": r.target_date.isoformat(),
                    "predicted_close": r.predicted_close,
                    "actual_close": r.actual_close,
                    "signal": r.signal,
                    "confidence": r.confidence,
                    "absolute_error": r.absolute_error,
                    "pct_error": r.pct_error,
                    "direction_correct": r.direction_correct,
                }
                for r in rows
            ]
