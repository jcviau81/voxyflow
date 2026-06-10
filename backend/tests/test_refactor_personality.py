"""Refactor guard for the personality_service split (facade + mixins package).

The golden file ``tests/refactor_personality_golden.json`` was captured by
running ``_build_outputs()`` against the PRE-split monolithic
``personality_service.py``. After the split into ``app/services/personality/``
mixins, every prompt must remain byte-identical.

All environment-dependent inputs (personality files, settings.json, ports,
PID, sandbox dir, wall clock) are stubbed so the outputs are deterministic.
"""

import json
from pathlib import Path
from unittest import mock

GOLDEN_PATH = Path(__file__).parent / "refactor_personality_golden.json"

_FAKE_SETTINGS = {
    "personality": {
        "bot_name": "TestBot",
        "custom_instructions": "CUSTOM-INSTRUCTIONS",
        "environment_notes": "ENV-NOTES",
        "tone": "balanced",
        "warmth": "warm",
        "preferred_language": "fr",
    },
    "user_name": "TestUser",
}

_WS = {
    "id": "ws-0001",
    "title": "Golden Workspace",
    "description": "A workspace used for the refactor golden test",
    "tech_stack": "Python/FastAPI",
    "github_url": "https://github.com/example/golden",
    "cards": [
        {"title": "Done card", "status": "done"},
        {"title": "Running card", "status": "in-progress"},
        {"title": "Todo card", "status": "todo"},
        {"title": "Backlog card A", "status": "backlog"},
        {"title": "Backlog card B", "status": "backlog"},
        {"title": "Archived card", "status": "archived"},
    ],
}

_CARD = {
    "id": "card-0001",
    "title": "Golden Card",
    "status": "in-progress",
    "priority": "high",
    "agent_type": "developer",
    "description": "Implement the golden feature",
    "assignee": "TestUser",
    "checklist_items": [
        {"text": "step 1", "done": True},
        {"text": "step 2", "done": False},
    ],
}

_WORKER_EVENTS = [
    {
        "status": "success",
        "intent": "research_topic",
        "task_id": "task-123",
        "completion": {
            "summary": "Researched the topic and compiled findings.",
            "findings": [
                "Finding one",
                {"text": "Finding two (dict)"},
                {"weird_key": "fallback json"},
            ],
            "pointers": [
                {"label": "full report", "offset": 0, "length": 2048},
                "raw-pointer-string",
            ],
            "next_step": "Review the report and ack the artifact.",
        },
    },
    {
        "status": "failed",
        "intent": "deploy_app",
        "task_id": "task-456",
        "summary_line": "Deploy failed: port collision.",
    },
]


def _make_service():
    from app.services.personality_service import PersonalityService

    svc = PersonalityService()
    # Stub all file loaders + settings so output is environment-independent.
    svc.load_soul = lambda: "SOUL-TEXT"
    svc.load_user = lambda: "USER-TEXT"
    svc.load_identity = lambda: "IDENTITY-TEXT"
    svc.load_agents = lambda: "AGENTS-TEXT"
    svc.load_dispatcher = lambda: "DISPATCHER-TEXT"
    svc.load_worker = lambda: "WORKER-RULES-TEXT"
    svc.load_architecture = lambda: "ARCHITECTURE-TEXT"
    svc.load_proactive = lambda: "PROACTIVE-TEXT"
    svc._load_settings = lambda: _FAKE_SETTINGS
    # Tool listing delegates to the registry — stub it so the golden does not
    # depend on concurrent registry changes.
    svc._build_tool_section = lambda names, chat_level="general": "TOOL-SECTION"
    return svc


class _FakeConfig:
    voxyflow_backend_port = 8000
    voxyflow_frontend_port = 5173


def _build_outputs() -> dict[str, str]:
    svc = _make_service()
    out: dict[str, str] = {}

    with mock.patch("app.config.get_settings", return_value=_FakeConfig()), \
         mock.patch("os.getpid", return_value=99999), \
         mock.patch("app.config.VOXYFLOW_SANDBOX_DIR", Path("/tmp/golden-sandbox")), \
         mock.patch(
             "app.services.time_context.format_now_block",
             return_value="NOW-BLOCK",
         ):
        # Chat init blocks
        out["general_init"] = svc.build_general_chat_init()
        out["workspace_init"] = svc.build_workspace_chat_init(_WS)
        out["card_init"] = svc.build_card_chat_init(_WS, _CARD)

        # Context-isolated static prompts
        out["general_prompt"] = svc.build_general_prompt()
        out["workspace_prompt"] = svc.build_workspace_prompt(_WS)
        out["card_prompt"] = svc.build_card_prompt(
            _WS, _CARD, {"system_prompt": "PERSONA-PROMPT"}
        )

        # Legacy generic builder (tone/warmth/language modifiers)
        out["system_prompt"] = svc.build_system_prompt(
            "BASE-TASK",
            include_memory_context="MEMORY-CONTEXT",
            agent_persona="AGENT-PERSONA",
        )

        # Dispatcher prompts — every native_tools mode
        out["dispatcher_fast_xml"] = svc.build_dispatcher_prompt(
            tier="fast", native_tools=False
        )
        out["dispatcher_fast_native"] = svc.build_dispatcher_prompt(
            tier="fast", native_tools=True
        )
        out["dispatcher_fast_cli_mcp"] = svc.build_dispatcher_prompt(
            tier="fast", native_tools="claude_cli_mcp"
        )
        out["dispatcher_deep_codex_ws"] = svc.build_dispatcher_prompt(
            tier="deep",
            chat_level="workspace",
            workspace=_WS,
            native_tools="codex_mcp",
        )
        out["dispatcher_card"] = svc.build_dispatcher_prompt(
            tier="fast",
            chat_level="card",
            workspace=_WS,
            card=_CARD,
            agent_persona={"system_prompt": "PERSONA-PROMPT"},
            native_tools="claude_cli_mcp",
        )

        # Compat wrappers
        out["fast_prompt"] = svc.build_fast_prompt(native_tools="claude_cli_mcp")
        out["deep_prompt_responder"] = svc.build_deep_prompt(
            is_chat_responder=True, native_tools=True
        )
        out["deep_prompt_static"] = svc.build_deep_prompt(
            chat_level="workspace", workspace=_WS, is_chat_responder=False
        )

        # Autonomy prompts
        out["autonomy_xml"] = svc.build_autonomy_prompt(
            _WS, "/tmp/directive.md", native_tools=False
        )
        out["autonomy_cli_mcp"] = svc.build_autonomy_prompt(
            _WS, "/tmp/directive.md", native_tools="claude_cli_mcp"
        )
        out["autonomy_codex"] = svc.build_autonomy_prompt(
            None, "/tmp/directive.md", native_tools="codex_mcp"
        )

        # Worker prompts
        out["worker_prompt_card"] = svc.build_worker_prompt(
            chat_level="card", workspace=_WS, card=_CARD
        )
        out["worker_prompt_ws"] = svc.build_worker_prompt(
            chat_level="workspace", workspace=_WS
        )
        out["worker_prompt_general"] = svc.build_worker_prompt()
        out["agent_prompt"] = svc.build_agent_prompt(
            "AGENT-PERSONA", "TASK-CONTEXT", memory_context="MEMORY-CONTEXT"
        )

        # Dynamic context block (wall clock stubbed via format_now_block)
        out["dynamic_context_ws"] = svc.build_dynamic_context_block(
            chat_level="workspace",
            workspace=_WS,
            memory_context="MEM-FRAGMENTS",
            active_workers_context="WORKERS-STATUS",
            worker_classes=[
                {"name": "researcher", "intent_patterns": ["research", "web", "scrape", "x"]},
                {"name": "coder"},
            ],
            live_state="LIVE-STATE\n",
            worker_events="WORKER-EVENTS\n",
            session_handoff="SESSION-HANDOFF\n",
        )
        out["dynamic_context_card"] = svc.build_dynamic_context_block(
            chat_level="card", workspace=_WS, card=_CARD
        )

    # Ambient module-level builders (deterministic inputs only)
    from app.services.personality_service import (
        build_live_state_block,
        build_session_handoff_block,
        build_worker_events_block,
    )

    out["worker_events_block"] = build_worker_events_block(_WORKER_EVENTS)
    out["worker_events_empty"] = build_worker_events_block([])
    out["live_state_block"] = build_live_state_block(
        active_workers=2,
        next_job={"name": "nightly-brief", "eta_seconds": 5400},
        pending_actions=0,
        cards_updated_today=3,
        last_user_turn_ago="2h05m",
        running_worker_intents=["research_topic", "deploy_app", "summarize", "extra"],
    )
    out["session_handoff_empty"] = build_session_handoff_block([])

    return out


def test_prompts_byte_identical_to_pre_split_golden():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    outputs = _build_outputs()
    assert set(outputs.keys()) == set(golden.keys())
    for key, expected in golden.items():
        assert outputs[key] == expected, (
            f"Prompt '{key}' drifted from the pre-split golden output"
        )


def test_facade_reexports_and_composition():
    import app.services.personality_service as ps
    from app.services.personality import ambient_blocks
    from app.services.personality.context_blocks import ContextBlocksMixin
    from app.services.personality.delegate_instructions import DelegateInstructionsMixin
    from app.services.personality.dispatcher_prompts import DispatcherPromptsMixin
    from app.services.personality.loader import PersonalityLoaderMixin
    from app.services.personality.worker_prompts import WorkerPromptsMixin

    # Ambient builders re-exported by the facade are the same objects.
    assert ps.build_session_handoff_block is ambient_blocks.build_session_handoff_block
    assert ps.build_worker_events_block is ambient_blocks.build_worker_events_block
    assert ps.build_live_state_block is ambient_blocks.build_live_state_block

    # The facade class composes all mixins.
    for mixin in (
        PersonalityLoaderMixin,
        ContextBlocksMixin,
        DelegateInstructionsMixin,
        DispatcherPromptsMixin,
        WorkerPromptsMixin,
    ):
        assert issubclass(ps.PersonalityService, mixin)

    # Singleton accessor unchanged.
    svc = ps.get_personality_service()
    assert svc is ps.get_personality_service()
    assert isinstance(svc, ps.PersonalityService)
