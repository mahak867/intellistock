"""
IntelliStock — Database Models
────────────────────────────────
SQLAlchemy 2.0 async ORM with:
  • UUID primary keys (no sequential ID leakage)
  • Automatic created_at / updated_at timestamps
  • Soft-delete pattern (deleted_at)
  • Indexed foreign keys and query fields
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ─── Base ───────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Automatic created_at / updated_at / deleted_at on every model."""
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)    # soft-delete

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# ─── User ───────────────────────────────────────────────────────────────────────

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    email           = Column(String(255), nullable=False, unique=True, index=True)
    full_name       = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role            = Column(String(20), nullable=False, default="user")   # user | admin
    is_active       = Column(Boolean, nullable=False, default=True)
    is_verified     = Column(Boolean, nullable=False, default=False)
    api_key_hash    = Column(String(255), nullable=True, unique=True)      # for programmatic access

    # Relationships
    watchlist_items   = relationship("WatchlistItem",   back_populates="user",   cascade="all, delete-orphan")
    prediction_logs   = relationship("PredictionLog",   back_populates="user")
    portfolio_entries = relationship("PortfolioEntry",  back_populates="user",   cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email} role={self.role}>"


# ─── Watchlist ───────────────────────────────────────────────────────────────────

class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "ticker", name="uq_watchlist_user_ticker"),
    )

    id       = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id  = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker   = Column(String(20), nullable=False)
    exchange = Column(String(10), nullable=False, default="NSE")
    notes    = Column(Text, nullable=True)

    user = relationship("User", back_populates="watchlist_items")


# ─── Stock metadata cache ────────────────────────────────────────────────────────

class StockMetadata(Base, TimestampMixin):
    __tablename__ = "stock_metadata"

    ticker        = Column(String(20), primary_key=True)
    exchange      = Column(String(10), nullable=False, default="NSE")
    company_name  = Column(String(200), nullable=True)
    sector        = Column(String(100), nullable=True)
    industry      = Column(String(100), nullable=True)
    market_cap    = Column(BigInteger, nullable=True)
    pe_ratio      = Column(Float, nullable=True)
    eps           = Column(Float, nullable=True)
    dividend_yield = Column(Float, nullable=True)
    is_nifty50    = Column(Boolean, default=False)
    is_active     = Column(Boolean, default=True)


# ─── Prediction Log ──────────────────────────────────────────────────────────────

class PredictionLog(Base, TimestampMixin):
    """
    Stores every prediction made — used for backtesting accuracy tracking.
    Once actual_close is filled in (via nightly job), we can compute real accuracy.
    """
    __tablename__ = "prediction_logs"
    __table_args__ = (
        Index("ix_predlog_ticker_created", "ticker", "created_at"),
    )

    id               = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id          = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True, index=True)
    ticker           = Column(String(20), nullable=False)
    model_version    = Column(String(50), nullable=False)
    prediction_date  = Column(DateTime(timezone=True), nullable=False)     # date we made the prediction
    target_date      = Column(DateTime(timezone=True), nullable=False)     # date we predict FOR
    predicted_close  = Column(Float, nullable=False)
    actual_close     = Column(Float, nullable=True)                        # filled by nightly job
    signal           = Column(String(10), nullable=False)                  # BUY/SELL/HOLD
    confidence       = Column(Float, nullable=False)
    rmse_at_time     = Column(Float, nullable=True)                        # model RMSE when prediction was made

    # Computed after actual is known
    absolute_error   = Column(Float, nullable=True)
    pct_error        = Column(Float, nullable=True)
    direction_correct = Column(Boolean, nullable=True)

    user = relationship("User", back_populates="prediction_logs")


# ─── Model Registry ──────────────────────────────────────────────────────────────

class ModelVersion(Base, TimestampMixin):
    """
    Tracks every trained model version — who trained it, when, how good it was.
    Enables rollback to previous versions if a new model performs worse.
    """
    __tablename__ = "model_versions"

    id             = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    version        = Column(String(50), nullable=False, unique=True)   # e.g. "v1.2.3"
    ticker         = Column(String(20), nullable=False)
    architecture   = Column(String(50), nullable=False)                # BiLSTM | GRU | etc
    rmse           = Column(Float, nullable=False)
    mae            = Column(Float, nullable=False)
    mape           = Column(Float, nullable=False)
    directional_accuracy = Column(Float, nullable=False)
    train_rows     = Column(Integer, nullable=False)
    test_rows      = Column(Integer, nullable=False)
    features_used  = Column(Text, nullable=False)                      # JSON list
    hyperparams    = Column(Text, nullable=False)                      # JSON dict
    storage_path   = Column(String(500), nullable=False)               # S3/GCS/Azure path
    is_active      = Column(Boolean, nullable=False, default=False)    # only 1 active per ticker
    trained_by     = Column(String(100), nullable=True)                # "auto" or user email

    __table_args__ = (
        Index("ix_modelver_ticker_active", "ticker", "is_active"),
    )


# ─── Portfolio ───────────────────────────────────────────────────────────────────

class PortfolioEntry(Base, TimestampMixin):
    """User's tracked positions — for P&L dashboard."""
    __tablename__ = "portfolio_entries"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id       = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker        = Column(String(20), nullable=False)
    exchange      = Column(String(10), nullable=False, default="NSE")
    quantity      = Column(Float, nullable=False)
    avg_buy_price = Column(Float, nullable=False)
    buy_date      = Column(DateTime(timezone=True), nullable=False)
    notes         = Column(Text, nullable=True)

    user = relationship("User", back_populates="portfolio_entries")

    @property
    def invested_value(self) -> float:
        return self.quantity * self.avg_buy_price


# ─── Alert Rules ─────────────────────────────────────────────────────────────────

class AlertRule(Base, TimestampMixin):
    """
    Price / signal alerts — notified via email when triggered.
    E.g. "alert me when RELIANCE BUY signal with confidence > 0.80"
    """
    __tablename__ = "alert_rules"

    id            = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    user_id       = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    ticker        = Column(String(20), nullable=False)
    alert_type    = Column(String(20), nullable=False)   # "signal" | "price_above" | "price_below"
    signal_filter = Column(String(10), nullable=True)    # BUY | SELL | HOLD (for signal alerts)
    price_target  = Column(Float, nullable=True)         # for price_above/below alerts
    min_confidence = Column(Float, nullable=True, default=0.7)
    is_active     = Column(Boolean, nullable=False, default=True)
    last_triggered = Column(DateTime(timezone=True), nullable=True)
    trigger_count  = Column(Integer, nullable=False, default=0)
