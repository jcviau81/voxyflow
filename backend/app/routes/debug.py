"""Debug introspection routes.

POST /api/debug/context — dump the full system prompt that Voxy sees for a
given chat context + sample user message. Replicates the prompt-construction
flow from ``claude_service.chat_fast_stream`` / ``chat_deep_stream`` up to
(but not including) the LLM call. No side effects, no history append.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import SYSTEM_MAIN_PROJECT_ID
from app.services.chat_id_utils import resolve_chat_id
from app.services.claude_service import _make_cached_system
from app.services.llm.model_utils import _inject_no_think
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/debug", tags=["debug"])


class DebugContextRequest(BaseModel):
    user_message: str = Field(..., description="Sample user message to probe the prompt with")
    layer: str = Field("fast", description="fast | deep")
    project_id: Optional[str] = None
    card_id: Optional[str] = None
    chat_level: Optional[str] = None
    chat_id: Optional[str] = None


def _flatten_system(system: Any) -> str:
    """Render the anthropic content-block list or plain string as a single string."""
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        out = []
        for block in system:
            if isinstance(block, dict):
                txt = block.get("text", "")
                cached = bool(block.get("cache_control"))
                marker = "  <-- [CACHED]" if cached else ""
                out.append(f"{txt}{marker}")
            else:
                out.append(str(block))
        return "\n\n".join(out)
    return str(system)


@router.post("/context")
async def dump_context(req: DebugContextRequest):
    """Return the full system prompt Voxy sees for the given (project, card, layer, message).

    Pure read — no chat history mutation, no LLM call. Use this to diagnose
    attribution, retrieved-fragment pertinence, and live-state wiring.
    """
    layer = (req.layer or "fast").lower()
    if layer not in ("fast", "deep"):
        raise HTTPException(400, "layer must be 'fast' or 'deep'")

    # Derive canonical project_id + chat_level like main.py WS handler.
    project_id = req.project_id
    card_id = req.card_id
    chat_level = req.chat_level or "general"
    if card_id:
        chat_level = "card"
    elif project_id:
        if chat_level == "general":
            chat_level = "project" if project_id != SYSTEM_MAIN_PROJECT_ID else "general"
    else:
        project_id = SYSTEM_MAIN_PROJECT_ID
        chat_level = "general"

    chat_id, _, _ = resolve_chat_id(
        project_id, card_id, req.chat_id, log_context="debug /context"
    )

    # Lazy imports to avoid circular imports at module load time.
    from app.main import _orchestrator, _claude_service

    claude = _claude_service
    personality = get_personality_service()
    memory = get_memory_service()

    project_context, card_context, project_names = await _orchestrator._resolve_context(
        project_id=project_id, card_id=card_id, chat_level=chat_level,
    )

    # ---- Replicate chat_{fast|deep}_stream prompt construction ----
    if layer == "fast":
        use_native = claude.fast_client_type == "anthropic"
        use_cli = claude.fast_client_type == "cli"
        model = claude.fast_model
        fast_layers = (0, 1)
        if memory._has_extractable_signal([{"content": req.user_message, "role": "user"}]):
            fast_layers = (0, 1, 2)
        memory_context = memory.build_memory_context(
            project_name=(project_context or {}).get("title"),
            project_id=project_id,
            include_long_term=False,
            include_daily=True,
            query=req.user_message,
            budget=600,
            layers=fast_layers,
        )
        base_prompt = personality.build_fast_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            native_tools=("cli_mcp" if use_cli else use_native),
        )
        layers_used = list(fast_layers)
        budget = 600
    else:
        use_native = claude.deep_client_type == "anthropic"
        use_cli = claude.deep_client_type == "cli"
        model = claude.deep_model
        memory_context = memory.build_memory_context(
            project_name=(project_context or {}).get("title"),
            project_id=project_id,
            include_long_term=True,
            include_daily=True,
            query=req.user_message,
            budget=1500,
            layers=(0, 1, 2),
        )
        base_prompt = personality.build_deep_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            is_chat_responder=True,
            native_tools=("cli_mcp" if use_cli else use_native),
        )
        layers_used = [0, 1, 2]
        budget = 1500

    # Ambient blocks — reuse the same helper the layer runners use so what
    # we dump matches what Voxy actually gets on the next turn.
    live_state_block = ""
    worker_events_block = ""
    try:
        from app.services.orchestration.layer_runners import _compute_ambient_blocks
        # Use the live orchestrator worker_pools, but pass a synthetic session_id
        # of None so count_active_for_chat returns 0 unless the caller passes one.
        live_state_block, worker_events_block = await _compute_ambient_blocks(
            worker_pools=getattr(_orchestrator, "_worker_pools", {}) or {},
            session_id=None,
            chat_id=chat_id,
            project_id=project_id,
        )
    except Exception as e:
        logger.debug("debug/context ambient blocks failed: %s", e)

    wc_list = await claude._load_worker_classes_context()

    dynamic_context = personality.build_dynamic_context_block(
        chat_level=chat_level,
        project=project_context,
        card=card_context,
        project_names=project_names,
        memory_context=memory_context,
        worker_classes=wc_list,
        live_state=live_state_block or None,
        worker_events=worker_events_block or None,
    )

    dynamic_parts: list[str] = []
    if dynamic_context:
        dynamic_parts.append(dynamic_context)
    dynamic_parts.append(
        f"IMPORTANT: You are running on model '{model}'. "
        f"This is your actual model. If asked, say you are {model}."
    )

    system_param = _make_cached_system(
        base_prompt, dynamic_parts,
        is_anthropic=(use_native or use_cli),
    )
    # Anthropic returns a list of content blocks; flatten for display.
    system_prompt_text = _flatten_system(system_param)
    system_prompt_text = _inject_no_think(system_prompt_text, model)

    return {
        "layer": layer,
        "model": model,
        "chat_id": chat_id,
        "chat_level": chat_level,
        "project_id": project_id,
        "card_id": card_id,
        "client_type": claude.fast_client_type if layer == "fast" else claude.deep_client_type,
        "memory": {
            "layers": layers_used,
            "budget_tokens": budget,
            "context": memory_context or "",
        },
        "ambient": {
            "live_state": live_state_block or "",
            "worker_events": worker_events_block or "",
        },
        "prompt": {
            "base": base_prompt,
            "dynamic_parts": dynamic_parts,
            "dynamic_context": dynamic_context or "",
            "system_full": system_prompt_text,
            "base_chars": len(base_prompt),
            "dynamic_chars": sum(len(p) for p in dynamic_parts),
            "total_chars": len(system_prompt_text),
        },
    }
