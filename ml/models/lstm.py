"""
IntelliStock — Model Architecture
───────────────────────────────────
• Bidirectional LSTM + Attention mechanism
• GRU baseline for comparison
• Production callbacks: EarlyStopping, ReduceLR, ModelCheckpoint
• Full metrics: RMSE, MAE, MAPE, Directional Accuracy
• Model versioning + serialisation to cloud storage
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import tensorflow as tf
from loguru import logger
from sklearn.metrics import mean_absolute_error, mean_squared_error
from tensorflow import keras
from tensorflow.keras import layers, regularizers


# ─── Reproducibility ────────────────────────────────────────────────────────────

def set_seed(seed: int = 42) -> None:
    tf.random.set_seed(seed)
    np.random.seed(seed)


# ─── Attention Layer ─────────────────────────────────────────────────────────────

class BahdanauAttention(layers.Layer):
    """
    Bahdanau (additive) attention for sequence models.
    Allows the model to focus on the most informative time steps.
    """

    def __init__(self, units: int = 64, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.W = layers.Dense(units)
        self.V = layers.Dense(1)

    def call(self, lstm_output: tf.Tensor) -> tf.Tensor:
        # lstm_output: (batch, seq_len, features)
        score = self.V(tf.nn.tanh(self.W(lstm_output)))  # (batch, seq_len, 1)
        weights = tf.nn.softmax(score, axis=1)            # (batch, seq_len, 1)
        context = weights * lstm_output                   # (batch, seq_len, features)
        return tf.reduce_sum(context, axis=1)             # (batch, features)

    def get_config(self) -> dict:
        config = super().get_config()
        config.update({"units": self.W.units})
        return config


# ─── Model factory ───────────────────────────────────────────────────────────────

def build_bilstm_attention(
    sequence_length: int,
    n_features: int,
    lstm_units: list[int] | None = None,
    attention_units: int = 64,
    dense_units: list[int] | None = None,
    dropout_rate: float = 0.3,
    recurrent_dropout: float = 0.1,
    l2_reg: float = 1e-4,
    learning_rate: float = 1e-3,
) -> keras.Model:
    """
    Production BiLSTM + Attention model.

    Architecture:
        Input → BiLSTM × 2 → BahdanauAttention → Dense × 2 → Output (1)

    Regularisation:
        - Dropout on LSTM output
        - Recurrent dropout inside LSTM cells
        - L2 weight regularisation on Dense layers
        - Batch Normalisation between dense layers
    """
    lstm_units = lstm_units or [128, 64]
    dense_units = dense_units or [64, 32]

    inp = keras.Input(shape=(sequence_length, n_features), name="sequence_input")

    # ── BiLSTM stack ─────────────────────────────────────────────────────────
    x = inp
    for i, units in enumerate(lstm_units):
        return_seq = i < len(lstm_units) - 1  # all but last return sequences
        x = layers.Bidirectional(
            layers.LSTM(
                units,
                return_sequences=True,              # always True — attention needs it
                dropout=dropout_rate,
                recurrent_dropout=recurrent_dropout,
                kernel_regularizer=regularizers.L2(l2_reg),
                name=f"lstm_{i}",
            ),
            name=f"bilstm_{i}",
        )(x)
        x = layers.BatchNormalization(name=f"bn_lstm_{i}")(x)

    # ── Attention ────────────────────────────────────────────────────────────
    x = BahdanauAttention(units=attention_units, name="attention")(x)
    x = layers.Dropout(dropout_rate, name="attention_dropout")(x)

    # ── Dense head ───────────────────────────────────────────────────────────
    for i, units in enumerate(dense_units):
        x = layers.Dense(
            units,
            activation="relu",
            kernel_regularizer=regularizers.L2(l2_reg),
            name=f"dense_{i}",
        )(x)
        x = layers.BatchNormalization(name=f"bn_dense_{i}")(x)
        x = layers.Dropout(dropout_rate / 2, name=f"dense_dropout_{i}")(x)

    out = layers.Dense(1, name="price_output")(x)

    model = keras.Model(inputs=inp, outputs=out, name="IntelliStock_BiLSTM_Attention")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate, clipnorm=1.0),
        loss="huber",   # robust to outliers vs MSE
        metrics=["mae"],
    )
    return model


def build_gru_baseline(
    sequence_length: int,
    n_features: int,
    gru_units: list[int] | None = None,
    dropout_rate: float = 0.3,
    learning_rate: float = 1e-3,
) -> keras.Model:
    """GRU baseline for ablation / comparison table in report."""
    gru_units = gru_units or [128, 64]

    inp = keras.Input(shape=(sequence_length, n_features), name="sequence_input")
    x = inp
    for i, units in enumerate(gru_units):
        return_seq = i < len(gru_units) - 1
        x = layers.GRU(units, return_sequences=return_seq, dropout=dropout_rate)(x)
        x = layers.BatchNormalization()(x)

    x = layers.Dense(32, activation="relu")(x)
    out = layers.Dense(1)(x)

    model = keras.Model(inputs=inp, outputs=out, name="IntelliStock_GRU")
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=learning_rate, clipnorm=1.0),
        loss="huber",
        metrics=["mae"],
    )
    return model


# ─── Training pipeline ───────────────────────────────────────────────────────────

@dataclass
class TrainingConfig:
    epochs: int = 100
    batch_size: int = 32
    patience: int = 15          # EarlyStopping patience
    lr_patience: int = 7        # ReduceLROnPlateau patience
    lr_factor: float = 0.5
    min_lr: float = 1e-6
    checkpoint_dir: Path = field(default_factory=lambda: Path("models/checkpoints"))
    model_name: str = "bilstm_attention"


def get_callbacks(config: TrainingConfig) -> list[keras.callbacks.Callback]:
    config.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = config.checkpoint_dir / f"{config.model_name}_best.keras"

    return [
        keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=config.patience,
            restore_best_weights=True,
            verbose=1,
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=config.lr_factor,
            patience=config.lr_patience,
            min_lr=config.min_lr,
            verbose=1,
        ),
        keras.callbacks.ModelCheckpoint(
            filepath=str(checkpoint_path),
            monitor="val_loss",
            save_best_only=True,
            verbose=1,
        ),
        keras.callbacks.TensorBoard(
            log_dir=f"logs/{config.model_name}_{int(time.time())}",
            histogram_freq=1,
        ),
        keras.callbacks.TerminateOnNaN(),
    ]


def train_model(
    model: keras.Model,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    config: TrainingConfig,
) -> keras.callbacks.History:
    """Train with full callback suite and class-weight-free pipeline."""
    logger.info(
        f"Training {model.name} | "
        f"train={X_train.shape} | val={X_val.shape} | "
        f"epochs={config.epochs} | batch={config.batch_size}"
    )
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=config.epochs,
        batch_size=config.batch_size,
        callbacks=get_callbacks(config),
        verbose=1,
        shuffle=False,   # CRITICAL: never shuffle time series
    )
    return history


# ─── Evaluation metrics ──────────────────────────────────────────────────────────


def evaluate_model(
    y_true_actual: np.ndarray,
    y_pred_actual: np.ndarray,
    model_name: str = "model",
) -> dict[str, float]:
    """
    Compute full evaluation suite on actual (inverse-transformed) prices.

    Metrics:
        RMSE  — Root Mean Square Error (₹)
        MAE   — Mean Absolute Error (₹)
        MAPE  — Mean Absolute Percentage Error (%)
        DA    — Directional Accuracy (% of correct up/down moves)
    """
    rmse = float(np.sqrt(mean_squared_error(y_true_actual, y_pred_actual)))
    mae = float(mean_absolute_error(y_true_actual, y_pred_actual))

    # MAPE — guard against zero true values
    mape = float(
        np.mean(np.abs((y_true_actual - y_pred_actual) / (np.abs(y_true_actual) + 1e-10))) * 100
    )

    # Directional accuracy
    true_dir = np.sign(np.diff(y_true_actual))
    pred_dir = np.sign(np.diff(y_pred_actual))
    da = float(np.mean(true_dir == pred_dir) * 100)

    metrics = {
        "model": model_name,
        "RMSE": round(rmse, 4),
        "MAE": round(mae, 4),
        "MAPE": round(mape, 4),
        "Directional_Accuracy": round(da, 2),
        "n_samples": len(y_true_actual),
    }

    logger.info(
        f"[{model_name}] RMSE={rmse:.2f} | MAE={mae:.2f} | "
        f"MAPE={mape:.2f}% | DA={da:.1f}%"
    )
    return metrics


def compare_models(results: list[dict]) -> str:
    """Return a formatted comparison table for all trained models."""
    header = f"{'Model':<35} {'RMSE':>8} {'MAE':>8} {'MAPE':>8} {'DA %':>8}"
    sep = "-" * len(header)
    rows = [header, sep]
    for r in sorted(results, key=lambda x: x["RMSE"]):
        rows.append(
            f"{r['model']:<35} {r['RMSE']:>8.2f} {r['MAE']:>8.2f} "
            f"{r['MAPE']:>7.2f}% {r['Directional_Accuracy']:>7.1f}%"
        )
    return "\n".join(rows)
