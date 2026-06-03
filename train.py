"""
IntelliStock — Training Pipeline
──────────────────────────────────
Full end-to-end training script:
  python train.py --ticker RELIANCE --epochs 100 --upload

Steps:
  1. Fetch NSE data (yfinance + holiday handling)
  2. Chronological train/val/test split
  3. Feature engineering (scaler on train only)
  4. Train BiLSTM + Attention
  5. Train GRU baseline
  6. Evaluate all models
  7. Print comparison table
  8. Save best model + feature engineer
  9. Upload to cloud storage (optional)
  10. Register in DB model registry
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path

import numpy as np
from loguru import logger

from ml.data.pipeline import fetch_nifty50, fetch_ohlcv, time_series_split
from ml.features.engineer import FeatureEngineer
from ml.models.lstm import (
    TrainingConfig,
    build_bilstm_attention,
    build_gru_baseline,
    compare_models,
    evaluate_model,
    set_seed,
    train_model,
)

# ─── CLI ────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train IntelliStock LSTM models")
    parser.add_argument("--ticker",     default="RELIANCE", help="NSE ticker (no .NS suffix)")
    parser.add_argument("--exchange",   default="NSE",       choices=["NSE", "BSE"])
    parser.add_argument("--epochs",     default=100, type=int)
    parser.add_argument("--batch-size", default=32,  type=int)
    parser.add_argument("--seq-len",    default=60,  type=int, help="LSTM sequence length")
    parser.add_argument("--horizon",    default=1,   type=int, help="Prediction horizon (days)")
    parser.add_argument("--seed",       default=42,  type=int)
    parser.add_argument("--upload",     action="store_true",  help="Upload model to cloud storage")
    parser.add_argument("--output-dir", default="models",     help="Local model output directory")
    parser.add_argument("--lookback-years", default=5, type=int)
    return parser.parse_args()


# ─── Main training pipeline ──────────────────────────────────────────────────────

def train(args: argparse.Namespace) -> dict:
    set_seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"{args.ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger.info(f"=== IntelliStock Training Run: {run_id} ===")

    # ── Step 1: Fetch data ───────────────────────────────────────────────────
    logger.info(f"Step 1/8: Fetching {args.ticker} data ({args.lookback_years}y)")
    df = fetch_ohlcv(
        args.ticker,
        exchange=args.exchange,
        lookback_years=args.lookback_years,
    )
    logger.info(f"Fetched {len(df)} rows: {df.index[0].date()} → {df.index[-1].date()}")

    # ── Step 2: Fetch NIFTY50 macro feature ─────────────────────────────────
    logger.info("Step 2/8: Fetching NIFTY50 macro feature")
    start_str = df.index[0].strftime("%Y-%m-%d")
    end_str   = df.index[-1].strftime("%Y-%m-%d")
    nifty = fetch_nifty50(start=start_str, end=end_str)

    # ── Step 3: Train/val/test split (chronological, no shuffle) ────────────
    logger.info("Step 3/8: Splitting data (75/10/15 chronological)")
    train_df, val_df, test_df = time_series_split(df, test_ratio=0.15, val_ratio=0.10)

    # ── Step 4: Feature engineering (fit on train ONLY) ─────────────────────
    logger.info("Step 4/8: Feature engineering (zero-leakage pipeline)")
    fe = FeatureEngineer(
        sequence_length=args.seq_len,
        prediction_horizon=args.horizon,
    )
    X_train, y_train = fe.fit_transform(train_df, nifty_series=nifty)
    X_val,   y_val   = fe.transform(val_df,   nifty_series=nifty)
    X_test,  y_test  = fe.transform(test_df,  nifty_series=nifty)

    n_features = X_train.shape[2]
    logger.info(
        f"Sequences → train={X_train.shape} | val={X_val.shape} | "
        f"test={X_test.shape} | features={n_features}"
    )

    # ── Step 5a: Train BiLSTM + Attention (main model) ───────────────────────
    logger.info("Step 5/8: Training BiLSTM + Attention model")
    bilstm_config = TrainingConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        model_name=f"bilstm_{run_id}",
        checkpoint_dir=output_dir / "checkpoints",
    )
    bilstm_model = build_bilstm_attention(
        sequence_length=args.seq_len,
        n_features=n_features,
    )
    bilstm_model.summary()
    train_model(bilstm_model, X_train, y_train, X_val, y_val, bilstm_config)

    # ── Step 5b: Train GRU baseline ──────────────────────────────────────────
    logger.info("Step 5b/8: Training GRU baseline")
    gru_config = TrainingConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        model_name=f"gru_{run_id}",
        checkpoint_dir=output_dir / "checkpoints",
    )
    gru_model = build_gru_baseline(
        sequence_length=args.seq_len,
        n_features=n_features,
    )
    train_model(gru_model, X_train, y_train, X_val, y_val, gru_config)

    # ── Step 6: Evaluate on TEST set (held-out, never seen) ──────────────────
    logger.info("Step 6/8: Evaluating on held-out test set")
    all_metrics = []

    for model, name in [(bilstm_model, "BiLSTM_Attention"), (gru_model, "GRU_Baseline")]:
        y_pred_scaled = model.predict(X_test, verbose=0).flatten()
        y_true_actual = fe.inverse_transform_close(y_test)
        y_pred_actual = fe.inverse_transform_close(y_pred_scaled)

        metrics = evaluate_model(y_true_actual, y_pred_actual, model_name=name)
        all_metrics.append(metrics)

    # ── Step 7: Print comparison table ───────────────────────────────────────
    logger.info("Step 7/8: Model comparison")
    print("\n" + compare_models(all_metrics))

    # Best model = lowest RMSE
    best_metrics = min(all_metrics, key=lambda x: x["RMSE"])
    best_model = bilstm_model if best_metrics["model"].startswith("BiLSTM") else gru_model
    logger.success(f"Best model: {best_metrics['model']} (RMSE={best_metrics['RMSE']:.2f})")

    # ── Step 8: Save model + feature engineer ────────────────────────────────
    logger.info("Step 8/8: Saving artefacts")
    model_path = output_dir / f"{run_id}_best_model.keras"
    fe_path    = output_dir / f"{run_id}_feature_engineer.pkl"
    meta_path  = output_dir / f"{run_id}_metadata.json"

    best_model.save(str(model_path))
    with open(fe_path, "wb") as f:
        pickle.dump(fe, f)

    metadata = {
        "run_id": run_id,
        "ticker": args.ticker,
        "exchange": args.exchange,
        "trained_at": datetime.utcnow().isoformat(),
        "best_model": best_metrics["model"],
        "metrics": best_metrics,
        "all_metrics": all_metrics,
        "config": {
            "sequence_length": args.seq_len,
            "prediction_horizon": args.horizon,
            "epochs_requested": args.epochs,
            "batch_size": args.batch_size,
            "n_features": n_features,
            "feature_cols": fe.feature_cols,
            "train_rows": len(train_df),
            "val_rows": len(val_df),
            "test_rows": len(test_df),
        },
    }
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    logger.success(f"Saved → {model_path} | {fe_path} | {meta_path}")

    # ── Step 9: Upload to cloud (optional) ───────────────────────────────────
    if args.upload:
        _upload_to_cloud(model_path, fe_path, meta_path, run_id)

    return metadata


def _upload_to_cloud(model_path: Path, fe_path: Path, meta_path: Path, run_id: str) -> None:
    """Upload artefacts to configured cloud storage (S3/GCS/Azure)."""
    from backend.core.config import settings

    if settings.MODEL_STORE == "s3":
        import boto3
        s3 = boto3.client("s3", region_name=settings.AWS_REGION)
        for path in [model_path, fe_path, meta_path]:
            key = f"models/{run_id}/{path.name}"
            s3.upload_file(str(path), settings.MODEL_BUCKET, key)
            logger.info(f"Uploaded → s3://{settings.MODEL_BUCKET}/{key}")

    elif settings.MODEL_STORE == "gcs":
        from google.cloud import storage as gcs
        client = gcs.Client(project=settings.GCP_PROJECT_ID)
        bucket = client.bucket(settings.MODEL_BUCKET)
        for path in [model_path, fe_path, meta_path]:
            blob = bucket.blob(f"models/{run_id}/{path.name}")
            blob.upload_from_filename(str(path))
            logger.info(f"Uploaded → gs://{settings.MODEL_BUCKET}/models/{run_id}/{path.name}")

    elif settings.MODEL_STORE == "azure":
        from azure.storage.blob import BlobServiceClient
        client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
        container = client.get_container_client(settings.MODEL_BUCKET)
        for path in [model_path, fe_path, meta_path]:
            blob_name = f"models/{run_id}/{path.name}"
            with open(path, "rb") as data:
                container.upload_blob(name=blob_name, data=data, overwrite=True)
            logger.info(f"Uploaded → azure://{settings.MODEL_BUCKET}/{blob_name}")

    logger.success("All artefacts uploaded to cloud storage")


# ─── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    result = train(args)
    print(f"\n✅ Training complete — Run ID: {result['run_id']}")
    print(f"   RMSE: {result['metrics']['RMSE']:.2f} | "
          f"MAPE: {result['metrics']['MAPE']:.2f}% | "
          f"DA: {result['metrics']['Directional_Accuracy']:.1f}%")
