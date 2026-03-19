"""Settings API — load/save personality and app configuration.

Personality files are stored in voxyflow/personality/ (NOT OpenClaw workspace).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import json
import os
from pathlib import Path

router = APIRouter(prefix="/api/settings", tags=["settings"])

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow")))
SETTINGS_FILE = str(VOXYFLOW_DIR / "settings.json")
PERSONALITY_DIR = VOXYFLOW_DIR / "personality"


class PersonalitySettings(BaseModel):
    bot_name: str = "Assistant"
    preferred_language: str = "both"  # "en", "fr", "both"
    soul_file: str = "./personality/SOUL.md"
    user_file: str = "./personality/USER.md"
    agents_file: str = "./personality/AGENTS.md"
    identity_file: str = "./personality/IDENTITY.md"
    custom_instructions: str = ""
    environment_notes: str = ""
    tone: str = "casual"  # "casual", "balanced", "formal"
    warmth: str = "warm"  # "cold", "warm", "hot"


class ModelLayerConfig(BaseModel):
    provider_url: str = ""   # e.g. "http://localhost:3456/v1" or "http://localhost:11434/v1"
    api_key: str = ""        # empty = no key required (e.g. Ollama)
    model: str = ""          # e.g. "claude-sonnet-4", "qwen2.5:7b"
    enabled: bool = True


class ModelsSettings(BaseModel):
    fast: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3456/v1",
        api_key="",
        model="claude-sonnet-4",
        enabled=True,
    )
    deep: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3456/v1",
        api_key="",
        model="claude-opus-4",
        enabled=True,
    )
    analyzer: ModelLayerConfig = ModelLayerConfig(
        provider_url="http://localhost:3456/v1",
        api_key="",
        model="claude-haiku-4",
        enabled=True,
    )


class SchedulerSettings(BaseModel):
    enabled: bool = True
    heartbeat_interval_minutes: int = 2
    rag_index_interval_minutes: int = 15


class VoiceSettings(BaseModel):
    stt_engine: str = "native"   # "native" (Web Speech API) | "whisper" (server-side)
    stt_model: str = "medium"    # Whisper model name (tiny, base, small, medium, large-v3, turbo)
    stt_language: str = "auto"   # auto/en/fr/es/de/ja/zh
    tts_enabled: bool = True
    tts_auto_play: bool = False
    tts_url: str = "http://192.168.1.59:5500"
    tts_voice: str = "default"
    tts_speed: float = 1.0
    volume: int = 80


class AppSettings(BaseModel):
    personality: PersonalitySettings = PersonalitySettings()
    models: ModelsSettings = ModelsSettings()
    scheduler: SchedulerSettings = SchedulerSettings()
    voice: VoiceSettings = VoiceSettings()
    onboarding_complete: bool = False
    user_name: str = ""
    assistant_name: str = "Voxy"


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
    """Load settings from file."""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return AppSettings().dict()


@router.put("")
async def save_settings(settings: AppSettings):
    """Save settings to file."""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings.dict(), f, indent=2)
    return {"status": "saved"}


@router.get("/personality/preview")
async def preview_personality():
    """Preview current personality files content."""
    settings = AppSettings()
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
            settings = AppSettings(**data)

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

ALLOWED_FILES = {"SOUL.md", "USER.md", "AGENTS.md", "IDENTITY.md", "MEMORY.md"}

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

- **Name:**
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

- **Name:** Voxy
- **Emoji:** 🤖
- **Vibe:** Helpful, clear, professional

---
_Customize this to give your assistant a unique identity._
""",
}


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
    """Write a personality file."""
    if filename not in ALLOWED_FILES:
        raise HTTPException(400, f"File not allowed: {filename}")

    path = PERSONALITY_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    content = body.get("content", "")
    path.write_text(content, encoding="utf-8")
    return {"status": "saved", "filename": filename, "size": len(content)}


@router.post("/personality/files/{filename}/reset")
async def reset_personality_file(filename: str):
    """Reset a personality file to default template."""
    if filename not in ALLOWED_FILES:
        raise HTTPException(400, f"File not allowed: {filename}")

    template = DEFAULT_TEMPLATES.get(filename)
    if not template:
        raise HTTPException(400, f"No default template for: {filename}")

    path = PERSONALITY_DIR / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template, encoding="utf-8")
    return {"status": "reset", "filename": filename, "size": len(template)}
