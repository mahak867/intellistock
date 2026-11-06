"""A server error must still carry CORS headers, or browsers report it as a blocked request instead of an error."""
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.config import settings


def test_500_has_cors_headers(monkeypatch):
    @app.get("/api/v1/__boom_for_test", include_in_schema=False)
    def boom():
        raise RuntimeError("boom")

    if not settings.ALLOWED_ORIGINS:
        import pytest
        pytest.skip("no ALLOWED_ORIGINS configured, so CORS is off")
    origin = str(settings.ALLOWED_ORIGINS[0]).rstrip("/")
    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/__boom_for_test", headers={"Origin": origin})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == origin
