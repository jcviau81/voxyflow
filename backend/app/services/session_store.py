"""Persist chat sessions to disk as JSON files.

Provides a simple file-based session store so conversations survive restarts.
Each chat_id maps to a JSON file under data/sessions/.
The chat_id format (e.g. "general:abc", "project:xyz", "card:123") naturally
maps to subdirectories via colon → slash translation.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

DATA_DIR = Path(os.environ.get(
    "VOXYFLOW_DATA",
    os.path.expanduser("~/voxyflow/data"),
))


class SessionStore:
    """Persists chat sessions to disk as JSON files."""

    def __init__(self):
        self.sessions_dir = DATA_DIR / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, chat_id: str) -> Path:
        """Get file path for a chat session."""
        # Sanitize chat_id for filesystem: colons → subdirs, strip ..
        safe_id = chat_id.replace(":", "/").replace("..", "")
        path = self.sessions_dir / f"{safe_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_message(self, chat_id: str, message: dict):
        """Append a message to a session file."""
        path = self._get_session_path(chat_id)

        # Load existing
        messages = self.load_session(chat_id)

        # Add timestamp if not present
        if "timestamp" not in message:
            message["timestamp"] = datetime.now().isoformat()

        messages.append(message)

        # Save atomically-ish
        with open(path, "w") as f:
            json.dump(
                {
                    "chat_id": chat_id,
                    "updated_at": datetime.now().isoformat(),
                    "message_count": len(messages),
                    "messages": messages,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

    def load_session(self, chat_id: str) -> List[dict]:
        """Load all messages for a session."""
        path = self._get_session_path(chat_id)
        if not path.exists():
            return []

        try:
            with open(path) as f:
                data = json.load(f)
                return data.get("messages", [])
        except (json.JSONDecodeError, IOError):
            return []

    def get_recent_messages(self, chat_id: str, limit: int = 20) -> List[dict]:
        """Get the N most recent messages."""
        messages = self.load_session(chat_id)
        return messages[-limit:]

    def get_history_for_claude(self, chat_id: str, limit: int = 20) -> List[dict]:
        """Get messages formatted for Claude API (role + content only)."""
        messages = self.get_recent_messages(chat_id, limit)
        return [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content")
            and m.get("type") != "enrichment"  # Skip enrichments from history
        ]

    def clear_session(self, chat_id: str):
        """Clear a session's messages (archives instead of deleting)."""
        path = self._get_session_path(chat_id)
        if path.exists():
            archive_suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive_path = path.with_suffix(f".archived-{archive_suffix}.json")
            path.rename(archive_path)

    def list_sessions(self, prefix: str = "") -> List[dict]:
        """List all sessions, optionally filtered by prefix."""
        sessions = []
        for path in self.sessions_dir.rglob("*.json"):
            if path.name.startswith(".") or "archived" in path.name:
                continue
            try:
                with open(path) as f:
                    data = json.load(f)
                    sessions.append(
                        {
                            "chat_id": data.get("chat_id", path.stem),
                            "updated_at": data.get("updated_at"),
                            "message_count": data.get("message_count", 0),
                            "path": str(path),
                        }
                    )
            except (json.JSONDecodeError, IOError):
                pass

        if prefix:
            sessions = [s for s in sessions if s["chat_id"].startswith(prefix)]

        return sorted(
            sessions, key=lambda s: s.get("updated_at", ""), reverse=True
        )


# Singleton
session_store = SessionStore()
