"""Memory-service constants and helpers — shared between the main service and its mixins.

Extracted so that ``memory_extraction.py`` and ``memory_context.py`` can
import constants + lightweight helpers without pulling in the full
``MemoryService`` class (which would create a circular import since
memory_service uses the mixins as its base classes).

Exports:
  GLOBAL_COLLECTION, MEMORY_FILE, MEMORY_DIR, WORKSPACE_DIR
  VALID_TYPES, VALID_SOURCES, VALID_IMPORTANCE
  _classify_text, _format_messages_for_extraction, _slugify, _project_collection
  _MEMORY_EXTRACTION_SYSTEM, _MEMORY_EXTRACTION_USER_TEMPLATE
"""
from __future__ import annotations

import os
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKSPACE_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.voxyflow"))) / "personality"
MEMORY_FILE = WORKSPACE_DIR / "MEMORY.md"
MEMORY_DIR = WORKSPACE_DIR / "memory"

CHROMA_PERSIST_DIR = os.path.expanduser("~/.voxyflow/chroma")
MIGRATION_FLAG_FILE = Path(CHROMA_PERSIST_DIR) / ".memory_migrated"

GLOBAL_COLLECTION = "memory-global"

VALID_TYPES = {"decision", "preference", "lesson", "fact", "context"}
VALID_SOURCES = {"chat", "manual", "auto-extract"}
VALID_IMPORTANCE = {"high", "medium", "low"}

# ---------------------------------------------------------------------------
# Keyword patterns for auto-extraction (FALLBACK heuristic — used when LLM fails)
# ---------------------------------------------------------------------------

_DECISION_PATTERNS = [
    re.compile(r"(?:I|we|let'?s)\s+(?:decided?|chose?|go(?:ing)?\s+with|picked|settled\s+on)", re.I),
    re.compile(r"(?:the\s+)?decision\s+(?:is|was)\s+to", re.I),
    re.compile(r"(?:I|we)\s+(?:will|'ll)\s+(?:use|go\s+with|stick\s+with)", re.I),
]

_PREFERENCE_PATTERNS = [
    re.compile(r"(?:I|we)\s+prefer", re.I),
    re.compile(r"(?:I|we)\s+(?:like|want|need)\s+(?:to\s+)?(?:use|have|keep)", re.I),
    re.compile(r"(?:always|never|don'?t)\s+(?:use|do|want)", re.I),
]

_BUG_PATTERNS = [
    re.compile(r"(?:bug|issue|problem|error|crash|broken|fix(?:ed)?)\b", re.I),
    re.compile(r"(?:doesn'?t|does\s+not|isn'?t|is\s+not)\s+work", re.I),
]

_TECH_PATTERNS = [
    re.compile(r"(?:using|switched?\s+to|migrated?\s+to|installed?|upgraded?)\s+\w+", re.I),
    re.compile(r"(?:stack|framework|library|tool|dependency|version)\b", re.I),
]

_LESSON_PATTERNS = [
    re.compile(r"(?:lesson|learned|takeaway|insight|realized?|turns?\s+out)\b", re.I),
    re.compile(r"(?:important|remember|note\s+to\s+self)\b", re.I),
]


def _classify_text(text: str) -> tuple[str, str]:
    """Classify text into (type, importance) using keyword heuristics.

    Fallback used when LLM extraction fails.
    Returns one of the VALID_TYPES and VALID_IMPORTANCE values.
    """
    # Check patterns in priority order
    for pat in _DECISION_PATTERNS:
        if pat.search(text):
            return "decision", "high"

    for pat in _BUG_PATTERNS:
        if pat.search(text):
            return "fact", "high"

    for pat in _PREFERENCE_PATTERNS:
        if pat.search(text):
            return "preference", "medium"

    for pat in _TECH_PATTERNS:
        if pat.search(text):
            return "fact", "medium"

    for pat in _LESSON_PATTERNS:
        if pat.search(text):
            return "lesson", "high"

    return "context", "low"


# ---------------------------------------------------------------------------
# LLM extraction prompt (B1)
# ---------------------------------------------------------------------------

_MEMORY_EXTRACTION_SYSTEM = """\
You are a memory extraction assistant for a project management tool. Your job is to analyze a \
short block of conversation messages and extract information worth remembering long-term.

## What to extract
- **decision**: A concrete choice that was made ("we'll use Redis", "going with Tailwind CSS")
- **preference**: A stated user preference or style guideline ("I prefer dark mode", "always use async")
- **fact**: A relevant technical fact, tool version, architecture detail, or bug/fix encountered
- **lesson**: A learned insight, hard-won takeaway, or "note to self"
- **skip**: Everything else — greetings, filler, vague statements, chitchat, questions without answers

## Language
The conversation may be in French, English, or franglais (FR/EN mix). Handle all naturally. \
Extract the memory content in the same language it was expressed.

## Output format
Respond with a JSON array ONLY — no markdown, no explanation, no code fence.
Each item in the array must be a JSON object with exactly these fields:
  - "content": string — the memory text, self-contained (no pronouns without referent)
  - "type": one of "decision" | "preference" | "fact" | "lesson" | "skip"
  - "importance": one of "high" | "medium" | "low"
  - "confidence": float between 0.0 and 1.0

## Rules
- Only include items with confidence > 0.7 that have real long-term value
- Skip pleasantries, repetitive content, questions, and anything too vague to be useful
- One memory per distinct piece of information (don't bundle multiple facts)
- Keep "content" concise but complete — someone reading it later should understand it without context
- If nothing is worth remembering, return an empty array: []

## Entity Extraction (Knowledge Graph)
Also extract named entities and relationships mentioned in the conversation:
- entities: People, technologies, tools, components, concepts, or decisions discussed
- relationships: How they relate (e.g. "project uses Redis", "auth depends on JWT")

Return a JSON object (not an array) with two keys:
  - "memories": the array of memory objects described above
  - "entities": an array of entity objects, each with:
    - "name": entity name (e.g. "Redis", "auth-service")
    - "type": one of "person" | "technology" | "component" | "concept" | "decision"
    - "relationships": array of {"predicate": string, "target": string, "target_type": string}

If no entities are found, set "entities": [].
If no memories are found, set "memories": [].
"""

_MEMORY_EXTRACTION_USER_TEMPLATE = """\
Extract memories from the following conversation messages:

{messages_block}
"""


def _format_messages_for_extraction(messages: list[dict]) -> str:
    """Format a list of message dicts into a readable block for the LLM."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "").strip()
        if content and role != "SYSTEM":
            lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def _slugify(name: str) -> str:
    """Convert a project name to a collection-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "default"


def _project_collection(project_id: str) -> str:
    """Return the collection name for a project (keyed by project_id, not slug).

    Using the project UUID as the collection key prevents cross-project
    context leaks that happened when slugs collided (e.g. "main" matching
    both the generic chat and the "system-main" project).
    """
    return f"memory-project-{project_id}"


