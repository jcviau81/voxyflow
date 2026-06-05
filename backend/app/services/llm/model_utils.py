"""Model name resolution and output post-processing utilities."""

import asyncio
import logging
import re
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool-visibility callback invocation (coroutine-aware)
# ---------------------------------------------------------------------------

async def invoke_tool_callback(callback, name, args, result):
    """Invoke a tool-visibility callback, awaiting it if it returns a coroutine/future.
    Swallows callback errors (logged)."""
    if callback is None:
        return
    try:
        ret = callback(name, args, result)
        if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
            await ret
    except Exception as e:
        logger.debug("tool_callback raised: %s", e)

# ---------------------------------------------------------------------------
# LRU Dict — bounded dict that evicts the oldest entry on overflow
# ---------------------------------------------------------------------------

class _LRUDict(OrderedDict):
    """An OrderedDict subclass that enforces a maximum size by evicting the
    least-recently-used (oldest) entry whenever the limit is exceeded.

    Usage: drop-in replacement for plain dict / defaultdict in cases where
    the key space is theoretically unbounded (e.g. chat_id per user session).

    Thread-safety: ``__missing__`` holds an internal lock so two concurrent
    readers cannot both create a fresh entry for the same key — important when
    the default factory returns a synchronisation primitive (asyncio.Lock,
    threading.Lock) whose identity matters.
    """

    def __init__(self, maxsize: int = 500, default_factory=None):
        super().__init__()
        self._maxsize = maxsize
        self._default_factory = default_factory
        self._lock = threading.Lock()

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        while len(self) > self._maxsize:
            oldest_key, _ = next(iter(self.items()))
            logger.debug("[LRUDict] Evicting key: %r (maxsize=%d)", oldest_key, self._maxsize)
            super().__delitem__(oldest_key)

    def __missing__(self, key):
        if self._default_factory is None:
            raise KeyError(key)
        with self._lock:
            # Double-check under the lock — another thread may have created
            # the entry between the miss and acquiring the lock.
            if super().__contains__(key):
                return super().__getitem__(key)
            value = self._default_factory()
            self[key] = value
            return value


# ---------------------------------------------------------------------------
# Model name mapping: short names → Anthropic full names
# ---------------------------------------------------------------------------

_MODEL_MAP = {
    "claude-haiku-4":   "claude-haiku-4-5-20251001",
    "claude-sonnet-4":  "claude-sonnet-4-6",
    "claude-opus-4":    "claude-opus-4-7",
    "claude-haiku-3":   "claude-3-haiku-20240307",
    "claude-sonnet-3":  "claude-3-5-sonnet-20241022",
    "claude-opus-3":    "claude-3-opus-20240229",
}


def _resolve_model(name: str, native: bool = True) -> str:
    """Return the full Anthropic model name for a short alias, or the name unchanged.
    When using the proxy (native=False), keep short names as-is."""
    if not native:
        return name
    return _MODEL_MAP.get(name, name)


# ---------------------------------------------------------------------------
# Thinking model utilities (Qwen3, DeepSeek-R1, etc.)
# ---------------------------------------------------------------------------

def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> blocks from model output."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _is_thinking_model(model_name: str) -> bool:
    """Detect models that emit <think> tokens."""
    if not model_name:
        return False
    lower = model_name.lower()
    return any(x in lower for x in ("qwen3", "qwen2.5-think", "deepseek-r1", "deepseek-r2", "qwq"))


def _flatten_system(system: str | list[dict]) -> str:
    """Flatten an Anthropic cache-control system (list of text blocks) to a plain string.

    Used by non-Anthropic paths (CLI, OpenAI-compat) that can't forward the
    structured form. Equivalent to ``"\\n\\n".join(block["text"] …)`` with a
    passthrough for strings.
    """
    if isinstance(system, str):
        return system
    return "\n\n".join(block["text"] for block in system if block.get("text"))


def _inject_no_think(system: str | list, model_name: str) -> str | list:
    """Prepend /no_think to system prompt for thinking models to disable chain-of-thought."""
    if not _is_thinking_model(model_name):
        return system
    prefix = "/no_think\n\n"
    if isinstance(system, str):
        return prefix + system
    if isinstance(system, list):
        result = list(system)
        for i, block in enumerate(result):
            if isinstance(block, dict) and block.get("text"):
                result[i] = {**block, "text": prefix + block["text"]}
                return result
        return [{"type": "text", "text": prefix}] + result
    return system


def make_think_stream_filter():
    """Return ``(feed, flush)`` callables that strip ``<think>…</think>`` blocks
    from a token stream. ``feed(chunk)`` returns the visible text to forward
    (may be empty while inside a think block or while buffering a partial tag).
    ``flush()`` returns any remaining buffered text once the stream ends.

    Why: ``/no_think`` in the system prompt isn't always honoured by Qwen3 /
    DeepSeek-R1 / QwQ via Ollama, especially with long prompts — we still need
    to keep their reasoning out of the user-visible chat.
    """
    OPEN, CLOSE = "<think>", "</think>"
    state = {"inside": False, "buf": ""}

    def _longest_target_prefix_at_end(buf: str, target: str) -> int:
        for k in range(min(len(buf), len(target) - 1), 0, -1):
            if target.startswith(buf[-k:]):
                return k
        return 0

    def feed(chunk: str) -> str:
        state["buf"] += chunk
        out: list[str] = []
        while True:
            if state["inside"]:
                idx = state["buf"].find(CLOSE)
                if idx >= 0:
                    state["buf"] = state["buf"][idx + len(CLOSE):]
                    state["inside"] = False
                    continue
                # No full close tag yet — keep just enough to detect a split CLOSE.
                keep = _longest_target_prefix_at_end(state["buf"], CLOSE)
                state["buf"] = state["buf"][-keep:] if keep else ""
                break
            idx = state["buf"].find(OPEN)
            if idx >= 0:
                if idx:
                    out.append(state["buf"][:idx])
                state["buf"] = state["buf"][idx + len(OPEN):]
                state["inside"] = True
                continue
            # No full OPEN — emit everything except a possible partial tag tail.
            keep = _longest_target_prefix_at_end(state["buf"], OPEN)
            if keep < len(state["buf"]):
                out.append(state["buf"][: len(state["buf"]) - keep])
            state["buf"] = state["buf"][-keep:] if keep else ""
            break
        return "".join(out)

    def flush() -> str:
        if state["inside"]:
            state["buf"] = ""
            return ""
        out, state["buf"] = state["buf"], ""
        return out

    return feed, flush
