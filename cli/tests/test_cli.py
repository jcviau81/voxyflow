"""Offline unit tests for the voxy CLI — no live backend required."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from voxy.chatws import build_chat_envelope, build_session_sync
from voxy.client import CliError, resolve_workspace
from voxy.commands.skills import parse_frontmatter
from voxy.config import load_token, ws_url


# ---------------------------------------------------------------------------
# Workspace-name resolution
# ---------------------------------------------------------------------------

WORKSPACES = [
    {"id": "aaa-111", "title": "Voxyflow Dev"},
    {"id": "bbb-222", "title": "Personal"},
    {"id": "ccc-333", "title": "personal"},  # ambiguous with bbb-222 by name
    {"id": "ddd-444", "title": "Groceries"},
]


class TestResolveWorkspace:
    def test_resolve_by_exact_id(self):
        assert resolve_workspace(WORKSPACES, "aaa-111")["title"] == "Voxyflow Dev"

    def test_resolve_by_title_case_insensitive(self):
        assert resolve_workspace(WORKSPACES, "voxyflow dev")["id"] == "aaa-111"
        assert resolve_workspace(WORKSPACES, "VOXYFLOW DEV")["id"] == "aaa-111"

    def test_resolve_by_unique_prefix(self):
        assert resolve_workspace(WORKSPACES, "groc")["id"] == "ddd-444"

    def test_ambiguous_title_raises(self):
        with pytest.raises(CliError, match="ambiguous"):
            resolve_workspace(WORKSPACES, "Personal")

    def test_not_found_raises(self):
        with pytest.raises(CliError, match="not found"):
            resolve_workspace(WORKSPACES, "nonexistent")

    def test_id_match_wins_over_title(self):
        spaces = [{"id": "x", "title": "y"}, {"id": "y", "title": "z"}]
        assert resolve_workspace(spaces, "y")["title"] == "z"


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------

class TestEnvelopes:
    def test_chat_envelope_shape(self):
        env = build_chat_envelope(
            "hello", session_id="sess-1", message_id="msg-1",
            workspace_id="ws-1", deep=True,
        )
        assert env["type"] == "chat:message"
        assert isinstance(env["timestamp"], int)
        p = env["payload"]
        assert p["content"] == "hello"
        assert p["messageId"] == "msg-1"
        assert p["sessionId"] == "sess-1"
        assert p["workspaceId"] == "ws-1"
        assert p["layers"] == {"deep": True}
        assert "cardId" not in p

    def test_chat_envelope_defaults(self):
        env = build_chat_envelope("hi", session_id="s")
        p = env["payload"]
        assert p["layers"] == {"deep": False}
        assert "workspaceId" not in p
        # auto-generated messageId is a valid uuid
        uuid.UUID(p["messageId"])

    def test_chat_envelope_card_id(self):
        env = build_chat_envelope("hi", session_id="s", card_id="card-9")
        assert env["payload"]["cardId"] == "card-9"

    def test_chat_envelope_is_json_serializable(self):
        json.dumps(build_chat_envelope("hi", session_id="s"))

    def test_session_sync_envelope(self):
        env = build_session_sync("sess-42")
        assert env["type"] == "session:sync"
        assert env["payload"] == {"sessionId": "sess-42"}
        assert isinstance(env["timestamp"], int)


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------

class TestLoadToken:
    def test_reads_token_from_file(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("file-token\n")
        http_get = MagicMock()
        assert load_token("http://x", token_path=token_file, http_get=http_get) == "file-token"
        http_get.assert_not_called()

    def test_bootstraps_and_caches_when_file_missing(self, tmp_path):
        token_file = tmp_path / "sub" / "auth_token"
        resp = MagicMock()
        resp.json.return_value = {"token": "boot-token"}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)

        token = load_token("http://backend:1234", token_path=token_file, http_get=http_get)

        assert token == "boot-token"
        http_get.assert_called_once()
        assert http_get.call_args[0][0] == "http://backend:1234/api/auth/bootstrap"
        # cached back to disk with restrictive mode
        assert token_file.read_text().strip() == "boot-token"
        assert (token_file.stat().st_mode & 0o777) == 0o600

    def test_empty_file_falls_back_to_bootstrap(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("")
        resp = MagicMock()
        resp.json.return_value = {"token": "t2"}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)
        assert load_token("http://x", token_path=token_file, http_get=http_get) == "t2"

    def test_bootstrap_without_token_raises(self, tmp_path):
        resp = MagicMock()
        resp.json.return_value = {}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)
        with pytest.raises(RuntimeError):
            load_token("http://x", token_path=tmp_path / "none", http_get=http_get)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

class TestWsUrl:
    def test_http(self):
        assert ws_url("http://localhost:8000") == "ws://localhost:8000/ws"

    def test_https(self):
        assert ws_url("https://voxy.example.com") == "wss://voxy.example.com/ws"


class TestFrontmatter:
    def test_parses_name_and_description(self):
        text = "---\nname: my-skill\ndescription: Does things\n---\n# Body\ncontent"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "my-skill"
        assert meta["description"] == "Does things"
        assert body.strip().startswith("# Body")

    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("# Just markdown")
        assert meta == {}
        assert body == "# Just markdown"
