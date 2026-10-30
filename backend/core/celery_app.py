"""
IntelliStock - Celery app.

Worker:  celery -A backend.core.celery_app worker --loglevel=info
Beat:    celery -A backend.core.celery_app beat --loglevel=info

Beat schedules `retrain_models` every RETRAIN_INTERVAL_HOURS (default 24).
Tickers to retrain come from the RETRAIN_TICKERS env var (comma separated,
default RELIANCE).
"""

from __future__ import annotations

import argparse
import os

from celery import Celery
from loguru import logger

from backend.core.config import settings

celery_app = Celery(
    "intellistock",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "retrain-models": {
            "task": "backend.core.celery_app.retrain_models",
            "schedule": settings.RETRAIN_INTERVAL_HOURS * 3600,
        },
    },
)


def _tickers() -> list[str]:
    raw = os.getenv("RETRAIN_TICKERS", "RELIANCE")
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


@celery_app.task(name="backend.core.celery_app.retrain_model", bind=True)
def retrain_model(self, ticker: str, epochs: int = 50) -> dict:
    """Retrain one ticker via train.train() and return its result."""
    # Imported here so the worker boots without loading TensorFlow until needed.
    from train import train

    args = argparse.Namespace(
        ticker=ticker,
        exchange="NSE",
        epochs=epochs,
        batch_size=32,
        seq_len=60,
        horizon=1,
        seed=42,
        upload=False,
        output_dir="models",
        lookback_years=5,
    )
    logger.info(f"Retraining {ticker} ({epochs} epochs)")
    return train(args)


@celery_app.task(name="backend.core.celery_app.retrain_models")
def retrain_models() -> list[str]:
    """Scheduled entry point: queue one retrain task per configured ticker."""
    tickers = _tickers()
    for t in tickers:
        retrain_model.delay(t)
    return tickers
