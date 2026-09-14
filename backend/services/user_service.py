"""
IntelliStock — User Service
──────────────────────────────
Thin async data-access layer over the `users` table.
Consumed by backend/api/routes/auth.py and backend/api/routes/users.py.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.core.database import get_session
from backend.models.db_models import User


class UserService:
    """CRUD operations for the User model. All methods are async + stateless."""

    @staticmethod
    async def get_by_email(email: str) -> User | None:
        async with get_session() as session:
            result = await session.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(user_id: str) -> User | None:
        async with get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()

    @staticmethod
    async def create(email: str, hashed_password: str, full_name: str) -> User:
        async with get_session() as session:
            user = User(
                email=email,
                hashed_password=hashed_password,
                full_name=full_name,
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user

    @staticmethod
    async def update_profile(user_id: str, **fields) -> User | None:
        """Update mutable profile fields (full_name, is_active, etc.)."""
        async with get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return None
            for key, value in fields.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            await session.flush()
            await session.refresh(user)
            return user

    @staticmethod
    async def deactivate(user_id: str) -> bool:
        async with get_session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return False
            user.is_active = False
            await session.flush()
            return True
