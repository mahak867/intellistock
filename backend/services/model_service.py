"""
IntelliStock — Model Service
────────────────────────────────
Loads trained model artefacts (produced by train.py) into memory at
startup, and serves them to PredictionService for inference.

Expects, per run, three files in `models/` (see train.py Step 8):
    {run_id}_best_model.keras
    {run_id}_feature_engineer.pkl
    {run_id}_metadata.json

The most recently trained run for a given ticker is treated as active.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from loguru import logger

MODEL_DIR = Path("models")

# In-memory registry: {ticker: {"model": keras.Model, "fe": FeatureEngineer, "meta": dict}}
_LOADED_MODELS: dict[str, dict[str, Any]] = {}


class ModelService:
    """Loads/serves trained BiLSTM/GRU models for inference."""

    @classmethod
    async def load_all_models(cls) -> None:
        """
        Scan the local model directory for trained artefacts and load the
        latest run per ticker into memory. Safe to call with an empty/missing
        directory — the API still starts, predictions just 404 until a model
        is trained and dropped into `models/`.
        """
        if not MODEL_DIR.exists():
            logger.warning(
                f"Model directory {MODEL_DIR} not found — "
                "run `python train.py --ticker <TICKER>` first. "
                "API will start but predictions will be unavailable."
            )
            return

        meta_files = sorted(MODEL_DIR.glob("*_metadata.json"))
        latest_by_ticker: dict[str, Path] = {}
        for meta_path in meta_files:
            try:
                meta = json.loads(meta_path.read_text())
            except Exception as exc:
                logger.warning(f"Could not parse {meta_path}: {exc}")
                continue
            ticker = meta.get("ticker")
            if not ticker:
                continue
            # glob is sorted lexicographically → run_id timestamp suffix means
            # the last one wins, so this naturally keeps the latest run.
            latest_by_ticker[ticker] = meta_path

        for ticker, meta_path in latest_by_ticker.items():
            try:
                cls._load_one(ticker, meta_path)
            except Exception as exc:
                logger.error(f"Failed to load model for {ticker}: {exc}")

        logger.info(
            f"ModelService: loaded {len(_LOADED_MODELS)} model(s) → "
            f"{list(_LOADED_MODELS.keys())}"
        )

    @classmethod
    def _load_one(cls, ticker: str, meta_path: Path) -> None:
        import tensorflow as tf

        meta = json.loads(meta_path.read_text())
        run_id = meta["run_id"]

        model_path = MODEL_DIR / f"{run_id}_best_model.keras"
        fe_path = MODEL_DIR / f"{run_id}_feature_engineer.pkl"

        if not model_path.exists() or not fe_path.exists():
            raise FileNotFoundError(f"Missing artefacts for run {run_id}")

        # Custom layer must be registered for Keras to deserialise it.
        from ml.models.lstm import BahdanauAttention

        model = tf.keras.models.load_model(
            str(model_path),
            custom_objects={"BahdanauAttention": BahdanauAttention},
        )
        with open(fe_path, "rb") as f:
            fe = pickle.load(f)

        _LOADED_MODELS[ticker] = {"model": model, "fe": fe, "meta": meta}
        logger.info(f"Loaded model for {ticker} (run={run_id}, RMSE={meta['metrics']['RMSE']})")

    @classmethod
    def get(cls, ticker: str) -> dict[str, Any] | None:
        """Return {"model", "fe", "meta"} for a ticker, or None if not loaded."""
        return _LOADED_MODELS.get(ticker.upper())

    @classmethod
    def get_status(cls) -> dict:
        if _LOADED_MODELS:
            return {
                "status": "loaded",
                "tickers": list(_LOADED_MODELS.keys()),
                "count": len(_LOADED_MODELS),
            }
        return {
            "status": "empty",
            "detail": "No trained models loaded — run train.py first",
        }

    @classmethod
    def get_all_model_versions(cls) -> list[dict]:
        return [
            {
                "ticker": ticker,
                "model_version": entry["meta"]["run_id"],
                "architecture": entry["meta"]["best_model"],
                "metrics": entry["meta"]["metrics"],
                "trained_at": entry["meta"]["trained_at"],
            }
            for ticker, entry in _LOADED_MODELS.items()
        ]
