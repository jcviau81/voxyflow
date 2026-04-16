"""Model name resolution and output post-processing utilities."""

import logging
import re
import threading
from collections import OrderedDict

logger = logging.getLogger(__name__)

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
