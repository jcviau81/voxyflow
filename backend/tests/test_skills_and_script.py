"""Skills system + programmatic tool calling (voxyflow.script) — tests.

Covers:
- skill_service: save/get/list/delete roundtrip, global vs workspace scoping,
  slug sanitization (path-traversal rejection), catalog budget truncation.
- MCP handlers: skill save/get with VOXYFLOW_WORKSPACE_ID env set/unset.
- Registry role sets: skill tools dispatcher+worker; voxyflow.script worker-only.
- script_run: chained tool calls via `await call_tool`, role enforcement,
  timeout, exception capture, print() capture.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.mcp_server as mcp_server
import app.services.skill_service as skill_service_module
from app.mcp_server import _get_system_handler
from app.services.skill_service import SkillService, sanitize_skill_name
from app.tools.registry import TOOLS_DISPATCHER, TOOLS_WORKER

WS_A = "11111111-1111-1111-1111-111111111111"
WS_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def svc(tmp_path):
    """SkillService rooted in a tmp dir (monkeypatched VOXYFLOW_DIR equivalent)."""
    return SkillService(base_dir=tmp_path / "skills")


@pytest.fixture
def patched_singleton(svc, monkeypatch):
    """Point the module singleton at the tmp-dir service (for handler tests)."""
    monkeypatch.setattr(skill_service_module, "_skill_service", svc)
    return svc


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# skill_service
# ---------------------------------------------------------------------------


class TestSkillService:
    def test_save_get_list_delete_roundtrip(self, svc):
        meta = svc.save_skill(
            "deploy-staging", "How to deploy to staging.",
            "1. git pull\n2. systemctl restart", scope="global",
        )
        assert meta.name == "deploy-staging"
        assert meta.scope == "global"

        got = svc.get_skill("deploy-staging")
        assert got is not None
        assert got["name"] == "deploy-staging"
        assert got["description"] == "How to deploy to staging."
        assert "systemctl restart" in got["instructions"]

        listed = svc.list_skills()
        assert [s.name for s in listed] == ["deploy-staging"]

        assert svc.delete_skill("deploy-staging") is True
        assert svc.get_skill("deploy-staging") is None
        assert svc.list_skills() == []
        # Second delete is a no-op
        assert svc.delete_skill("deploy-staging") is False

    def test_save_updates_existing(self, svc):
        svc.save_skill("fmt-report", "v1", "old body", scope="global")
        svc.save_skill("fmt-report", "v2 description", "new body", scope="global")
        skills = svc.list_skills()
        assert len(skills) == 1
        assert skills[0].description == "v2 description"
        assert svc.get_skill("fmt-report")["instructions"] == "new body"

    def test_workspace_scoping(self, svc):
        svc.save_skill("global-skill", "everywhere", "g", scope="global")
        svc.save_skill("ws-a-skill", "only in A", "a", scope="workspace", workspace_id=WS_A)

        # Workspace A sees global + its own
        names_a = {s.name for s in svc.list_skills(WS_A)}
        assert names_a == {"global-skill", "ws-a-skill"}

        # Workspace B sees global only — A's skills are invisible
        names_b = {s.name for s in svc.list_skills(WS_B)}
        assert names_b == {"global-skill"}
        assert svc.get_skill("ws-a-skill", WS_B) is None

        # General chat (empty / system-main) sees global only
        assert {s.name for s in svc.list_skills(None)} == {"global-skill"}
        assert {s.name for s in svc.list_skills("system-main")} == {"global-skill"}
        assert svc.get_skill("ws-a-skill", "system-main") is None

    def test_workspace_save_in_general_chat_falls_back_to_global(self, svc):
        meta = svc.save_skill("home-skill", "saved from general chat", "x",
                              scope="workspace", workspace_id="system-main")
        assert meta.scope == "global"
        meta2 = svc.save_skill("home-skill-2", "no workspace", "x",
                               scope="workspace", workspace_id=None)
        assert meta2.scope == "global"

    def test_slug_sanitization_rejects_traversal(self, svc):
        for bad in ("../x", "..", "a/b", "a\\b", "x.y", "UPPER CASE!?", "", "   "):
            with pytest.raises(ValueError):
                sanitize_skill_name(bad)
            with pytest.raises(ValueError):
                svc.save_skill(bad, "d", "b", scope="global")

    def test_slug_normalizes_spaces_and_case(self, svc):
        assert sanitize_skill_name("Deploy Staging") == "deploy-staging"
        assert sanitize_skill_name("my_skill") == "my-skill"

    def test_malformed_frontmatter_skipped_in_list(self, svc, tmp_path):
        svc.save_skill("good-skill", "fine", "ok", scope="global")
        bad_dir = svc.base_dir / "global" / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "SKILL.md").write_text("no frontmatter here, just text")
        names = {s.name for s in svc.list_skills()}
        assert names == {"good-skill"}

    def test_catalog_grouping_and_get_hint(self, svc):
        svc.save_skill("global-skill", "the global one", "g", scope="global")
        svc.save_skill("ws-skill", "the workspace one", "w", scope="workspace", workspace_id=WS_A)
        catalog = svc.build_skills_catalog(WS_A)
        assert catalog is not None
        assert "voxyflow.skill.get" in catalog
        assert "Global skills:" in catalog
        assert "Workspace skills:" in catalog
        assert "- global-skill: the global one" in catalog
        assert "- ws-skill: the workspace one" in catalog
        # General chat catalog: global only
        general = svc.build_skills_catalog(None)
        assert "ws-skill" not in general
        assert "global-skill" in general

    def test_catalog_empty_returns_none(self, svc):
        assert svc.build_skills_catalog(WS_A) is None

    def test_catalog_budget_truncation(self, svc):
        for i in range(50):
            svc.save_skill(f"skill-{i:02d}", "x" * 120, "body", scope="global")
        catalog = svc.build_skills_catalog(None, max_chars=1500)
        assert len(catalog) < 1500 + 200  # header overshoot bounded by the "… and N more" line
        assert "more — call voxyflow.skill.list" in catalog


# ---------------------------------------------------------------------------
# MCP handlers (env-scoped)
# ---------------------------------------------------------------------------


class TestSkillHandlers:
    def test_save_and_get_with_workspace_env(self, patched_singleton, monkeypatch):
        monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", WS_A)
        save = _get_system_handler("skill_save")
        get = _get_system_handler("skill_get")
        listing = _get_system_handler("skill_list")

        result = _run(save({
            "name": "env-skill", "description": "scoped via env",
            "instructions": "step 1",
        }))
        assert result["success"] is True
        assert result["scope"] == "workspace"

        got = _run(get({"name": "env-skill"}))
        assert got["success"] is True
        assert got["instructions"] == "step 1"

        listed = _run(listing({}))
        assert listed["success"] is True
        assert {s["name"] for s in listed["skills"]} == {"env-skill"}

        # Skill is invisible from another workspace
        monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", WS_B)
        got_b = _run(get({"name": "env-skill"}))
        assert got_b["success"] is False

    def test_save_without_workspace_env_goes_global(self, patched_singleton, monkeypatch):
        monkeypatch.delenv("VOXYFLOW_WORKSPACE_ID", raising=False)
        save = _get_system_handler("skill_save")
        result = _run(save({
            "name": "global-via-env", "description": "d", "instructions": "i",
        }))
        assert result["success"] is True
        assert result["scope"] == "global"
        # Visible from any workspace (global)
        monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", WS_A)
        got = _run(_get_system_handler("skill_get")({"name": "global-via-env"}))
        assert got["success"] is True

    def test_handler_rejects_bad_slug(self, patched_singleton, monkeypatch):
        monkeypatch.delenv("VOXYFLOW_WORKSPACE_ID", raising=False)
        result = _run(_get_system_handler("skill_save")({
            "name": "../evil", "description": "d", "instructions": "i",
        }))
        assert result["success"] is False
        assert "Invalid skill name" in result["error"]

    def test_delete_handler(self, patched_singleton, monkeypatch):
        monkeypatch.delenv("VOXYFLOW_WORKSPACE_ID", raising=False)
        _run(_get_system_handler("skill_save")({
            "name": "to-delete", "description": "d", "instructions": "i",
        }))
        result = _run(_get_system_handler("skill_delete")({"name": "to-delete"}))
        assert result["success"] is True
        again = _run(_get_system_handler("skill_delete")({"name": "to-delete"}))
        assert again["success"] is False


# ---------------------------------------------------------------------------
# Registry role boundary
# ---------------------------------------------------------------------------


class TestRoleSets:
    def test_skill_tools_dispatcher_and_worker(self):
        skill_tools = {
            "voxyflow.skill.list", "voxyflow.skill.get",
            "voxyflow.skill.save", "voxyflow.skill.delete",
        }
        assert skill_tools <= TOOLS_DISPATCHER
        assert skill_tools <= TOOLS_WORKER

    def test_script_is_worker_only(self):
        assert "voxyflow.script" in TOOLS_WORKER
        assert "voxyflow.script" not in TOOLS_DISPATCHER

    def test_new_tools_resolve_in_catalog(self):
        names = {t["name"] for t in mcp_server._TOOL_DEFINITIONS}
        assert {"voxyflow.skill.list", "voxyflow.skill.get", "voxyflow.skill.save",
                "voxyflow.skill.delete", "voxyflow.script"} <= names

    def test_skill_schemas_have_no_workspace_id(self):
        """STRICT ISOLATION: scope comes from VOXYFLOW_WORKSPACE_ID, never the LLM."""
        for t in mcp_server._TOOL_DEFINITIONS:
            if t["name"].startswith("voxyflow.skill."):
                assert "workspace_id" not in t["inputSchema"].get("properties", {})


# ---------------------------------------------------------------------------
# voxyflow.script — script_run handler
# ---------------------------------------------------------------------------


@pytest.fixture
def script_run():
    return _get_system_handler("script_run")


class TestScriptRun:
    def test_chained_tool_calls_and_result(self, script_run, monkeypatch):
        calls: list[tuple[str, dict]] = []

        async def fake_call_api(tool_def, args):
            calls.append((tool_def["name"], args))
            return {"success": True, "echo": args.get("n")}

        monkeypatch.setattr(mcp_server, "_call_api", fake_call_api)
        monkeypatch.setattr(mcp_server, "VOXYFLOW_MCP_ROLE", "worker")

        code = (
            "a = await call_tool('voxyflow.card.get', {'n': 1})\n"
            "b = await call_tool('voxyflow.card.get', {'n': 2})\n"
            "print('first:', a['echo'])\n"
            "result = a['echo'] + b['echo']\n"
        )
        out = _run(script_run({"code": code}))
        assert out["success"] is True
        assert out["result"] == 3
        assert "first: 1" in out["output"]
        assert [c[0] for c in calls] == ["voxyflow.card.get", "voxyflow.card.get"]

    def test_role_enforcement_dispatcher_blocked(self, script_run, monkeypatch):
        async def fake_call_api(tool_def, args):  # must never be reached
            raise AssertionError("role check bypassed")

        monkeypatch.setattr(mcp_server, "_call_api", fake_call_api)
        monkeypatch.setattr(mcp_server, "VOXYFLOW_MCP_ROLE", "dispatcher")

        code = "result = await call_tool('system.exec', {'command': 'id'})\n"
        out = _run(script_run({"code": code}))
        assert out["success"] is True  # script ran; the call inside was refused
        assert out["result"]["success"] is False
        assert "not available" in out["result"]["error"]

    def test_role_enforcement_outside_worker_set(self, script_run, monkeypatch):
        """Even as worker, a script is bounded by TOOLS_WORKER."""
        import app.tools.registry as registry

        async def fake_call_api(tool_def, args):
            raise AssertionError("worker-set check bypassed")

        monkeypatch.setattr(mcp_server, "_call_api", fake_call_api)
        monkeypatch.setattr(mcp_server, "VOXYFLOW_MCP_ROLE", "worker")
        monkeypatch.setattr(registry, "TOOLS_WORKER", registry.TOOLS_WORKER - {"memory.search"})

        code = "result = await call_tool('memory.search', {'query': 'x'})\n"
        out = _run(script_run({"code": code}))
        assert out["result"]["success"] is False
        assert "not available" in out["result"]["error"]

    def test_script_cannot_nest_itself(self, script_run, monkeypatch):
        monkeypatch.setattr(mcp_server, "VOXYFLOW_MCP_ROLE", "worker")
        code = "result = await call_tool('voxyflow.script', {'code': 'pass'})\n"
        out = _run(script_run({"code": code}))
        assert out["result"]["success"] is False
        assert "nesting" in out["result"]["error"]

    def test_unknown_tool(self, script_run, monkeypatch):
        monkeypatch.setattr(mcp_server, "VOXYFLOW_MCP_ROLE", "worker")
        code = "result = await call_tool('no.such.tool', {})\n"
        out = _run(script_run({"code": code}))
        assert out["result"]["success"] is False
        assert "Unknown tool" in out["result"]["error"]

    def test_timeout_fires(self, script_run):
        out = _run(script_run({
            "code": "await asyncio.sleep(5)\n",
            "timeout_seconds": 1,
        }))
        assert out["success"] is False
        assert "timed out" in out["error"]

    def test_exception_captured(self, script_run):
        out = _run(script_run({
            "code": "print('before')\nraise ValueError('boom')\n",
        }))
        assert out["success"] is False
        assert "ValueError" in out["traceback"]
        assert "boom" in out["traceback"]
        assert "before" in out["output"]

    def test_syntax_error(self, script_run):
        out = _run(script_run({"code": "def broken(:\n"}))
        assert out["success"] is False
        assert "SyntaxError" in out["error"]

    def test_empty_code_rejected(self, script_run):
        out = _run(script_run({"code": "   "}))
        assert out["success"] is False

    def test_globals_available(self, script_run):
        out = _run(script_run({
            "code": "result = json.dumps(sorted(re.findall(r'[a-z]+', 'b a')))\n",
        }))
        assert out["success"] is True
        assert out["result"] == '["a", "b"]'
