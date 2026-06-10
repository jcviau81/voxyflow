"""Regression guard for the cards.py -> app/routes/cards/ package split.

The route table snapshot below was captured from the monolithic
``app/routes/cards.py`` BEFORE the refactor (commit 1ebc093). The split
must keep (method, path, name) registration order byte-identical —
notably the static ``/cards/unassigned`` and ``/cards/bulk-reorder``
routes MUST stay registered before ``/cards/{card_id}`` or the path
param captures them.
"""

from app.routes import cards


# Captured from the pre-refactor monolith — do not reorder.
EXPECTED_ROUTE_TABLE = [
    ("GET", "/api/agents", "list_agents"),
    ("POST", "/api/workspaces/{workspace_id}/cards", "create_card"),
    ("GET", "/api/workspaces/{workspace_id}/cards", "list_cards"),
    ("GET", "/api/cards/unassigned", "list_unassigned_cards"),
    ("POST", "/api/cards/unassigned", "create_unassigned_card"),
    ("POST", "/api/cards/bulk-reorder", "bulk_reorder_cards"),
    ("PATCH", "/api/cards/{card_id}/assign/{workspace_id}", "assign_card_to_project"),
    ("PATCH", "/api/cards/{card_id}/unassign", "unassign_card_from_project"),
    ("GET", "/api/cards/{card_id}", "get_card"),
    ("PATCH", "/api/cards/{card_id}", "update_card"),
    ("POST", "/api/cards/{card_id}/assign", "assign_agent"),
    ("GET", "/api/cards/{card_id}/routing", "get_routing_suggestion"),
    ("POST", "/api/cards/{card_id}/duplicate", "duplicate_card"),
    ("POST", "/api/cards/{card_id}/execute", "execute_card"),
    ("POST", "/api/workspaces/{workspace_id}/boards/execute", "execute_board_plan"),
    ("DELETE", "/api/cards/{card_id}", "delete_card"),
    ("POST", "/api/cards/{card_id}/archive", "archive_card"),
    ("POST", "/api/cards/{card_id}/restore", "restore_card"),
    ("GET", "/api/workspaces/{workspace_id}/cards/archived", "list_archived_cards"),
    ("POST", "/api/cards/{card_id}/clone-to/{target_workspace_id}", "clone_card_to_project"),
    ("POST", "/api/cards/{card_id}/move-to/{target_workspace_id}", "move_card_to_project"),
    ("GET", "/api/cards/{card_id}/history", "get_card_history"),
    ("POST", "/api/cards/{card_id}/vote", "vote_card"),
    ("DELETE", "/api/cards/{card_id}/vote", "unvote_card"),
    ("POST", "/api/cards/{card_id}/time", "log_time"),
    ("GET", "/api/cards/{card_id}/time", "list_time_entries"),
    ("DELETE", "/api/cards/{card_id}/time/{entry_id}", "delete_time_entry"),
    ("POST", "/api/cards/{card_id}/checklist", "add_checklist_item"),
    ("GET", "/api/cards/{card_id}/checklist", "list_checklist_items"),
    ("PATCH", "/api/cards/{card_id}/checklist/{item_id}", "update_checklist_item"),
    ("DELETE", "/api/cards/{card_id}/checklist/{item_id}", "delete_checklist_item"),
    ("POST", "/api/cards/{card_id}/checklist/bulk", "add_checklist_items_bulk"),
    ("POST", "/api/cards/{card_id}/attachments", "upload_attachment"),
    ("GET", "/api/cards/{card_id}/attachments", "list_attachments"),
    ("GET", "/api/cards/{card_id}/attachments/{attachment_id}/download", "download_attachment"),
    ("DELETE", "/api/cards/{card_id}/attachments/{attachment_id}", "delete_attachment"),
    ("POST", "/api/cards/{card_id}/relations", "add_relation"),
    ("GET", "/api/cards/{card_id}/relations", "list_relations"),
    ("DELETE", "/api/cards/{card_id}/relations/{relation_id}", "delete_relation"),
    ("POST", "/api/cards/{card_id}/enrich", "enrich_card"),
    ("GET", "/api/cards/{card_id}/files", "list_card_files"),
    ("POST", "/api/cards/{card_id}/files", "add_card_file"),
    ("DELETE", "/api/cards/{card_id}/files", "remove_card_file"),
]


def _route_table(router):
    return [
        (sorted(r.methods)[0] if r.methods else "", r.path, r.name)
        for r in router.routes
    ]


def test_route_table_snapshot_exact_order():
    """(method, path, name) registration order is byte-identical to the monolith."""
    assert _route_table(cards.router) == EXPECTED_ROUTE_TABLE


def test_static_card_routes_registered_before_card_id():
    """/cards/unassigned and /cards/bulk-reorder must precede /cards/{card_id}."""
    paths = [r.path for r in cards.router.routes]
    first_dynamic = paths.index("/api/cards/{card_id}")
    assert paths.index("/api/cards/unassigned") < first_dynamic
    assert paths.index("/api/cards/bulk-reorder") < first_dynamic


def test_facade_reexports_survive():
    """Names other modules (or callers) import from app.routes.cards still resolve."""
    # workspaces.py imports ATTACHMENTS_BASE from app.routes.cards
    from app.routes.cards import ATTACHMENTS_BASE  # noqa: F401
    assert cards.ATTACHMENTS_BASE.name == "attachments"
    assert cards.MAX_ATTACHMENT_SIZE == 50 * 1024 * 1024
    assert callable(cards._card_to_response)
    assert callable(cards._broadcast_card_change)
    assert callable(cards._invert_relation_type)
    for name in (
        "UnassignedCardCreate",
        "CardHistoryEntry",
        "RelationCreate",
        "RelationResponse",
        "EnrichResponse",
        "FileRefRequest",
        "VALID_RELATION_TYPES",
    ):
        assert hasattr(cards, name), f"missing re-export: {name}"


def test_router_mounted_in_app():
    """main.py still picks up the cards router (same paths reachable in the app)."""
    from app.main import app

    app_paths = {getattr(r, "path", None) for r in app.routes}
    for _method, path, _name in EXPECTED_ROUTE_TABLE:
        assert path in app_paths, f"route missing from app: {path}"
