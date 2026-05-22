"""Smoke test — workspace autonomy heartbeat layer.

Verifies that workspace heartbeats are routed through the dedicated autonomy
runner (dispatcher-shaped, no 'wait for go' gate), not the interactive
dispatcher that paralyses them when no user is present.

Run from backend/ with venv activated:
  cd backend && source venv/bin/activate && python scripts/smoke_test_autonomy.py
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

PASS_COUNT = 0
FAIL_COUNT = 0


def test(name):
    def decorator(fn):
        def wrapper():
            global PASS_COUNT, FAIL_COUNT
            try:
                fn()
                print(f"[PASS] {name}")
                PASS_COUNT += 1
            except AssertionError as e:
                print(f"[FAIL] {name}: {e}")
                FAIL_COUNT += 1
            except Exception as e:
                print(f"[FAIL] {name}: unexpected {type(e).__name__}: {e}")
                FAIL_COUNT += 1
        return wrapper
    return decorator


@test("autonomy prompt — includes operating rules, workspace, directive path")
def test_autonomy_prompt_shape():
    from app.services.personality_service import PersonalityService
    ps = PersonalityService()
    p = ps.build_autonomy_prompt(
        workspace={"id": "proj-1", "title": "TestProj"},
        directive_path="/tmp/heartbeat.md",
        native_tools="cli_mcp",
    )
    assert "Autonomy Heartbeat" in p, "missing autonomy header"
    assert "TestProj" in p, "missing workspace title"
    assert "/tmp/heartbeat.md" in p, "missing directive path"
    assert "AUTONOMY-NOOP" in p, "missing no-op sentinel"
    assert "No user is present" in p, "missing no-user-present clause"
    # The dispatcher 'go gate' language must NOT leak into the autonomy prompt.
    assert "Never emit a <delegate> block unless" not in p, \
        "dispatcher go-gate leaked into autonomy prompt"
    assert "wait for go" not in p.lower() or "no 'wait for go'" in p.lower(), \
        "autonomy prompt contains the go-gate instead of overriding it"


@test("dispatcher and autonomy prompts differ (autonomy is NOT just the dispatcher)")
def test_prompts_differ():
    from app.services.personality_service import PersonalityService
    ps = PersonalityService()
    dp = ps.build_fast_prompt(chat_level="general", native_tools="cli_mcp")
    ap = ps.build_autonomy_prompt(
        workspace={"id": "p", "title": "X"},
        directive_path="/tmp/h.md",
        native_tools="cli_mcp",
    )
    assert "Dispatcher" in dp, "dispatcher label missing from interactive prompt"
    assert "Autonomy Heartbeat" in ap, "autonomy label missing from autonomy prompt"
    assert "Autonomy Heartbeat" not in dp, \
        "interactive dispatcher prompt should NOT carry autonomy header"
    assert "AUTONOMY-NOOP" not in dp, \
        "no-op sentinel leaked into interactive dispatcher prompt"


@test("default heartbeat file — seeded with an actionable directive, not empty")
def test_default_directive_not_empty():
    import re
    from app.services.workspace_autonomy import _DEFAULT_PREAMBLE, DIVIDER
    rendered = _DEFAULT_PREAMBLE.format(title="Any Workspace")
    assert DIVIDER in rendered, "divider missing from seeded preamble"
    below = rendered.split(DIVIDER, 1)[1]
    stripped = re.sub(r"<!--.*?-->", "", below, flags=re.DOTALL).strip()
    assert stripped, \
        "seeded directive below divider is empty — file_has_directive gate would always skip"
    assert "workers.list" in stripped, "default directive should reference workers.list"
    assert "AUTONOMY-NOOP" in stripped, \
        "default directive should tell the model how to no-op instead of brainstorming"


@test("build_job_dict — carries workspace_heartbeat flag in payload and top-level")
def test_job_dict_flag_both_places():
    from app.services.workspace_autonomy import build_job_dict
    jd = build_job_dict("proj-42", "ProjFortyTwo")
    assert jd.get("workspace_heartbeat") is True, "top-level flag missing"
    assert jd["payload"].get("workspace_heartbeat") is True, \
        "payload flag missing — _run_agent_task would not route to autonomy"
    assert jd["payload"].get("workspace_id") == "proj-42"
    assert jd["payload"].get("gate", {}).get("type") == "file_has_directive"


@test("_run_agent_task routes heartbeat jobs to _run_autonomy_tick")
def test_heartbeat_routing():
    import asyncio
    from app.services import job_runner as jr

    captured = {}

    async def fake_autonomy_tick(job, payload):
        captured["called"] = True
        captured["job_id"] = job.get("id")
        captured["workspace_id"] = payload.get("workspace_id")
        return {"status": "ok", "message": "fake autonomy"}

    original = jr._run_autonomy_tick
    jr._run_autonomy_tick = fake_autonomy_tick
    try:
        job = {"id": "hb-1", "name": "Heartbeat", "workspace_heartbeat": True}
        payload = {
            "workspace_heartbeat": True,
            "workspace_id": "proj-xyz",
            "instruction": "tick",
        }
        result = asyncio.run(jr._run_agent_task(job, payload))
    finally:
        jr._run_autonomy_tick = original

    assert captured.get("called"), "heartbeat job did NOT route to _run_autonomy_tick"
    assert captured.get("workspace_id") == "proj-xyz"
    assert result["status"] == "ok"


@test("_run_agent_task leaves non-heartbeat agent_task jobs on the dispatcher path")
def test_non_heartbeat_stays_on_dispatcher():
    import asyncio
    from app.services import job_runner as jr

    called = {"autonomy": False}

    async def trap_autonomy(job, payload):
        called["autonomy"] = True
        return {"status": "ok", "message": "should not be called"}

    original = jr._run_autonomy_tick
    jr._run_autonomy_tick = trap_autonomy
    try:
        job = {"id": "adhoc-1", "name": "Ad hoc"}
        payload = {"instruction": "do a thing"}  # no workspace_heartbeat
        # We can't easily run the real dispatcher here without the app — just
        # verify we didn't divert to autonomy. We stub handle_message via main.
        import types
        fake_orch = types.SimpleNamespace()

        async def fake_handle_message(**kwargs):
            called["dispatcher_hit"] = True
            return []
        fake_orch.handle_message = fake_handle_message

        import app.main as app_main
        original_orch = getattr(app_main, "_orchestrator", None)
        app_main._orchestrator = fake_orch
        try:
            asyncio.run(jr._run_agent_task(job, payload))
        finally:
            if original_orch is not None:
                app_main._orchestrator = original_orch
    finally:
        jr._run_autonomy_tick = original

    assert called["autonomy"] is False, \
        "non-heartbeat agent_task wrongly routed through autonomy"
    assert called.get("dispatcher_hit"), \
        "non-heartbeat agent_task did not reach the dispatcher handle_message"


@test("chat_orchestration.handle_message accepts role='autonomy'")
def test_handle_message_accepts_role():
    import inspect
    from app.services.chat_orchestration import ChatOrchestrator
    sig = inspect.signature(ChatOrchestrator.handle_message)
    assert "role" in sig.parameters, "handle_message missing 'role' param"
    assert "autonomy_directive_path" in sig.parameters, \
        "handle_message missing 'autonomy_directive_path' param"


@test("chat_fast_stream accepts role='autonomy' and autonomy_directive_path")
def test_chat_fast_stream_signature():
    import inspect
    from app.services.claude_service import ClaudeService
    sig = inspect.signature(ClaudeService.chat_fast_stream)
    assert "role" in sig.parameters, "chat_fast_stream missing 'role' param"
    assert "autonomy_directive_path" in sig.parameters, \
        "chat_fast_stream missing 'autonomy_directive_path' param"


@test("autonomy tick registry — cancel_autonomy_task exists and is wired")
def test_autonomy_cancel_registry():
    from app.services import job_runner as jr
    assert hasattr(jr, "_active_autonomy_tasks"), \
        "job_runner missing _active_autonomy_tasks registry"
    assert callable(getattr(jr, "cancel_autonomy_task", None)), \
        "job_runner missing cancel_autonomy_task()"
    assert callable(getattr(jr, "get_active_autonomy_task", None)), \
        "job_runner missing get_active_autonomy_task()"


@test("cancel_worker_task_global routes autonomy-* task_ids to autonomy registry")
def test_cancel_worker_task_global_routes_autonomy():
    import asyncio
    from app.services import job_runner as jr
    from app.services.chat_orchestration import ChatOrchestrator

    captured = {}

    async def fake_cancel(task_id):
        captured["task_id"] = task_id
        return True

    original = jr.cancel_autonomy_task
    jr.cancel_autonomy_task = fake_cancel
    try:
        orch = ChatOrchestrator(claude_service=None)  # not used by this code path
        result = asyncio.run(orch.cancel_worker_task_global("autonomy-job42-abcd1234"))
    finally:
        jr.cancel_autonomy_task = original

    assert result is True, "cancel_worker_task_global should return True for autonomy task"
    assert captured.get("task_id") == "autonomy-job42-abcd1234", \
        "autonomy task_id was not forwarded to cancel_autonomy_task"


if __name__ == "__main__":
    print("=" * 60)
    print("Voxyflow autonomy heartbeat smoke tests")
    print("=" * 60)

    test_autonomy_prompt_shape()
    test_prompts_differ()
    test_default_directive_not_empty()
    test_job_dict_flag_both_places()
    test_heartbeat_routing()
    test_non_heartbeat_stays_on_dispatcher()
    test_handle_message_accepts_role()
    test_chat_fast_stream_signature()
    test_autonomy_cancel_registry()
    test_cancel_worker_task_global_routes_autonomy()

    print()
    print("=" * 60)
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print("=" * 60)
    sys.exit(0 if FAIL_COUNT == 0 else 1)
