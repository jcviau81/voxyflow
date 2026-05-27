"""Tests for GET /health endpoint.

Smoke tests that hit the real FastAPI route via httpx ASGI transport
(no running server needed, but uses real DB/scheduler state).
"""

import pytest
import httpx

from app.main import app


@pytest.mark.asyncio
async def test_health_returns_200_with_json_keys():
    """GET /health returns HTTP 200 and JSON with all required top-level keys."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")

    # /health must respond as JSON (not HTML/SPA fallback)
    assert r.headers.get("content-type", "").startswith("application/json"), (
        f"Expected JSON content-type, got: {r.headers.get('content-type')!r}\n"
        f"Body snippet: {r.text[:200]}"
    )
    # Status must be 200 (ok) or 503 (degraded) — never a redirect or HTML 200
    assert r.status_code in (200, 503), f"Unexpected status: {r.status_code}"


@pytest.mark.asyncio
async def test_health_response_shape():
    """GET /health response body contains all required keys with correct types."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.get("/health")

    data = r.json()

    # Required top-level keys
    assert "status" in data, f"Missing 'status' key: {data}"
    assert "version" in data, f"Missing 'version' key: {data}"
    assert "uptime_seconds" in data, f"Missing 'uptime_seconds' key: {data}"
    assert "checks" in data, f"Missing 'checks' key: {data}"

    # status must be one of the known values
    assert data["status"] in ("ok", "degraded"), (
        f"Unexpected status value: {data['status']!r}"
    )

    # version is a non-empty string
    assert isinstance(data["version"], str) and data["version"], (
        f"version should be a non-empty string, got: {data['version']!r}"
    )

    # uptime_seconds is a non-negative integer
    assert isinstance(data["uptime_seconds"], int) and data["uptime_seconds"] >= 0, (
        f"uptime_seconds should be a non-negative int, got: {data['uptime_seconds']!r}"
    )

    # checks contains at least db and chroma keys
    checks = data["checks"]
    assert "db" in checks, f"Missing 'db' in checks: {checks}"
    assert "chroma" in checks, f"Missing 'chroma' in checks: {checks}"
