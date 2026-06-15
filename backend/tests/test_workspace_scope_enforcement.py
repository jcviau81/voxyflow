"""Scope-enforcement invariants for MCP path params.

When VOXYFLOW_WORKSPACE_ID holds a real workspace UUID, env must win over any
workspace_id an LLM emits in tool arguments. The schema strips workspace_id,
but some models re-emit it anyway — this locks down the runtime guard.
"""
import os

from app.mcp_server import _build_url_and_payload


PROJECT_A = "aaaaaaaa-bbbb-cccc-dddd-000000000001"
PROJECT_B = "bbbbbbbb-cccc-dddd-eeee-000000000002"


def test_env_workspace_id_wins_over_llm_in_scoped_chat(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)

    url, body, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/workspaces/{workspace_id}/cards",
        payload_transformer=None,
        params={"workspace_id": PROJECT_B, "title": "foo"},
    )

    assert f"/api/workspaces/{PROJECT_A}/cards" == url
    assert "workspace_id" not in body
    assert body["title"] == "foo"


def test_env_fills_when_llm_omits_workspace_id(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)

    url, _, _ = _build_url_and_payload(
        method="GET",
        path_template="/api/workspaces/{workspace_id}/cards",
        payload_transformer=None,
        params={},
    )

    assert url == f"/api/workspaces/{PROJECT_A}/cards"


def test_llm_workspace_id_accepted_in_general_chat(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", "system-main")

    url, _, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/workspaces/{workspace_id}/cards",
        payload_transformer=None,
        params={"workspace_id": PROJECT_B, "title": "foo"},
    )

    assert url == f"/api/workspaces/{PROJECT_B}/cards"


def test_workspace_entity_tools_honor_explicit_workspace_id(monkeypatch):
    """voxyflow.workspace.* operate ON workspaces — an explicit id targets that
    workspace, even in a workspace-scoped chat. Without this exemption, a bulk
    'delete workspaces A and B' fan-out got redirected onto the CURRENT
    workspace and destroyed it."""
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)

    url, _, _ = _build_url_and_payload(
        method="DELETE",
        path_template="/api/workspaces/{workspace_id}",
        payload_transformer=None,
        params={"workspace_id": PROJECT_B},
        tool_name="voxyflow.workspace.delete",
    )

    assert url == f"/api/workspaces/{PROJECT_B}"


def test_workspace_entity_tools_fall_back_to_env_when_omitted(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)

    url, _, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/workspaces/{workspace_id}/archive",
        payload_transformer=None,
        params={},
        tool_name="voxyflow.workspace.archive",
    )

    assert url == f"/api/workspaces/{PROJECT_A}/archive"


def test_child_resource_tools_still_hard_scoped(monkeypatch):
    """The exemption is for workspace-ENTITY tools only — child resources
    (cards, wiki, …) keep the env hard-override."""
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)

    url, _, _ = _build_url_and_payload(
        method="POST",
        path_template="/api/workspaces/{workspace_id}/cards",
        payload_transformer=None,
        params={"workspace_id": PROJECT_B, "title": "foo"},
        tool_name="voxyflow.card.create",
    )

    assert url == f"/api/workspaces/{PROJECT_A}/cards"


def test_card_id_not_hard_scoped(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", PROJECT_A)
    monkeypatch.setenv("VOXYFLOW_CARD_ID", "current-card")

    url, _, _ = _build_url_and_payload(
        method="GET",
        path_template="/api/cards/{card_id}",
        payload_transformer=None,
        params={"card_id": "other-card"},
    )

    assert url == "/api/cards/other-card"
