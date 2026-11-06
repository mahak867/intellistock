"""
IntelliStock — Stock Service
───────────────────────────────
Metadata search/cache + watchlist CRUD.
Consumed by backend/api/routes/stocks.py.
"""

from __future__ import annotations

from sqlalchemy import or_, select

from backend.core.database import get_session
from backend.models.db_models import StockMetadata, WatchlistItem


class StockService:
    """Ticker metadata cache + per-user watchlist management."""

    # ── Metadata ───────────────────────────────────────────────────────────

    @staticmethod
    async def get_metadata(ticker: str) -> dict | None:
        async with get_session() as session:
            result = await session.execute(
                select(StockMetadata).where(StockMetadata.ticker == ticker)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "ticker": row.ticker,
                "exchange": row.exchange,
                "company_name": row.company_name,
                "sector": row.sector,
                "industry": row.industry,
                "market_cap": row.market_cap,
                "pe_ratio": row.pe_ratio,
                "eps": row.eps,
                "dividend_yield": row.dividend_yield,
                "is_nifty50": row.is_nifty50,
            }

    @staticmethod
    async def fetch_and_cache_metadata(ticker: str) -> dict:
        """
        Fetch fundamentals via yfinance and cache in Postgres.
        Falls back to a minimal record if yfinance has no fundamentals
        (common for less-liquid tickers).
        """
        import yfinance as yf

        from ml.data.pipeline import NIFTY50_TICKERS, normalise_ticker

        yf_ticker = normalise_ticker(ticker, "NSE")
        info = yf.Ticker(yf_ticker).info or {}

        record = {
            "ticker": ticker,
            "exchange": "NSE",
            "company_name": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE"),
            "eps": info.get("trailingEps"),
            "dividend_yield": info.get("dividendYield"),
            "is_nifty50": ticker in NIFTY50_TICKERS,
        }

        async with get_session() as session:
            row = StockMetadata(**record)
            await session.merge(row)
            await session.flush()

        return record

    @staticmethod
    async def search(query: str, limit: int = 20) -> list[dict]:
        async with get_session() as session:
            result = await session.execute(
                select(StockMetadata)
                .where(
                    or_(
                        StockMetadata.ticker.ilike(f"%{query}%"),
                        StockMetadata.company_name.ilike(f"%{query}%"),
                    )
                )
                .limit(limit)
            )
            rows = result.scalars().all()
            return [
                {
                    "ticker": r.ticker,
                    "company_name": r.company_name,
                    "exchange": r.exchange,
                    "is_nifty50": r.is_nifty50,
                }
                for r in rows
            ]

    # ── Watchlist ──────────────────────────────────────────────────────────

    @staticmethod
    async def add_watchlist(
        user_id: str, ticker: str, exchange: str = "NSE", notes: str | None = None, list_name: str = "Main"
    ) -> WatchlistItem:
        async with get_session() as session:
            item = WatchlistItem(
                user_id=user_id, ticker=ticker, exchange=exchange, notes=notes, list_name=list_name
            )
            session.add(item)
            await session.flush()
            await session.refresh(item)
            return item

    @staticmethod
    async def get_watchlist(user_id: str) -> list[dict]:
        async with get_session() as session:
            result = await session.execute(
                select(WatchlistItem).where(WatchlistItem.user_id == user_id)
            )
            rows = result.scalars().all()
            return [
                {
                    "id": str(r.id),
                    "ticker": r.ticker,
                    "exchange": r.exchange,
                    "notes": r.notes,
                    "list_name": r.list_name or "Main",
                    "added_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    @staticmethod
    async def remove_watchlist(item_id: str, user_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(
                select(WatchlistItem).where(
                    WatchlistItem.id == item_id, WatchlistItem.user_id == user_id
                )
            )
            item = result.scalar_one_or_none()
            if not item:
                return False
            await session.delete(item)
            await session.flush()
            return True
