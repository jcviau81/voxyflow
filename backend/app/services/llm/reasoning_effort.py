"""Canonical worker reasoning-effort levels and per-provider mapping.

Voxyflow exposes ONE canonical effort scale on worker classes (and a
``default_worker_effort`` fallback); each CLI provider maps it to its own
flag/value because the native scales differ:

  - Claude CLI  : ``--effort low|medium|high|xhigh|max`` (per-invocation).
                  Unsupported models silently ignore the flag.
  - Codex CLI   : ``-c model_reasoning_effort="minimal|low|medium|high"``.

Canonical levels: ``"" | low | medium | high | max``. Empty / "default" /
"auto" means "pass nothing — let the model/CLI use its own default", which is
the historical behaviour (so an unset worker class is a no-op).
"""
from __future__ import annotations

# Canonical levels a worker class / default-worker setting may carry.
# "" is the sentinel for "inherit the model/CLI default" (no flag emitted).
CANONICAL_EFFORTS = ("", "low", "medium", "high", "max")


def normalize_effort(level: str | None) -> str:
    """Normalize a raw effort string to a canonical level (or "" for default).

    Tolerant of provider-native synonyms so a value copied from either CLI
    still resolves: ``minimal`` clamps up to ``low`` (Claude has no minimal),
    ``xhigh`` clamps to ``max``. Anything unrecognized → "" (default).
    """
    s = (level or "").strip().lower()
    if s in ("", "default", "auto", "none"):
        return ""
    if s in ("min", "minimal"):
        return "low"
    if s == "xhigh":
        return "max"
    return s if s in ("low", "medium", "high", "max") else ""


def claude_effort(level: str | None) -> str | None:
    """Map a canonical level to a Claude CLI ``--effort`` value, or None to omit.

    Claude accepts low|medium|high|xhigh|max; we expose low/medium/high/max,
    which all pass through unchanged. Models that don't support effort ignore
    the flag, so no per-model gating is needed here.
    """
    return normalize_effort(level) or None


def codex_reasoning_effort(level: str | None) -> str | None:
    """Map a canonical level to a Codex ``model_reasoning_effort``, or None to omit.

    Codex accepts minimal|low|medium|high. ``max`` clamps to ``high`` (Codex's
    ceiling); low/medium/high pass through unchanged.
    """
    s = normalize_effort(level)
    if not s:
        return None
    return "high" if s == "max" else s
