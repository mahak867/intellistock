"""
IntelliStock — FastAPI Application Entry Point
────────────────────────────────────────────────
• JWT Bearer authentication
• Rate limiting per IP via slowapi + Redis
• Prometheus metrics at /metrics
• Sentry error tracking
• CORS, HTTPS-only headers, trusted host middleware
• OpenTelemetry tracing
• Structured logging (loguru → JSON in production)
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_client import Counter, Histogram, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.api.routes import auth, health, predictions, stocks, users
from backend.core.config import settings

# ─── Prometheus metrics ─────────────────────────────────────────────────────────

REQUEST_COUNT = Counter(
    "intellistock_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "intellistock_request_duration_seconds",
    "HTTP request latency",
    ["endpoint"],
)
PREDICTION_COUNT = Counter(
    "intellistock_predictions_total",
    "Total ML predictions served",
    ["ticker", "signal"],
)


# ─── Sentry ─────────────────────────────────────────────────────────────────────

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT.value,
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        send_default_pii=False,
    )


# ─── Rate limiter ────────────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=str(settings.REDIS_URL),
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
)


# ─── Lifespan (startup/shutdown) ─────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup: warm caches, load model. Shutdown: flush connections."""
    logger.info(
        f"IntelliStock {settings.APP_VERSION} starting in {settings.ENVIRONMENT} mode"
    )

    # Import here to avoid circular imports at module level
    from backend.services.model_service import ModelService

    from backend.core.database import init_db
    from backend.core.redis_client import init_redis

    await init_db()
    await init_redis()
    await ModelService.load_all_models()

    logger.info("All services ready — accepting traffic")
    yield

    logger.info("Shutting down IntelliStock")
    from backend.core.redis_client import close_redis

    await close_redis()


# ─── App factory ────────────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="IntelliStock API",
        description=(
            "NSE/BSE Market Intelligence — LSTM-powered price forecasting, "
            "BUY/SELL/HOLD signals, and portfolio analytics for Indian equities."
        ),
        version=settings.APP_VERSION,
        docs_url=(
            "/docs" if not settings.is_production else None
        ),  # hide Swagger in prod
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Rate limiter ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o) for o in settings.ALLOWED_ORIGINS] or ["*"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Remaining"],
    )

    # ── Trusted host ─────────────────────────────────────────────────────────
    if settings.is_production:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.ALLOWED_HOSTS,
        )

    # ── Gzip compression ──────────────────────────────────────────────────────
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Request ID + timing middleware ────────────────────────────────────────
    @app.middleware("http")
    async def request_middleware(request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(f"Unhandled error [{request_id}]: {exc}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error", "request_id": request_id},
            )

        duration = time.perf_counter() - start
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.4f}s"

        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Prometheus
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status=response.status_code,
        ).inc()
        REQUEST_LATENCY.labels(endpoint=request.url.path).observe(duration)

        logger.info(
            f"{request.method} {request.url.path} "
            f"→ {response.status_code} [{duration*1000:.1f}ms] [{request_id[:8]}]"
        )
        return response

    # ── Prometheus metrics endpoint ───────────────────────────────────────────
    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(), media_type="text/plain")

    # ── Routers ───────────────────────────────────────────────────────────────
    API_V1 = "/api/v1"
    app.include_router(health.router, prefix=f"{API_V1}/health", tags=["Health"])
    app.include_router(auth.router, prefix=f"{API_V1}/auth", tags=["Auth"])
    app.include_router(users.router, prefix=f"{API_V1}/users", tags=["Users"])
    app.include_router(stocks.router, prefix=f"{API_V1}/stocks", tags=["Stocks"])
    app.include_router(
        predictions.router, prefix=f"{API_V1}/predictions", tags=["Predictions"]
    )

    return app


app = create_app()
