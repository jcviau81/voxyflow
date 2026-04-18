"""Default worker classes — intent → model/provider routing defaults.

Returned when nothing is saved in the settings DB yet. Must stay in sync
with frontend defaults in Settings → Models. Pure service constants so
``services/llm/worker_class_resolver`` does not have to import from
``app.routes.models``.
"""

from __future__ import annotations


DEFAULT_WORKER_CLASSES = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Quick",
        "description": "Fast, lightweight tasks — summaries, simple Q&A, formatting",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-haiku-4-5-20251001",
        "intent_patterns": ["summarize", "format", "quick", "simple", "short"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Coding",
        "description": "Code writing, debugging, refactoring, code review",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-sonnet-4-6",
        "intent_patterns": ["code", "debug", "refactor", "implement", "fix", "test"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "Research",
        "description": "Deep research, analysis, multi-step investigation",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        "intent_patterns": ["research", "analyze", "investigate", "compare", "explain"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000004",
        "name": "Creative",
        "description": "Writing, brainstorming, ideation, narrative",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-sonnet-4-6",
        "intent_patterns": ["write", "brainstorm", "creative", "story", "draft"],
    },
]
