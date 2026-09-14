"""
Security regression tests — each test here corresponds to a real gap found
during an explicit security audit, not a hypothetical. Kept separate from
test_suite.py so the security-specific intent is easy to find and extend.
"""

from __future__ import annotations

import pytest
from passlib.context import CryptContext

from backend.api.routes.auth import RegisterRequest
from backend.api.routes.predictions import BatchPredictionRequest
from backend.api.routes.stocks import WatchlistAddRequest
from backend.api.routes.users import AlertAddRequest, PortfolioAddRequest


# ─── bcrypt 72-byte truncation ──────────────────────────────────────────────


class TestBcryptTruncation:
    def test_bcrypt_silently_truncates_at_72_bytes_raw(self):
        """
        Proves the underlying library behaviour that motivates the
        RegisterRequest validator below: two DIFFERENT passwords sharing
        the same 72-byte UTF-8 prefix hash identically in raw passlib.
        This is a property of bcrypt itself, not a bug in this codebase —
        the fix is catching it at the input boundary (next test).
        """
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        base = "🔥" * 18  # exactly 72 bytes (4 bytes/char x 18)
        pw_a = base + "🎉" * 12
        pw_b = base + "💀" * 12  # different tail, same 72-byte prefix
        hashed = pwd_context.hash(pw_a)
        assert pwd_context.verify(pw_b, hashed) is True  # documents the footgun

    def test_registration_rejects_password_over_72_bytes(self):
        with pytest.raises(ValueError, match="72 bytes"):
            RegisterRequest(
                email="test@example.com",
                password="🔥" * 20,  # 80 bytes — over the limit
                full_name="Test User",
            )

    def test_registration_accepts_password_at_72_byte_boundary(self):
        # 72 plain ASCII bytes = 72 chars, exactly at the limit — must pass
        req = RegisterRequest(
            email="test@example.com",
            password="a" * 72,
            full_name="Test User",
        )
        assert len(req.password) == 72

    def test_registration_accepts_normal_ascii_password(self):
        req = RegisterRequest(
            email="test@example.com",
            password="a_normal_password_123",
            full_name="Test User",
        )
        assert req.password == "a_normal_password_123"


# ─── Ticker input validation (DB column is String(20)) ─────────────────────


class TestTickerValidation:
    @pytest.mark.parametrize(
        "schema_cls,extra_fields",
        [
            (WatchlistAddRequest, {}),
            (
                PortfolioAddRequest,
                {"quantity": 10, "avg_buy_price": 100.0, "buy_date": "2026-01-01T00:00:00Z"},
            ),
            (AlertAddRequest, {"alert_type": "signal"}),
        ],
    )
    def test_ticker_over_20_chars_rejected(self, schema_cls, extra_fields):
        with pytest.raises(Exception):  # pydantic ValidationError
            schema_cls(ticker="A" * 21, **extra_fields)

    @pytest.mark.parametrize(
        "schema_cls,extra_fields",
        [
            (WatchlistAddRequest, {}),
            (
                PortfolioAddRequest,
                {"quantity": 10, "avg_buy_price": 100.0, "buy_date": "2026-01-01T00:00:00Z"},
            ),
            (AlertAddRequest, {"alert_type": "signal"}),
        ],
    )
    def test_ticker_with_injection_style_characters_rejected(self, schema_cls, extra_fields):
        for bad_ticker in ["RELIANCE; DROP TABLE users;--", "../../etc/passwd", "<script>x</script>"]:
            with pytest.raises(Exception):
                schema_cls(ticker=bad_ticker, **extra_fields)

    def test_valid_ticker_accepted(self):
        req = WatchlistAddRequest(ticker="RELIANCE")
        assert req.ticker == "RELIANCE"

    def test_batch_predict_rejects_oversized_ticker_in_list(self):
        with pytest.raises(Exception):
            BatchPredictionRequest(tickers=["RELIANCE", "A" * 25])

    def test_batch_predict_still_accepts_valid_list(self):
        req = BatchPredictionRequest(tickers=["RELIANCE", "TCS", "INFY"])
        assert req.tickers == ["RELIANCE", "TCS", "INFY"]


# ─── Portfolio/alert numeric bounds ─────────────────────────────────────────


class TestNumericBounds:
    def test_portfolio_rejects_negative_quantity(self):
        with pytest.raises(Exception):
            PortfolioAddRequest(
                ticker="RELIANCE", quantity=-5, avg_buy_price=100.0,
                buy_date="2026-01-01T00:00:00Z",
            )

    def test_portfolio_rejects_zero_quantity(self):
        with pytest.raises(Exception):
            PortfolioAddRequest(
                ticker="RELIANCE", quantity=0, avg_buy_price=100.0,
                buy_date="2026-01-01T00:00:00Z",
            )

    def test_portfolio_rejects_negative_price(self):
        with pytest.raises(Exception):
            PortfolioAddRequest(
                ticker="RELIANCE", quantity=10, avg_buy_price=-100.0,
                buy_date="2026-01-01T00:00:00Z",
            )

    def test_alert_rejects_confidence_outside_zero_one(self):
        with pytest.raises(Exception):
            AlertAddRequest(ticker="RELIANCE", alert_type="signal", min_confidence=1.5)

    def test_alert_rejects_negative_price_target(self):
        with pytest.raises(Exception):
            AlertAddRequest(ticker="RELIANCE", alert_type="price_above", price_target=-50.0)

    def test_alert_rejects_unknown_alert_type(self):
        with pytest.raises(Exception):
            AlertAddRequest(ticker="RELIANCE", alert_type="not_a_real_type")
