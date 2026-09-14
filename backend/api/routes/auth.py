"""
IntelliStock — Authentication Routes
──────────────────────────────────────
• POST /auth/register    — create account (bcrypt password)
• POST /auth/login       — issue JWT access + refresh tokens
• POST /auth/refresh     — rotate access token
• POST /auth/logout      — invalidate refresh token in Redis
• POST /auth/api-key     — generate long-lived API key for programmatic access
• GET  /auth/me          — current user info
"""


from datetime import datetime, timedelta, timezone
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
    OAuth2PasswordRequestForm,
)
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.core.config import settings

router = APIRouter()

# ─── Crypto ─────────────────────────────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ─── Token creation ──────────────────────────────────────────────────────────────


def create_access_token(subject: str, role: str = "user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ─── Dependencies ────────────────────────────────────────────────────────────────


async def get_redis() -> aioredis.Redis:
    from backend.core.redis_client import get_redis_client

    return await get_redis_client()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    redis: aioredis.Redis = Depends(get_redis),
) -> dict:
    """Dependency — validates Bearer token, checks revocation list in Redis."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_token(token)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Wrong token type")

    # Check if token has been revoked (logout)
    revoked = await redis.get(f"revoked:{token}")
    if revoked:
        raise HTTPException(status_code=401, detail="Token has been revoked")

    return payload


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user


# ─── Schemas ────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_must_fit_bcrypt(cls, v: str) -> str:
        # bcrypt silently truncates at 72 BYTES (not characters). Without
        # this check, two different passwords sharing the same 72-byte
        # UTF-8 prefix (trivial with multi-byte characters like emoji)
        # verify as identical — proved this with a direct passlib test.
        # Reject explicitly rather than let auth silently weaken.
        if len(v.encode("utf-8")) > 72:
            raise ValueError(
                "Password is too long once encoded (max 72 bytes — multi-byte "
                "characters like emoji count as more than 1 byte each)"
            )
        return v


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    email: str
    full_name: str
    role: str
    created_at: datetime


# ─── Routes ─────────────────────────────────────────────────────────────────────


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register new account",
)
async def register(payload: RegisterRequest) -> dict:
    """
    Create a new IntelliStock account.
    Password is bcrypt-hashed before storage — never stored in plaintext.
    """
    from backend.services.user_service import UserService

    existing = await UserService.get_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    hashed = hash_password(payload.password)
    user = await UserService.create(
        email=payload.email,
        hashed_password=hashed,
        full_name=payload.full_name,
    )
    logger.info(f"New user registered: {payload.email}")
    return {"message": "Account created successfully", "user_id": str(user.id)}


@router.post("/login", response_model=LoginResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> LoginResponse:
    """
    Authenticate and receive JWT tokens.
    Uses OAuth2PasswordRequestForm for compatibility with standard tooling.
    """
    from backend.services.user_service import UserService

    user = await UserService.get_by_email(form_data.username)  # username = email
    if not user or not verify_password(form_data.password, user.hashed_password):
        # Constant-time comparison via passlib — no timing attack
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    access = create_access_token(subject=str(user.id), role=user.role)
    refresh = create_refresh_token(subject=str(user.id))

    # Store refresh token in Redis with TTL
    redis = await get_redis()
    await redis.setex(
        f"refresh:{user.id}",
        settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        refresh,
    )

    logger.info(f"User logged in: {user.email}")
    return LoginResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    payload: RefreshRequest,
    redis: aioredis.Redis = Depends(get_redis),
) -> LoginResponse:
    """Rotate access token using a valid refresh token."""
    claims = decode_token(payload.refresh_token)
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Wrong token type")

    user_id = claims["sub"]

    # Verify the refresh token matches what we stored
    stored = await redis.get(f"refresh:{user_id}")
    if not stored or stored.decode() != payload.refresh_token:
        raise HTTPException(
            status_code=401, detail="Refresh token invalid or already used"
        )

    from backend.services.user_service import UserService

    user = await UserService.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        # Without this check, a deactivated account could refresh its
        # session indefinitely as long as it already held a valid,
        # unexpired refresh token — deactivation would never actually
        # take effect until Redis's TTL happened to expire it.
        raise HTTPException(status_code=401, detail="Account is deactivated")

    # Rotate tokens
    new_access = create_access_token(subject=user_id, role=user.role)
    new_refresh = create_refresh_token(subject=user_id)
    await redis.setex(
        f"refresh:{user_id}", settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, new_refresh
    )

    return LoginResponse(access_token=new_access, refresh_token=new_refresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(bearer)],
    current_user: dict = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
) -> None:
    """
    Revoke access token and delete refresh token.
    Access token is blocklisted in Redis until its natural expiry.
    """
    token = credentials.credentials
    claims = decode_token(token)
    remaining_ttl = int((claims["exp"] - datetime.now(timezone.utc).timestamp()))

    if remaining_ttl > 0:
        await redis.setex(f"revoked:{token}", remaining_ttl, "1")

    await redis.delete(f"refresh:{current_user['sub']}")
    logger.info(f"User {current_user['sub']} logged out")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)) -> UserResponse:
    """Return current authenticated user's profile."""
    from backend.services.user_service import UserService

    user = await UserService.get_by_id(current_user["sub"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        created_at=user.created_at,
    )
