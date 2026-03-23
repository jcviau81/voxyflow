"""Persist chat sessions to disk as JSON files.

Provides a simple file-based session store so conversations survive restarts.
Each chat_id maps to a JSON file under data/sessions/.
The chat_id format (e.g. "general:abc", "project:xyz", "card:123") naturally
maps to subdirectories via colon → slash translation.
"""

import json
import os
import tempfile
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List

DATA_DIR = Path(os.environ.get(
    "VOXYFLOW_DATA",
    os.path.expanduser("~/voxyflow/data"),
))


class SessionStore:
    """Persists chat sessions to disk as JSON files."""

    def __init__(self):
        self.sessions_dir = DATA_DIR / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        # Per-chat_id threading locks for file-level atomicity
        self._file_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def _get_session_path(self, chat_id: str) -> Path:
        """Get file path for a chat session."""
        # Sanitize chat_id for filesystem: colons → subdirs, strip ..
        safe_id = chat_id.replace(":", "/").replace("..", "")
        path = self.sessions_dir / f"{safe_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save_message(self, chat_id: str, message: dict):
        """Append a message to a session file (thread-safe, atomic write)."""
        path = self._get_session_path(chat_id)

        with self._file_locks[chat_id]:
            # Load existing (under lock to prevent read-modify-write races)
            messages = self.load_session(chat_id)

            # Add timestamp if not present
            if "timestamp" not in message:
                message["timestamp"] = datetime.now().isoformat()

            messages.append(message)

            # Atomic write: write to temp file, then os.rename
            data = json.dumps(
                {
                    "chat_id": chat_id,
                    "updated_at": datetime.now().isoformat(),
                    "message_count": len(messages),
                    "messages": messages,
                },
                indent=2,
                ensure_ascii=False,
            )
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(data)
                os.rename(tmp_path, str(path))
            except Exception:
                # Clean up temp file on failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

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

    def list_active_sessions(self, max_age_hours: int = 720) -> List[dict]:
        """List sessions updated within max_age_hours, with lastMessage info.

        Returns [{ chatId, title, lastMessage, messageCount, updatedAt }] sorted by updatedAt desc.
        """
        from datetime import timedelta, timezone
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        sessions = []
        for path in self.sessions_dir.rglob("*.json"):
            if path.name.startswith(".") or "archived" in path.name:
                continue
            try:
                with open(path) as f:
                    data = json.load(f)

                updated_at_str = data.get("updated_at")
                if not updated_at_str:
                    continue

                # Parse updated_at (ISO format, may or may not have timezone)
                try:
                    updated_at = datetime.fromisoformat(updated_at_str)
                    # Strip timezone info for naive comparison
                    if updated_at.tzinfo is not None:
                        updated_at = updated_at.replace(tzinfo=None)
                except ValueError:
                    continue

                if updated_at < cutoff:
                    continue

                chat_id = data.get("chat_id", "")
                messages = data.get("messages", [])
                message_count = data.get("message_count", len(messages))

                # Filter: only project sessions with >0 messages
                if not chat_id.startswith("project:"):
                    continue
                if message_count < 1:
                    continue

                last_message = None
                first_user_message = None
                # Find last user or assistant message + first user message for title
                for msg in messages:
                    if msg.get("role") == "user" and msg.get("content") and not first_user_message:
                        first_user_message = msg["content"][:60]
                for msg in reversed(messages):
                    if msg.get("role") in ("user", "assistant") and msg.get("content"):
                        last_message = {
                            "role": msg["role"],
                            "content": msg["content"][:100],  # snippet
                            "timestamp": msg.get("timestamp"),
                        }
                        break

                # Derive title from first user message
                title = first_user_message or chat_id.split(":")[-1].replace("-", " ").title()

                sessions.append({
                    "chatId": chat_id,
                    "title": title,
                    "lastMessage": last_message,
                    "messageCount": message_count,
                    "updatedAt": updated_at_str,
                })
            except (json.JSONDecodeError, IOError):
                pass

        return sorted(sessions, key=lambda s: s.get("updatedAt", ""), reverse=True)

    def create_session(self, project_id: str, title: str | None = None) -> str:
        """Create a new session with a stable incremental chat_id.

        Returns the chat_id, e.g. 'project:system-main:session-2'.
        The base session (no suffix) is 'project:{project_id}'.
        """
        import re
        base_chat_id = f"project:{project_id}"

        # Find existing session numbers for this project
        max_session_num = 1  # base session counts as 1
        prefix_path = self._get_session_path(base_chat_id).parent
        if prefix_path.exists():
            for path in prefix_path.iterdir():
                if path.name.startswith(".") or "archived" in path.name:
                    continue
                if not path.name.endswith(".json"):
                    continue
                # Match session-N.json
                match = re.match(r"session-(\d+)\.json", path.name)
                if match:
                    num = int(match.group(1))
                    if num > max_session_num:
                        max_session_num = num

        next_num = max_session_num + 1
        chat_id = f"{base_chat_id}:session-{next_num}"

        # Create the session file with an initial empty state
        path = self._get_session_path(chat_id)
        data = json.dumps(
            {
                "chat_id": chat_id,
                "title": title or f"Session {next_num}",
                "updated_at": datetime.now().isoformat(),
                "message_count": 0,
                "messages": [],
            },
            indent=2,
            ensure_ascii=False,
        )
        with open(path, "w") as f:
            f.write(data)

        return chat_id


# Singleton
session_store = SessionStore()
