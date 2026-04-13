"""
E2E: Health, infrastructure, settings, models, MCP tool listing.
"""

import pytest
import httpx


# ── Health Endpoints ─────────────────────────────��───────────────────────────

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client: httpx.AsyncClient):
        r = await client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded", "down")

    @pytest.mark.asyncio
    async def test_health_services(self, client: httpx.AsyncClient):
        r = await client.get("/api/health/services")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "services" in data

    @pytest.mark.asyncio
    async def test_metrics(self, client: httpx.AsyncClient):
        r = await client.get("/api/metrics")
        assert r.status_code == 200
        data = r.json()
        # Metrics should return some structure
        assert isinstance(data, dict)


# ── Settings Endpoints ──────────────────────────────────��────────────────────

class TestSettings:
    @pytest.mark.asyncio
    async def test_get_settings(self, client: httpx.AsyncClient):
        r = await client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_personality_preview(self, client: httpx.AsyncClient):
        r = await client.get("/api/settings/personality/preview")
        assert r.status_code == 200


# ── Models Endpoint ──────────────────────────────────────────────────────────

class TestModels:
    @pytest.mark.asyncio
    async def test_list_available_models(self, client: httpx.AsyncClient):
        r = await client.get("/api/models/available")
        assert r.status_code == 200
        data = r.json()
        # Should return a list or dict of models
        assert data is not None


# ── MCP Tools ────────────────────────────────────────────────────────────────

class TestMCPTools:
    @pytest.mark.asyncio
    async def test_list_tools(self, client: httpx.AsyncClient):
        r = await client.get("/mcp/tools")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data
        assert data["count"] >= 25, f"Expected >= 25 tools, got {data['count']}"

    @pytest.mark.asyncio
    async def test_tools_have_required_fields(self, client: httpx.AsyncClient):
        r = await client.get("/mcp/tools")
        data = r.json()
        tools = data.get("tools", [])
        assert len(tools) > 0, "No tools returned"
        for tool in tools[:5]:
            assert "name" in tool, f"Tool missing name: {tool}"


# ── Agents Endpoint ─────────────────────────────────��────────────────────────

class TestAgents:
    @pytest.mark.asyncio
    async def test_list_agents(self, client: httpx.AsyncClient):
        r = await client.get("/api/agents")
        assert r.status_code == 200
        agents = r.json()
        assert isinstance(agents, list)
        assert len(agents) > 0, "No agents returned"
        for agent in agents:
            assert "type" in agent
            assert "name" in agent
            assert "emoji" in agent
