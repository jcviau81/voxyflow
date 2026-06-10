"""Personality Service — loads personality files and builds context-isolated system prompts.

Reads personality configuration from settings.json (saved via Settings UI) and
applies custom_instructions, environment_notes, tone, and warmth to system prompts.

IMPORTANT: Personality files are loaded from voxyflow/personality/ by default,
NOT from the OpenClaw workspace. This prevents context leakage between systems.

This module is the public FACADE. The implementation lives in the
``app.services.personality`` package, split by audience:

- ``personality.loader``                — file/settings loading + caching
- ``personality.context_blocks``        — chat-init + dynamic context builders
- ``personality.delegate_instructions`` — per-provider delegate/tool instructions
- ``personality.dispatcher_prompts``    — dispatcher/autonomy system prompts
- ``personality.worker_prompts``        — worker/agent prompts
- ``personality.ambient_blocks``        — module-level ambient context blocks

All existing import paths (``from app.services.personality_service import X``)
keep working via the re-exports below.
"""

import logging
from typing import Optional

# Re-exported for backward compatibility — these names were previously defined
# at module level here and may be referenced by callers/tests.
from app.services.personality.loader import (  # noqa: F401
    _CACHE_TTL,
    AGENTS_FILE,
    ARCHITECTURE_FILE,
    DISPATCHER_FILE,
    IDENTITY_FILE,
    PERSONALITY_DIR,
    PROACTIVE_FILE,
    SOUL_FILE,
    USER_FILE,
    VOXYFLOW_DIR,
    WORKER_FILE,
    PersonalityLoaderMixin,
)
from app.services.personality.context_blocks import ContextBlocksMixin
from app.services.personality.delegate_instructions import DelegateInstructionsMixin
from app.services.personality.dispatcher_prompts import (  # noqa: F401
    LANGUAGE_INSTRUCTIONS,
    TONE_MODIFIERS,
    WARMTH_MODIFIERS,
    DispatcherPromptsMixin,
)
from app.services.personality.worker_prompts import WorkerPromptsMixin

# Ambient context blocks (Live state + Worker activity + Session handoff) —
# re-exported so orchestration/layer_runners.py and tests need no changes.
from app.services.personality.ambient_blocks import (  # noqa: F401
    _PER_FINDING_MAX_CHARS,
    _PER_POINTER_MAX_CHARS,
    _PER_WORKER_FINDINGS_MAX,
    _STATUS_GLYPH,
    _WORKER_BLOCK_MAX_CHARS,
    _fmt_delta_seconds,
    _summarize_finding_dict,
    build_live_state_block,
    build_session_handoff_block,
    build_worker_events_block,
)

logger = logging.getLogger(__name__)


class PersonalityService(
    PersonalityLoaderMixin,
    ContextBlocksMixin,
    DelegateInstructionsMixin,
    DispatcherPromptsMixin,
    WorkerPromptsMixin,
):
    """Loads and caches personality files to build system prompts for Claude API calls."""


_personality_service: Optional[PersonalityService] = None


def get_personality_service() -> PersonalityService:
    global _personality_service
    if _personality_service is None:
        _personality_service = PersonalityService()
    return _personality_service
