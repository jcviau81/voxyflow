"""Result formatting helpers — previews, card-facing rendering, short titles.

Pure functions, zero pool state. Extracted verbatim from worker_pool.py.
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Result preview helpers — the artifact file is the canonical blob store;
# everything else gets a short preview + artifact_path reference.
# ---------------------------------------------------------------------------
PREVIEW_CHARS = 500          # for worker session store + session timeline previews
DISPATCHER_PREVIEW_CHARS = 10_000  # read_artifact default page size
WS_RESULT_CHARS = 2_000     # for the task:completed WS event to the frontend


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """Return the first *limit* chars of *text*, with a truncation marker if cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated — {len(text):,} chars total ...]"


def _format_result_for_card(text: str) -> str:
    """Convert raw LLM result to clean human-readable text for card injection.

    If the result is a JSON object/array, flatten it into readable key: value lines
    instead of injecting raw JSON into the card description.
    """
    stripped = text.strip()
    if stripped.startswith('```'):
        inner = stripped.split('```', 2)
        if len(inner) >= 2:
            block = inner[1]
            if block.startswith('json'):
                block = block[4:]
            stripped = block.strip()

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text

    if isinstance(parsed, dict):
        lines = []
        for k, v in parsed.items():
            if isinstance(v, list):
                lines.append(f'**{k}:**')
                for item in v:
                    lines.append(f'  - {item}')
            elif isinstance(v, dict):
                lines.append(f'**{k}:** {json.dumps(v)}')
            else:
                lines.append(f'**{k}:** {v}')
        return '\n'.join(lines)
    elif isinstance(parsed, list):
        return '\n'.join(f'- {item}' for item in parsed)
    else:
        return str(parsed)


def _make_short_title(intent: str, summary: str) -> str:
    """Derive a concise card title (≤80 chars) from intent and summary.

    Uses the first sentence of summary if available, otherwise shortens intent.
    """
    # If intent is a short action keyword, use it as prefix
    source = summary or intent
    if not source:
        return "Worker task"

    # Take the first sentence, clause, or line
    for sep in (".", "\n", ":", "—", " - ", ","):
        idx = source.find(sep)
        if 10 < idx < 80:
            source = source[:idx]
            break

    # Truncate to 80 chars at a word boundary
    if len(source) > 80:
        source = source[:77].rsplit(" ", 1)[0] + "…"

    return source.strip() or "Worker task"
