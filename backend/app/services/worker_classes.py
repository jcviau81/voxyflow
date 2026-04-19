"""Default worker classes — intent → model/provider routing defaults.

Returned when nothing is saved in the settings DB yet. Must stay in sync
with frontend defaults in Settings → Models. Pure service constants so
``services/llm/worker_class_resolver`` does not have to import from
``app.routes.models``.
"""

from __future__ import annotations


DEFAULT_WORKER_CLASSES = [
    {
        "id": "00000000-0000-0000-0000-000000000006",
        "name": "Architecture",
        "description": "System design, structural decisions, cross-cutting architecture",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        "intent_patterns": ["architect", "architecture", "system_design", "structural", "redesign"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000005",
        "name": "Complex Coding",
        "description": "Multi-file changes, major refactors, complex features",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        "intent_patterns": ["multi_file", "multifile", "major_refactor", "complex_implement", "complex_feature", "large_refactor"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Coding",
        "description": "Code writing, debugging, refactoring, code review",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-sonnet-4-6",
        # Tightened: 'code'/'fix'/'test' alone match too broadly (QR code,
        # fix typo, test plan). Use multi-word phrases or unambiguous verbs.
        "intent_patterns": ["debug", "refactor", "implement", "unit test", "fix bug", "code review", "write code"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "Research",
        "description": "Deep research, analysis, multi-step investigation",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-opus-4-7",
        # Dropped 'explain' (too broad — any "explain X" task matched).
        "intent_patterns": ["research", "investigate", "analyze", "compare alternatives", "feasibility", "fact check"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000004",
        "name": "Creative",
        "description": "Writing, brainstorming, ideation, narrative",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-sonnet-4-6",
        # Dropped standalone 'write'/'draft' (matched "write code", "draft email").
        "intent_patterns": ["brainstorm", "brainstorming", "creative writing", "story", "narrative", "ideation"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Quick",
        "description": "Fast, lightweight tasks — summaries, simple Q&A, formatting",
        "endpoint_id": "",
        "provider_type": "cli",
        "model": "claude-haiku-4-5-20251001",
        # Tightened: dropped 'quick','short','simple','format' (matched stray
        # words in delivery-format text like "Quick-start steps").
        "intent_patterns": ["summarize", "summarization", "tldr", "reformat", "rephrase"],
    },
]
