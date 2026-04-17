"""Scope-enforcement invariants for MCP path params.

When VOXYFLOW_PROJECT_ID holds a real project UUID, env must win over any
project_id an LLM emits in tool arguments. The schema strips project_id,
but some models re-emit it anyway — this locks down the runtime guard.
"""
import os

from app.mcp_server import _build_url_and_payload


PROJECT_A = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
PROJECT_B = "bbbbbbbb-cccc-dddd-eeee-000000000002"


def test_env_project_id_wins_over_llm_in_scoped_chat(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_PROJECT_ID", PROJECT_A)

    url, body, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/projects/{project_id}/cards",
        payload_transformer=None,
        params={"project_id": PROJECT_B, "title": "foo"},
    )

    assert f"/api/projects/{PROJECT_A}/cards" == url
    assert "project_id" not in body
    assert body["title"] == "foo"


def test_env_fills_when_llm_omits_project_id(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_PROJECT_ID", PROJECT_A)

    url, _, _ = _build_url_and_payload(
        method="GET",
        path_template="/api/projects/{project_id}/cards",
        payload_transformer=None,
        params={},
    )

    assert url == f"/api/projects/{PROJECT_A}/cards"


def test_llm_project_id_accepted_in_general_chat(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_PROJECT_ID", "system-main")

    url, _, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/projects/{project_id}/cards",
        payload_transformer=None,
        params={"project_id": PROJECT_B, "title": "foo"},
    )

    assert url == f"/api/projects/{PROJECT_B}/cards"


def test_card_id_not_hard_scoped(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_PROJECT_ID", PROJECT_A)
    monkeypatch.setenv("VOXYFLOW_CARD_ID", "current-card")

    url, _, _ = _build_url_and_payload(
        method="GET",
        path_template="/api/cards/{card_id}",
        payload_transformer=None,
        params={"card_id": "other-card"},
    )

    assert url == "/api/cards/other-card"
