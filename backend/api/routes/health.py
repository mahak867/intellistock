"""
IntelliStock — Health Check Endpoints
───────────────────────────────────────
• GET /health           — liveness probe (always 200 if app is up)
• GET /health/ready     — readiness probe (checks DB + Redis + model)
• GET /health/detailed  — full system status (admin only)

Used by:
  • Kubernetes liveness/readiness probes
  • GCP Cloud Run health checks
  • AWS ECS health checks
  • Load balancer health checks
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from loguru import logger

from backend.api.routes.auth import require_admin
from backend.core.config import settings

router = APIRouter()

# App start time for uptime tracking
_START_TIME = time.time()


@router.get("", status_code=status.HTTP_200_OK, summary="Liveness probe")
async def liveness() -> dict:
    """
    Kubernetes liveness probe.
    Returns 200 as long as the FastAPI process is alive.
    """
    return {
        "status": "alive",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT.value,
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness probe")
async def readiness() -> JSONResponse:
    """
    Kubernetes readiness probe.
    Returns 200 only when DB + Redis + ML model are all available.
    Returns 503 otherwise — this removes the pod from the load balancer.
    """
    checks: dict[str, dict] = {}
    all_healthy = True

    # ── Database check ───────────────────────────────────────────────────────
    try:
        from backend.core.database import engine

        if engine:
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            checks["database"] = {"status": "ok", "latency_ms": None}
        else:
            raise RuntimeError("Engine not initialised")
    except Exception as exc:
        checks["database"] = {"status": "error", "detail": str(exc)}
        all_healthy = False
        logger.warning(f"Health check — DB failed: {exc}")

    # ── Redis check ──────────────────────────────────────────────────────────
    try:
        from backend.core.redis_client import get_redis_client

        redis = await get_redis_client()
        t0 = time.perf_counter()
        await redis.ping()
        latency = round((time.perf_counter() - t0) * 1000, 2)
        checks["redis"] = {"status": "ok", "latency_ms": latency}
    except Exception as exc:
        checks["redis"] = {"status": "error", "detail": str(exc)}
        all_healthy = False
        logger.warning(f"Health check — Redis failed: {exc}")

    # ── ML model check ───────────────────────────────────────────────────────
    try:
        from backend.services.model_service import ModelService

        model_status = ModelService.get_status()
        checks["ml_model"] = model_status
        if model_status.get("status") != "loaded":
            all_healthy = False
    except Exception as exc:
        checks["ml_model"] = {"status": "error", "detail": str(exc)}
        all_healthy = False

    http_status = (
        status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if all_healthy else "degraded",
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.get("/detailed", summary="Full system status (admin)")
async def detailed_health(admin: dict = Depends(require_admin)) -> dict:
    """
    Detailed system diagnostics — admin only.
    Includes memory, model versions, cache stats, worker status.
    """
    import psutil
    from backend.services.model_service import ModelService

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "app": {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT.value,
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "memory_used_gb": round(memory.used / 1e9, 2),
            "memory_total_gb": round(memory.total / 1e9, 2),
            "memory_percent": memory.percent,
            "disk_used_gb": round(disk.used / 1e9, 2),
            "disk_total_gb": round(disk.total / 1e9, 2),
            "disk_percent": disk.percent,
        },
        "models": ModelService.get_all_model_versions(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
