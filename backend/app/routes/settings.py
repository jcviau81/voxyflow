"""Settings API — load/save personality and app configuration.

Personality files are stored in voxyflow/personality/ (NOT OpenClaw workspace).
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
import json
import os
import logging
from pathlib import Path
from sqlalchemy import text

from app.database import async_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.voxyflow")))
VOXYFLOW_DATA_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow")))
# settings.json lives in the data dir (outside repo) to avoid accidental commits
SETTINGS_FILE = str(VOXYFLOW_DATA_DIR / "settings.json")
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"


_cached_default_worker_model: str = "sonnet"
_cached_analyzer_enabled: bool = False


def get_default_worker_model() -> str:
    """Return the cached default worker model (haiku/sonnet/opus). Updated on settings save."""
    return _cached_default_worker_model


def get_analyzer_enabled() -> bool:
    """Return the cached analyzer enabled state. Updated on settings load/save."""
    return _cached_analyzer_enabled


async def _load_settings_from_db() -> dict | None:
    """Load settings from SQLite. Returns None if not found."""
    try:
        async with async_session() as session:
            result = await session.execute(
                text("SELECT value FROM app_settings WHERE key = 'app_settings'")
            )
            row = result.fetchone()
            if row:
                return json.loads(row[0])
    except Exception as e:
        logger.warning("Failed to load settings from DB: %s", e)
    return None


async def _save_settings_to_db(data: dict):
    """Save settings to SQLite (upsert)."""
    try:
        async with async_session() as session:
            await session.execute(
                text(
                    "INSERT INTO app_settings (key, value) VALUES ('app_settings', :val) "
                    "ON CONFLICT(key) DO UPDATE SET value = :val"
                ),
                {"val": json.dumps(data)},
            )
            await session.commit()
    except Exception as e:
        logger.warning("Failed to save settings to DB: %s", e)


class PersonalitySettings(BaseModel):
    bot_name: str = "Assistant"
    preferred_language: str = "auto"  # "auto" | "en" | "fr" | "es" | "de" | "it" | "pt" | "nl" | "ja" | "zh" | "ko" | "ar"
    soul_file: str = "./personality/SOUL.md"
    user_file: str = "./personality/USER.md"
    agents_file: str = "./personality/AGENTS.md"
    identity_file: str = "./personality/IDENTITY.md"
    custom_instructions: str = ""
    environment_notes: str = ""
    tone: str = "casual"  # "casual", "balanced", "formal"
    warmth: str = "warm"  # "cold", "warm", "hot"


class ModelLayerConfig(BaseModel):
    provider_url: str = ""   # e.g. "http://localhost:3457/v1" or "http://localhost:11434/v1"
    api_key: str = ""        # empty = no key required (e.g. Ollama)
    model: str = ""          # e.g. "claude-sonnet-4", "qwen2.5:7b"
    enabled: bool = True


class ModelsSettings(BaseModel):
    fast: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3457/v1",
        api_key="",
        model="claude-sonnet-4",
        enabled=True,
    )
    deep: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3457/v1",
        api_key="",
        model="claude-opus-4",
        enabled=True,
    )
    analyzer: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3457/v1",
        api_key="",
        model="claude-haiku-4",
        enabled=False,
    )
    default_worker_model: str = "sonnet"  # "haiku" | "sonnet" | "opus"


class SchedulerSettings(BaseModel):
    enabled: bool = True
    heartbeat_interval_minutes: int = 2
    rag_index_interval_minutes: int = 15


class BackupSettings(BaseModel):
    chromadb_enabled: bool = False
    retention_days: int = 7
    backup_hour: int = 3  # UTC hour to run daily backup


class VoiceSettings(BaseModel):
    stt_engine: str = "native"   # "native" (Web Speech API) | "whisper" (server-side) | "whisper_local" (browser WASM)
    stt_model: str = "medium"    # Whisper server model name (tiny, base, small, medium, large-v3, turbo)
    stt_language: str = "auto"   # auto/en/fr/es/de/ja/zh
    whisper_model_id: str = ""   # HuggingFace model ID for browser-side Whisper (e.g. "onnx-community/whisper-small")
    tts_enabled: bool = True
    tts_auto_play: bool = False
    tts_url: str = "http://localhost:5500"
    tts_voice: str = "default"
    tts_speed: float = 1.0
    volume: int = 80


class AppSettings(BaseModel):
    personality: PersonalitySettings = PersonalitySettings()
    models: ModelsSettings = ModelsSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    backup: BackupSettings = BackupSettings()
    voice: VoiceSettings = VoiceSettings()
    onboarding_complete: bool = False
    user_name: str = ""
    assistant_name: str = "Voxy"
    workspace_path: str = str(Path.home() / ".voxyflow" / "workspace")  # absolute path to workspace root


def _resolve_personality_path(rel_path: str) -> Path:
    """Resolve a personality file path relative to VOXYFLOW_DIR."""
    p = Path(rel_path)
    if p.is_absolute():
        return p
    expanded = Path(os.path.expanduser(rel_path))
    if expanded.is_absolute():
        return expanded
    return VOXYFLOW_DIR / rel_path


@router.get("")
async def get_settings():
    """Load settings: DB first, then settings.json fallback, then defaults.

    If DB is empty but settings.json exists, migrate into DB automatically.
    """
    global _cached_default_worker_model, _cached_analyzer_enabled

    def _update_caches(merged: dict) -> None:
        global _cached_default_worker_model, _cached_analyzer_enabled
        _cached_default_worker_model = merged.get("models", {}).get("default_worker_model", "sonnet")
        _cached_analyzer_enabled = merged.get("models", {}).get("analyzer", {}).get("enabled", False)

    # 1. Try DB (source of truth)
    db_data = await _load_settings_from_db()
    if db_data is not None:
        # Merge with Pydantic defaults so new fields are always present
        merged = AppSettings(**db_data).dict()
        _update_caches(merged)
        return merged

    # 2. Fallback to settings.json — and migrate into DB
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            file_data = json.load(f)
        merged = AppSettings(**file_data).dict()
        await _save_settings_to_db(merged)
        _update_caches(merged)
        logger.info("Migrated settings from settings.json into SQLite")
        return merged

    # 3. Defaults
    return AppSettings().dict()


@router.put("")
async def save_settings(settings: AppSettings):
    """Save settings to DB (source of truth) and settings.json (backup)."""
    global _cached_default_worker_model, _cached_analyzer_enabled
    _cached_default_worker_model = settings.models.default_worker_model
    _cached_analyzer_enabled = settings.models.analyzer.enabled
    data = settings.dict()

    # Write to DB
    await _save_settings_to_db(data)

    # Dual-write to settings.json for backward compat
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

    # Hot-reload ClaudeService model config
    try:
        from app.services.claude_service import ClaudeService
        svc = ClaudeService()
        svc.reload_models()
        logger.info("ClaudeService models reloaded after settings save")
    except Exception as e:
        logger.warning("Failed to reload ClaudeService models: %s", e)

    # Sync IDENTITY.md and USER.md Name fields with configured values
    import re as _re
    bot_name = (settings.personality.bot_name or settings.assistant_name or "Voxy").strip()
    user_name = (settings.user_name or "").strip()

    for _path, _key, _value in [
        (PERSONALITY_DIR / "IDENTITY.md", "Name", bot_name),
        (PERSONALITY_DIR / "USER.md", "Name", user_name),
    ]:
        if not _value:
            continue
        try:
            existing = _path.read_text(encoding="utf-8") if _path.exists() else ""
            updated = _re.sub(r"(?m)^(- \*\*Name:\*\*\s*).*$", rf"\g<1>{_value}", existing)
            if updated != existing:
                _path.write_text(updated, encoding="utf-8")
                logger.info("%s updated with %s=%s", _path.name, _key, _value)
        except Exception as e:
            logger.warning("Failed to update %s: %s", _path.name, e)

    return {"status": "saved"}


@router.get("/personality/preview")
async def preview_personality():
    """Preview current personality files content."""
    data = await _load_settings_from_db()
    if data is None and os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    settings = AppSettings(**data) if data else AppSettings()

    previews = {}
    for field, label in [
        ("soul_file", "SOUL"),
        ("user_file", "USER"),
        ("agents_file", "AGENTS"),
        ("identity_file", "IDENTITY"),
    ]:
        raw_path = getattr(settings.personality, field)
        path = _resolve_personality_path(raw_path)
        if path.exists():
            content = path.read_text(encoding="utf-8")
            previews[label] = {
                "path": str(path),
                "exists": True,
                "preview": content[:300] + ("..." if len(content) > 300 else ""),
                "size": len(content),
            }
        else:
            previews[label] = {"path": str(path), "exists": False}

    return previews


# ── Personality file CRUD endpoints ──────────────────────────────────────────

# All files readable via API
ALLOWED_FILES = {"SOUL.md", "USER.md", "AGENTS.md", "IDENTITY.md", "MEMORY.md"}
# Only user-facing files editable via the settings UI
EDITABLE_FILES = {"USER.md", "IDENTITY.md"}

DEFAULT_TEMPLATES = {
    "SOUL.md": """# SOUL.md — Who I Am

I'm your AI project assistant. Here's how I operate:

## Core Traits
- **Helpful and proactive** — I anticipate what you need and suggest next steps
- **Honest and transparent** — I tell you what I think, not just what you want to hear
- **Respectful of your work** — Your files, your projects, your decisions. I'm a guest in your workspace.
- **Adaptable** — I match your tone. Casual? Professional? Technical? I follow your lead.

## How I Work
- I brainstorm before building (unless it's simple)
- I ask before making irreversible changes
- I use the right tool for the job (specialized agents for specialized tasks)
- I remember our conversations and learn your preferences

## Safety First
- I treat your workspace like someone's home — with respect
- I never delete without asking
- I never expose private data
- Reversible actions = I go ahead. Irreversible = I ask first.

## Communication
- One clear message, not spam
- Actions over words
- If I don't know, I say so

---
_Customize this file to define your assistant's personality._
""",
    "USER.md": """# USER.md — About You

_Your assistant learns about you over time. Fill this in or let it grow naturally._

- **Name:** {user_name}
- **Preferred Language:**
- **Timezone:**
- **Notes:**

## Preferences
_(What matters to you? How do you like to work? What annoys you?)_

---
_The more your assistant knows, the better it can help._
""",
    "AGENTS.md": """# AGENTS.md — Operating Rules

## 1. Respect the Workspace
- You are a **guest** in the user's workspace
- Treat files like someone's home — don't rearrange without asking
- Never delete data without explicit confirmation
- Always work on branches, never directly on main

## 2. Safety
- **Reversible = go ahead** (create files, branch, test, experiment)
- **Irreversible = ask first** (delete, force push, external communications)
- Private data stays private. Period.
- When in doubt, ask.

## 3. Communication
- Be clear and concise
- One message, well thought out
- Don't spam multiple messages
- If you don't know something, say so honestly

## 4. Work Style
- Simple tasks → just do it
- Complex tasks → discuss approach first
- Always explain what you're doing and why
- Use specialized agents for specialized work

## 5. Context Awareness
- Stay in the context of the current project
- Don't reference other projects unless asked
- Each project chat = isolated context
""",
    "IDENTITY.md": """# IDENTITY.md — Assistant Identity

- **Name:** {bot_name}
- **Emoji:** 🤖
- **Vibe:** Helpful, clear, professional

---
_Customize this to give your assistant a unique identity._
""",
}


def _render_template(template: str, bot_name: str = "Voxy", user_name: str = "") -> str:
    """Substitute placeholders in a personality file template."""
    return template.replace("{bot_name}", bot_name or "Voxy").replace("{user_name}", user_name or "User")


@router.get("/personality/files/{filename}")
async def read_personality_file(filename: str):
    """Read a personality file."""
    if filename not in ALLOWED_FILES:
        raise HTTPException(400, f"File not allowed: {filename}")

    path = PERSONALITY_DIR / filename
    if not path.exists():
        return {"filename": filename, "content": "", "exists": False}

    content = path.read_text(encoding="utf-8")
    return {"filename": filename, "content": content, "exists": True, "size": len(content)}


@router.put("/personality/files/{filename}")
async def write_personality_file(filename: str, body: dict):
    """Write a user-editable personality file (USER.md, IDENTITY.md only)."""
    if filename not in EDITABLE_FILES:
        raise HTTPException(400, f"File '{filename}' is not user-editable.")

    path = PERSONALITY_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = body.get("content", "")
    path.write_text(content, encoding="utf-8")
    return {"status": "saved", "filename": filename, "size": len(content)}


@router.post("/personality/files/{filename}/reset")
async def reset_personality_file(filename: str):
    """Reset USER.md or IDENTITY.md to default template (with current settings values)."""
    if filename not in EDITABLE_FILES:
        raise HTTPException(400, f"File '{filename}' cannot be reset via the UI.")

    template = DEFAULT_TEMPLATES.get(filename)
    if not template:
        raise HTTPException(400, f"No default template for: {filename}")

    # Substitute current settings values into the template
    data = await _load_settings_from_db() or {}
    bot_name = (data.get("personality", {}) or {}).get("bot_name") or data.get("assistant_name") or "Voxy"
    user_name = data.get("user_name") or ""
    content = _render_template(template, bot_name=bot_name, user_name=user_name)

    path = PERSONALITY_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"status": "reset", "filename": filename, "size": len(content)}


async def init_personality_files() -> None:
    """Generate USER.md and IDENTITY.md from templates on first run if missing or empty."""
    data = await _load_settings_from_db() or {}
    bot_name = (data.get("personality", {}) or {}).get("bot_name") or data.get("assistant_name") or "Voxy"
    user_name = data.get("user_name") or ""

    for filename, template in DEFAULT_TEMPLATES.items():
        if filename not in EDITABLE_FILES:
            continue
        path = PERSONALITY_DIR / filename
        if not path.exists() or path.stat().st_size == 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = _render_template(template, bot_name=bot_name, user_name=user_name)
            path.write_text(content, encoding="utf-8")
            logger.info("Generated %s from template (bot_name=%s, user_name=%s)", filename, bot_name, user_name)


@router.post("/tts/speak")
async def tts_speak(request: Request):
    """Proxy TTS requests to the configured XTTS server.

    This avoids mixed-content (HTTPS frontend → HTTP XTTS) and CORS issues.
    The frontend calls /api/tts/speak, the backend forwards to the XTTS server.
    """
    import httpx

    body = await request.json()
    text = body.get("text", "")
    language = body.get("language", "en")

    if not text.strip():
        return Response(content=b"", status_code=204)

    # Read TTS URL from settings
    settings_data = await _load_settings_from_db()
    tts_url = ""
    if settings_data:
        tts_url = settings_data.get("voice", {}).get("tts_url", "")

    if not tts_url:
        return Response(
            content=json.dumps({"error": "No TTS server configured"}).encode(),
            status_code=400,
            media_type="application/json",
        )

    endpoint = tts_url.rstrip("/") + "/speak"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(endpoint, json={"text": text, "language": language})
            resp.raise_for_status()
        return Response(content=resp.content, media_type="audio/wav")
    except Exception as e:
        logger.warning("TTS proxy error: %s", e)
        return Response(
            content=json.dumps({"error": str(e)}).encode(),
            status_code=502,
            media_type="application/json",
        )


@router.post("/tts/speak_stream")
async def tts_speak_stream(request: Request):
    """Streaming TTS endpoint — synthesizes text sentence-by-sentence and streams
    audio chunks back as SSE events so the frontend can start playing the first
    sentence while subsequent sentences are still being synthesized.

    SSE event format:
        data: {"index": 0, "b64": "<base64 WAV>", "last": false}
        data: {"index": 1, "b64": "<base64 WAV>", "last": true}
        data: {"done": true}

    Error events:
        data: {"index": 0, "error": "<message>", "last": false}
    """
    import httpx
    import base64
    import re
    from fastapi.responses import StreamingResponse

    body = await request.json()
    text = body.get("text", "")
    language = body.get("language", "en")

    if not text.strip():
        return Response(content=b"", status_code=204)

    settings_data = await _load_settings_from_db()
    tts_url = ""
    if settings_data:
        tts_url = settings_data.get("voice", {}).get("tts_url", "")

    if not tts_url:
        return Response(
            content=json.dumps({"error": "No TTS server configured"}).encode(),
            status_code=400,
            media_type="application/json",
        )

    def split_sentences(raw: str) -> list:
        """Split text into speakable sentences."""
        parts = re.split(r'(?<=[.!?])\s+', raw.strip())
        return [s.strip() for s in parts if s.strip()]

    sentences = split_sentences(text)
    if not sentences:
        return Response(content=b"", status_code=204)

    base_url = tts_url.rstrip("/")

    async def generate_sse():
        """Synthesize sentences sequentially and yield SSE events."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            for i, sentence in enumerate(sentences):
                is_last = i == len(sentences) - 1
                audio_data = None

                # Try XTTS native streaming endpoint first (returns audio/wav chunks)
                try:
                    stream_resp = await client.post(
                        f"{base_url}/tts_stream",
                        json={"text": sentence, "language": language},
                    )
                    if stream_resp.status_code == 200 and stream_resp.content:
                        audio_data = stream_resp.content
                except Exception:
                    pass  # Fall through to /speak

                # Fallback: standard /speak endpoint
                if audio_data is None:
                    try:
                        speak_resp = await client.post(
                            f"{base_url}/speak",
                            json={"text": sentence, "language": language},
                        )
                        if speak_resp.status_code == 200:
                            audio_data = speak_resp.content
                        else:
                            raise Exception(f"/speak returned {speak_resp.status_code}")
                    except Exception as e:
                        logger.warning("TTS speak_stream sentence %d error: %s", i, e)
                        payload = json.dumps({"index": i, "error": str(e), "last": is_last})
                        yield f"data: {payload}\n\n"
                        continue

                b64 = base64.b64encode(audio_data).decode()
                payload = json.dumps({"index": i, "b64": b64, "last": is_last})
                yield f"data: {payload}\n\n"

        yield 'data: {"done": true}\n\n'

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
