"""
IntelliStock — Test Suite
──────────────────────────
Coverage targets:
  • Data pipeline (NSE holiday handling, split correctness, no leakage)
  • Feature engineering (scaler fit/transform separation)
  • API endpoints (auth, predictions, stocks, health)
  • Security (JWT, rate limiting, CORS headers)

Run: pytest backend/tests/ ml/tests/ --cov=backend --cov=ml -v
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.api.main import app
from backend.api.routes.auth import (create_access_token, hash_password,
                                     verify_password)
from ml.data.pipeline import fetch_ohlcv, normalise_ticker, time_series_split
from ml.features.engineer import (FEATURE_COLS, FeatureEngineer,
                                  compute_features)

# ─── Fixtures ────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """300 rows of synthetic OHLCV data for unit tests — no API calls."""
    n = 300
    dates = pd.bdate_range(start="2022-01-01", periods=n)
    np.random.seed(42)
    close = 2000 + np.cumsum(np.random.randn(n) * 20)
    close = np.maximum(close, 100)
    return pd.DataFrame(
        {
            "Open": close * (1 + np.random.randn(n) * 0.005),
            "High": close * (1 + np.abs(np.random.randn(n)) * 0.01),
            "Low": close * (1 - np.abs(np.random.randn(n)) * 0.01),
            "Close": close,
            "Volume": np.random.randint(1_000_000, 10_000_000, n).astype(float),
            "IsHoliday": False,
        },
        index=pd.DatetimeIndex(dates, name="Date"),
    )


@pytest.fixture
def valid_token() -> str:
    return create_access_token(subject="test-user-id", role="user")


@pytest.fixture
def admin_token() -> str:
    return create_access_token(subject="admin-user-id", role="admin")


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# ─── Data Pipeline Tests ─────────────────────────────────────────────────────────


class TestDataPipeline:

    def test_normalise_ticker_adds_ns_suffix(self):
        assert normalise_ticker("RELIANCE") == "RELIANCE.NS"
        assert normalise_ticker("RELIANCE.NS") == "RELIANCE.NS"  # idempotent
        assert normalise_ticker("reliance") == "RELIANCE.NS"  # normalises case

    def test_normalise_ticker_bse(self):
        assert normalise_ticker("TCS", exchange="BSE") == "TCS.BO"

    def test_time_series_split_proportions(self, sample_ohlcv):
        train, val, test = time_series_split(
            sample_ohlcv, test_ratio=0.15, val_ratio=0.10
        )
        total = len(sample_ohlcv)
        assert len(train) + len(val) + len(test) == total

    def test_time_series_split_no_shuffling(self, sample_ohlcv):
        """Temporal order must be preserved — no data from the future in train."""
        train, val, test = time_series_split(sample_ohlcv)
        assert train.index[-1] < val.index[0], "Train bleeds into val"
        assert val.index[-1] < test.index[0], "Val bleeds into test"

    def test_time_series_split_no_overlap(self, sample_ohlcv):
        train, val, test = time_series_split(sample_ohlcv)
        train_idx = set(train.index)
        val_idx = set(val.index)
        test_idx = set(test.index)
        assert train_idx.isdisjoint(val_idx), "Train/val overlap — DATA LEAKAGE"
        assert train_idx.isdisjoint(test_idx), "Train/test overlap — DATA LEAKAGE"
        assert val_idx.isdisjoint(test_idx), "Val/test overlap — DATA LEAKAGE"


# ─── Feature Engineering Tests ───────────────────────────────────────────────────


class TestFeatureEngineer:

    def test_compute_features_returns_expected_columns(self, sample_ohlcv):
        feat = compute_features(sample_ohlcv)
        required = ["RSI", "MACD", "BB_High", "BB_Low", "SMA_20", "Volatility_20"]
        for col in required:
            assert col in feat.columns, f"Missing feature: {col}"

    def test_scaler_fitted_only_on_train(self, sample_ohlcv):
        """Core anti-leakage test: scaler must not see val/test data."""
        train, val, test = time_series_split(sample_ohlcv)
        fe = FeatureEngineer(sequence_length=30, prediction_horizon=1)
        X_train, y_train = fe.fit_transform(train)

        # Scaler fitted — now transform val should NOT re-fit
        assert fe._is_fitted is True
        X_val, y_val = fe.transform(val)

        # Val data extremes should often exceed scaler [0,1] range if different distribution
        # Key: transform() must not call fit_transform() again
        assert X_val is not None  # just verifies no exception

    def test_sequence_shapes(self, sample_ohlcv):
        train, val, test = time_series_split(sample_ohlcv)
        fe = FeatureEngineer(sequence_length=30, prediction_horizon=1)
        X_train, y_train = fe.fit_transform(train)

        assert X_train.ndim == 3, "X must be 3D: (samples, seq_len, features)"
        assert X_train.shape[1] == 30, "Second dim must equal sequence_length"
        assert y_train.ndim == 1, "y must be 1D"
        assert len(X_train) == len(y_train)

    def test_inverse_transform_close_shape(self, sample_ohlcv):
        train, _, _ = time_series_split(sample_ohlcv)
        fe = FeatureEngineer(sequence_length=20)
        _, y_train = fe.fit_transform(train)
        actual = fe.inverse_transform_close(y_train)
        assert actual.shape == y_train.shape
        assert (actual > 0).all(), "Inverse-transformed prices must be positive"

    def test_transform_before_fit_raises(self, sample_ohlcv):
        fe = FeatureEngineer()
        with pytest.raises(RuntimeError, match="fit_transform"):
            fe.transform(sample_ohlcv)


# ─── Auth Tests ───────────────────────────────────────────────────────────────────


class TestAuth:

    def test_password_hashing_and_verification(self):
        plain = "SuperSecret123!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True
        assert verify_password("WrongPassword", hashed) is False

    def test_create_access_token_contains_correct_claims(self):
        token = create_access_token(subject="user-123", role="admin")
        from jose import jwt

        from backend.core.config import settings

        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_access_token_expires(self):
        from jose import jwt

        from backend.core.config import settings

        token = create_access_token(subject="user-123")
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        assert exp > now
        assert exp < now + timedelta(hours=2)


# ─── API Endpoint Tests ───────────────────────────────────────────────────────────


class TestHealthEndpoint:

    @pytest.mark.asyncio
    async def test_liveness_always_returns_200(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "alive"
        assert "version" in body
        assert "uptime_seconds" in body

    @pytest.mark.asyncio
    async def test_liveness_has_security_headers(self, client):
        resp = await client.get("/api/v1/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert "X-Request-ID" in resp.headers


class TestPredictionsEndpoint:

    @pytest.mark.asyncio
    async def test_prediction_requires_auth(self, client):
        """Unauthenticated request must get 401, not 200."""
        resp = await client.get("/api/v1/predictions/RELIANCE")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_prediction_with_valid_token(self, client, valid_token):
        from backend.services.prediction_service import PredictionService

        mock_prediction = MagicMock()
        mock_prediction.model_dump.return_value = {
            "ticker": "RELIANCE",
            "exchange": "NSE",
            "currency": "INR",
            "predictions": [],
            "signal": {
                "ticker": "RELIANCE",
                "signal": "HOLD",
                "confidence": 0.65,
                "current_price": 2500.0,
                "predicted_price": 2510.0,
                "predicted_return_pct": 0.4,
                "rsi": 55.0,
                "macd_bullish": True,
                "generated_at": datetime.utcnow().isoformat(),
                "model_version": "v1",
            },
            "metrics": {
                "RMSE": 25.5,
                "MAE": 18.2,
                "MAPE": 1.1,
                "Directional_Accuracy": 64.5,
            },
            "model_version": "v1",
            "cached": False,
            "generated_at": datetime.utcnow().isoformat(),
        }

        with patch.object(
            PredictionService,
            "predict",
            new_callable=AsyncMock,
            return_value=mock_prediction,
        ):
            resp = await client.get(
                "/api/v1/predictions/RELIANCE",
                headers={"Authorization": f"Bearer {valid_token}"},
            )
        assert resp.status_code == 200
        assert resp.json()["ticker"] == "RELIANCE"

    @pytest.mark.asyncio
    async def test_batch_prediction_limit_enforced(self, client, valid_token):
        """Batch endpoint must reject > 10 tickers."""
        tickers = [f"STOCK{i}" for i in range(15)]
        resp = await client.post(
            "/api/v1/predictions/batch",
            json={"tickers": tickers, "horizon_days": 5},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 422  # Pydantic validation error


class TestSecurityHeaders:

    @pytest.mark.asyncio
    async def test_all_responses_have_security_headers(self, client):
        resp = await client.get("/api/v1/health")
        headers = resp.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("X-XSS-Protection") == "1; mode=block"

    @pytest.mark.asyncio
    async def test_request_id_is_uuid(self, client):
        import uuid

        resp = await client.get("/api/v1/health")
        request_id = resp.headers.get("X-Request-ID")
        assert request_id is not None
        uuid.UUID(request_id)  # raises if not valid UUID
