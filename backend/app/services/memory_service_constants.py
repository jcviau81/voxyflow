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

VALID_TYPES = {"decision", "preference", "lesson", "fact", "context", "procedure"}
VALID_SOURCES = {"chat", "manual", "auto-extract", "worker_summary", "worker"}
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


# Patterns that justify classifying a memory as importance="high". Matches
# decisions, deadlines, root-cause fixes, absolute preferences, compliance.
# If an LLM returns `importance=high` but the text matches NONE of these,
# we downgrade to medium — prevents jokes and rhetoric from landing in L1.
_HIGH_IMPORTANCE_SIGNALS = [
    re.compile(r"\b(?:decision|decided?|chose|choisi|going\s+with|we['’]?ll\s+use|we['’]?re\s+using|"
               r"on\s+va\s+(?:utiliser|prendre|faire)|on\s+prend|on\s+choisit|"
               r"switched?\s+to|migrated?\s+to|"
               r"root[- ]cause|fixed\s+(?:by|via|the)|bug\s+confirmé|solved)\b", re.I),
    re.compile(r"\b(?:deadline|due\s+(?:by|on)|freeze|release|launch|ship(?:ped|ping)?|"
               r"échéance|gel\s+des?\s+merges?|sortie\s+prévue)\b", re.I),
    re.compile(r"\b(?:always|never|must(?:\s+not)?|don['’]?t\s+ever|jamais|toujours|"
               r"obligatoirement|interdit|impératif)\b", re.I),
    re.compile(r"\b(?:CVE|security\s+(?:risk|bug|hole)|data\s+loss|breach|leak|"
               r"compliance|GDPR|RGPD|faille)\b", re.I),
    re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),  # ISO date
]


def _high_importance_justified(text: str) -> bool:
    """Return True iff the text contains at least one strong-signal pattern.

    Used as a guard after LLM extraction — when the model tags a line as
    `high` but the line is actually banter or a soft remark, this gate
    fires False and the caller downgrades importance to `medium`.
    """
    t = text or ""
    for pat in _HIGH_IMPORTANCE_SIGNALS:
        if pat.search(t):
            return True
    return False


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
- **procedure**: A reusable "how to do X" pattern — ordered steps for a recurring workflow \
("how to restart the backend", "how to deploy", "how to debug Chroma drift"). Content MUST \
start with "How to {task}:" and list concrete ordered steps. Extract only when the trace is \
complete enough to be re-executed later. One-off commands are NOT procedures — they're facts.
- **skip**: Everything else — greetings, filler, jokes, off-topic banter, personal anecdotes \
unrelated to the work, vague statements, chitchat, questions without answers, conversational \
closings ("dis-moi", "let me know", "on continue"), rhetorical prompts

## Language
The conversation may be in French, English, or franglais (FR/EN mix). Handle all naturally. \
Extract the memory content in the same language it was expressed.

## Output format
Respond with a JSON array ONLY — no markdown, no explanation, no code fence.
Each item in the array must be a JSON object with exactly these fields:
  - "content": string — the memory text, self-contained (no pronouns without referent)
  - "type": one of "decision" | "preference" | "fact" | "lesson" | "procedure" | "skip"
  - "importance": one of "high" | "medium" | "low"
  - "confidence": float between 0.0 and 1.0
  - "speaker": one of "user" | "assistant" — who uttered the source statement
    (look at the [USER]/[ASSISTANT] tag of the message the memory is extracted from)

## Importance calibration (STRICT)
`importance` is NOT a mood signal. Use this rubric:

- **high** — reserve for one of:
    * an explicit decision or architecture choice ("we're going with X instead of Y")
    * a deadline, date, or release constraint
    * a root-cause bug diagnosis or a confirmed fix
    * a stated strong preference ("always / never / must / don't ever")
    * a compliance / security / data-loss risk
  If the sentence doesn't clearly fit one of these slots, it is NOT high.

- **medium** — useful technical facts, tool versions, naming conventions, project status
  updates, and mild preferences. This is the default for anything real but not critical.

- **low** — incidental detail, single data point, background context.

Jokes, banter, asides, metaphors, emoji-heavy reactions, and personal anecdotes
unrelated to the project must be classified **skip** — not "high", not "medium", not "low".

## Rules
- Only include items with confidence > 0.7 that have real long-term value
- Skip pleasantries, repetitive content, questions, and anything too vague to be useful
- One memory per distinct piece of information (don't bundle multiple facts)
- Keep "content" concise but complete — someone reading it later should understand it without context
- If nothing is worth remembering, return an empty array: []

## Examples

Input: "On va utiliser Redis 7 pour le cache, Memcached c'est mort."
→ {"content": "Decision: using Redis 7 for cache (dropping Memcached)", "type": "decision", "importance": "high", "confidence": 0.95}

Input: "Le backend tourne sur uvicorn port 8000."
→ {"content": "Backend runs on uvicorn, port 8000", "type": "fact", "importance": "medium", "confidence": 0.9}

Input: "Deadline démo client vendredi prochain, gel des merges mercredi soir."
→ {"content": "Client demo deadline Friday; merge freeze Wednesday evening", "type": "fact", "importance": "high", "confidence": 0.95}

Input: "Allez file, ton bug t'attend 🔧"
→ skip (banter / sign-off, no informational value)

Input: "Blague à part, c'était drôle ce matin."
→ skip (personal banter, off-topic)

Input: "J'aime bien le dark mode."
→ {"content": "User prefers dark mode", "type": "preference", "importance": "low", "confidence": 0.75}
  (soft preference without "always/never" → low, not high)

Input: "Pour redémarrer le backend: 1. git pull 2. systemctl --user restart voxyflow-backend 3. attendre /health. Pour le frontend: cd frontend-react && npm run build."
→ {"content": "How to restart the backend:\\n1. git pull\\n2. systemctl --user restart voxyflow-backend\\n3. wait for /health\\n\\nHow to rebuild the frontend:\\n1. cd frontend-react && npm run build", "type": "procedure", "importance": "medium", "confidence": 0.9}

Input: "tmux kill-session -t voxy"
→ {"content": "tmux kill-session -t voxy", "type": "fact", "importance": "low", "confidence": 0.6}
  (single command → fact, not procedure — procedures have ≥ 2 ordered steps)

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


