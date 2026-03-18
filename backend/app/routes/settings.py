"""Settings API — load/save personality and app configuration."""

from fastapi import APIRouter
from pydantic import BaseModel
import json
import os

router = APIRouter(prefix="/api/settings", tags=["settings"])

SETTINGS_FILE = os.path.expanduser("~/.openclaw/workspace/voxyflow/settings.json")


class PersonalitySettings(BaseModel):
    bot_name: str = "Ember"
    preferred_language: str = "both"  # "en", "fr", "both"
    soul_file: str = "~/.openclaw/workspace/SOUL.md"
    user_file: str = "~/.openclaw/workspace/USER.md"
    agents_file: str = "~/.openclaw/workspace/AGENTS.md"
    custom_instructions: str = ""
    environment_notes: str = ""
    tone: str = "casual"  # "casual", "balanced", "formal"
    warmth: str = "warm"  # "cold", "warm", "hot"


class AppSettings(BaseModel):
    personality: PersonalitySettings = PersonalitySettings()
    # Future: models, proxy, theme, voice sections


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
    for field, label in [("soul_file", "SOUL"), ("user_file", "USER"), ("agents_file", "AGENTS")]:
        path = os.path.expanduser(getattr(settings.personality, field))
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
                previews[label] = {
                    "path": path,
                    "exists": True,
                    "preview": content[:300] + ("..." if len(content) > 300 else ""),
                    "size": len(content),
                }
        else:
            previews[label] = {"path": path, "exists": False}

    return previews
