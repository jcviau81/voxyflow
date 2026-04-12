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
    os.path.expanduser("~/.voxyflow"),
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

    def _find_latest_archive(self, path: Path) -> Path | None:
        """Find the most recent .archived-*.json file for a given session path."""
        stem = path.stem  # e.g. "system-main"
        parent = path.parent
        if not parent.exists():
            return None
        archives = sorted(
            parent.glob(f"{stem}.archived-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return archives[0] if archives else None

    def load_session(self, chat_id: str) -> List[dict]:
        """Load all messages for a session.

        Falls back to the most recent archived session if the active file
        doesn't exist (e.g. after a session:reset where the init didn't complete).
        """
        path = self._get_session_path(chat_id)
        target = path if path.exists() else self._find_latest_archive(path)
        if not target:
            return []

        try:
            with open(target) as f:
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

    # ------------------------------------------------------------------
    # Summary persistence (sliding window)
    # ------------------------------------------------------------------

    def _get_summary_path(self, chat_id: str) -> Path:
        """Get file path for a chat session's summary."""
        safe_id = chat_id.replace(":", "/").replace("..", "")
        path = self.sessions_dir / f"{safe_id}.summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def load_summary(self, chat_id: str) -> dict | None:
        """Load the persisted conversation summary for a chat session.

        Returns dict with keys: summary_text, summarized_count
        or None if no summary exists.
        """
        path = self._get_summary_path(chat_id)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def save_summary(self, chat_id: str, summary_text: str, summarized_count: int):
        """Persist the conversation summary for a chat session."""
        path = self._get_summary_path(chat_id)
        data = json.dumps(
            {
                "chat_id": chat_id,
                "summary_text": summary_text,
                "summarized_count": summarized_count,
                "updated_at": datetime.now().isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        )
        with self._file_locks[chat_id]:
            fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(data)
                os.rename(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def clear_summary(self, chat_id: str):
        """Remove the persisted summary for a chat session."""
        path = self._get_summary_path(chat_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    def clear_session(self, chat_id: str):
        """Clear a session's messages and summary (archives messages instead of deleting)."""
        self.clear_summary(chat_id)
        path = self._get_session_path(chat_id)
        if path.exists():
            archive_suffix = datetime.now().strftime("%Y%m%d-%H%M%S")
            archive_path = path.with_suffix(f".archived-{archive_suffix}.json")
            path.rename(archive_path)

    def delete_session(self, chat_id: str) -> None:
        """Permanently delete a session file (and its summary) from disk."""
        path = self._get_session_path(chat_id)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        summary_path = self._get_summary_path(chat_id)
        if summary_path.exists():
            try:
                summary_path.unlink()
            except OSError:
                pass

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

    def _parse_session_entry(self, data: dict, cutoff: datetime) -> dict | None:
        """Parse a session JSON dict into a list_active_sessions entry, or None if filtered."""
        updated_at_str = data.get("updated_at")
        if not updated_at_str:
            return None

        try:
            updated_at = datetime.fromisoformat(updated_at_str)
            if updated_at.tzinfo is not None:
                updated_at = updated_at.replace(tzinfo=None)
        except ValueError:
            return None

        if updated_at < cutoff:
            return None

        chat_id = data.get("chat_id", "")
        messages = data.get("messages", [])
        message_count = data.get("message_count", len(messages))

        if not (chat_id.startswith("project:") or chat_id.startswith("card:")):
            return None
        if message_count < 1:
            return None

        last_message = None
        first_user_message = None
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content") and not first_user_message:
                first_user_message = msg["content"][:60]
        for msg in reversed(messages):
            if msg.get("role") in ("user", "assistant") and msg.get("content"):
                last_message = {
                    "role": msg["role"],
                    "content": msg["content"][:100],
                    "timestamp": msg.get("timestamp"),
                }
                break

        title = first_user_message or chat_id.split(":")[-1].replace("-", " ").title()

        return {
            "chatId": chat_id,
            "title": title,
            "lastMessage": last_message,
            "messageCount": message_count,
            "updatedAt": updated_at_str,
        }

    def list_active_sessions(self, max_age_hours: int = 720) -> List[dict]:
        """List sessions updated within max_age_hours, with lastMessage info.

        Returns [{ chatId, title, lastMessage, messageCount, updatedAt }] sorted by updatedAt desc.
        Falls back to the most recent archived session when no active file exists for a chatId.
        """
        from datetime import timedelta, timezone
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        sessions = []
        seen_chat_ids: set[str] = set()

        # First pass: active (non-archived) sessions
        for path in self.sessions_dir.rglob("*.json"):
            if path.name.startswith(".") or "archived" in path.name:
                continue
            try:
                with open(path) as f:
                    data = json.load(f)
                entry = self._parse_session_entry(data, cutoff)
                if entry:
                    sessions.append(entry)
                    seen_chat_ids.add(entry["chatId"])
            except (json.JSONDecodeError, IOError):
                pass

        # Second pass: for chatIds with no active session, fall back to the
        # most recent archive (by mtime).  Collect candidates keyed by their
        # base active path so we can pick the newest per slot.
        archive_candidates: dict[str, Path] = {}  # active_path_str → newest archive Path
        for path in self.sessions_dir.rglob("*.json"):
            if "archived" not in path.name or path.name.startswith("."):
                continue
            stem = path.name.split(".archived-")[0]
            active_path = path.parent / f"{stem}.json"
            if active_path.exists():
                continue  # active file exists, already handled in first pass
            key = str(active_path)
            prev = archive_candidates.get(key)
            if prev is None or path.stat().st_mtime > prev.stat().st_mtime:
                archive_candidates[key] = path

        for path in archive_candidates.values():
            try:
                with open(path) as f:
                    data = json.load(f)
                chat_id = data.get("chat_id", "")
                if chat_id in seen_chat_ids:
                    continue
                entry = self._parse_session_entry(data, cutoff)
                if entry:
                    sessions.append(entry)
                    seen_chat_ids.add(chat_id)
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
