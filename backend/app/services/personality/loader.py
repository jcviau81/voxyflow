"""Personality file/settings loading + caching (PersonalityLoaderMixin).

Reads personality configuration from settings.json (saved via Settings UI).

IMPORTANT: Personality files are loaded from voxyflow/personality/ by default,
NOT from the OpenClaw workspace. This prevents context leakage between systems.
"""

import json
import logging
import os
from pathlib import Path

# Canonical path resolution lives in app.config — single resolution site.
from app.config import VOXYFLOW_DIR

logger = logging.getLogger(__name__)

# Voxyflow's own personality directory (NOT OpenClaw workspace)
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"

# Personality files — isolated to Voxyflow
SOUL_FILE = PERSONALITY_DIR / "SOUL.md"
USER_FILE = PERSONALITY_DIR / "USER.md"
IDENTITY_FILE = PERSONALITY_DIR / "IDENTITY.md"
AGENTS_FILE = PERSONALITY_DIR / "AGENTS.md"
DISPATCHER_FILE = PERSONALITY_DIR / "DISPATCHER.md"
WORKER_FILE = PERSONALITY_DIR / "WORKER.md"
ARCHITECTURE_FILE = PERSONALITY_DIR / "ARCHITECTURE.md"
PROACTIVE_FILE = PERSONALITY_DIR / "PROACTIVE.md"

# Settings file lives in the data dir (outside repo)
from app.config import SETTINGS_FILE  # ~/.voxyflow/settings.json

_CACHE_TTL = 300  # 5 minutes

# Files we have already warned about (module-level → one warning per file per
# process, regardless of how many service instances exist).
_WARNED_MISSING: set[str] = set()


def _warn_missing_once(path: Path) -> None:
    key = str(path)
    if key not in _WARNED_MISSING:
        _WARNED_MISSING.add(key)
        logger.warning(
            "[personality] %s missing at %s — dispatcher rules degraded",
            path.name, path,
        )


class PersonalityLoaderMixin:
    """Loads and caches personality files + settings.json."""

    def __init__(self):
        self._cache: dict[str, tuple[float, str]] = {}
        self._settings_cache: tuple[float, dict] | None = None

    def _read_if_changed(self, path: Path) -> str:
        if not path.exists():
            _warn_missing_once(path)
            return ""
        try:
            mtime = path.stat().st_mtime
            cached = self._cache.get(str(path))
            if cached and cached[0] == mtime:
                return cached[1]
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                _warn_missing_once(path)  # exists but empty — same degradation
            self._cache[str(path)] = (mtime, content)
            return content
        except Exception as e:
            logger.warning(f"Failed to read personality file {path}: {e}")
            return ""

    def _load_settings(self) -> dict:
        if not SETTINGS_FILE.exists():
            return {}
        try:
            mtime = SETTINGS_FILE.stat().st_mtime
            if self._settings_cache and self._settings_cache[0] == mtime:
                return self._settings_cache[1]
            with open(SETTINGS_FILE) as f:
                data = json.load(f)
            self._settings_cache = (mtime, data)
            return data
        except Exception as e:
            logger.warning(f"Failed to read settings.json: {e}")
            return {}

    def get_personality_settings(self) -> dict:
        settings = self._load_settings()
        return settings.get("personality", {})

    def get_bot_name(self) -> str:
        """Return configured assistant name from settings (personality.bot_name or assistant_name)."""
        settings = self._load_settings()
        name = settings.get("personality", {}).get("bot_name", "").strip()
        if not name:
            name = settings.get("assistant_name", "").strip()
        return name or "Voxy"

    def get_user_name(self) -> str:
        """Return configured user name from settings."""
        settings = self._load_settings()
        return settings.get("user_name", "").strip() or "User"

    def _resolve_path(self, raw_path: str) -> Path:
        """Resolve a personality file path, relative to VOXYFLOW_DIR."""
        p = Path(raw_path)
        if p.is_absolute():
            return p
        expanded = Path(os.path.expanduser(raw_path))
        if expanded.is_absolute():
            return expanded
        return VOXYFLOW_DIR / raw_path

    def load_soul(self) -> str:
        ps = self.get_personality_settings()
        soul_path = ps.get("soul_file")
        if soul_path:
            return self._read_if_changed(self._resolve_path(soul_path))
        return self._read_if_changed(SOUL_FILE)

    def load_user(self) -> str:
        ps = self.get_personality_settings()
        user_path = ps.get("user_file")
        if user_path:
            return self._read_if_changed(self._resolve_path(user_path))
        return self._read_if_changed(USER_FILE)

    def load_identity(self) -> str:
        ps = self.get_personality_settings()
        identity_path = ps.get("identity_file")
        if identity_path:
            return self._read_if_changed(self._resolve_path(identity_path))
        return self._read_if_changed(IDENTITY_FILE)

    def load_agents(self) -> str:
        ps = self.get_personality_settings()
        agents_path = ps.get("agents_file")
        if agents_path:
            return self._read_if_changed(self._resolve_path(agents_path))
        return self._read_if_changed(AGENTS_FILE)

    def load_dispatcher(self) -> str:
        content = self._read_if_changed(DISPATCHER_FILE)
        if content:
            content = content.replace("{VOXYFLOW_DIR}", str(VOXYFLOW_DIR))
        return content

    def load_worker(self) -> str:
        return self._read_if_changed(WORKER_FILE)

    def load_architecture(self) -> str:
        return self._read_if_changed(ARCHITECTURE_FILE)

    def load_proactive(self) -> str:
        return self._read_if_changed(PROACTIVE_FILE)
