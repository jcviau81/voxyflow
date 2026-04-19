"""MCP system handler closures — extracted from mcp_server.py.

These handlers are instantiated lazily via `build_handlers()` because they
import several heavy modules (worker_supervisor, system_tools) and we want
to defer that cost until the first system-tool call.

Cross-module helpers (`_get_http_client`, `_enforce_task_scope`, …) are
passed in as arguments instead of imported directly to avoid a circular
dependency with `app.mcp_server`.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger("voxyflow.mcp")


# --- KG input limits (shared by the kg_* handlers built below) ---
_KG_MAX_NAME = 500
_KG_MAX_VALUE = 5000
_KG_MAX_LIMIT = 200


def _kg_clamp_limit(raw, default: int, ceiling: int = _KG_MAX_LIMIT) -> int:
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(v, ceiling))


def _kg_truncate(s: str | None, maxlen: int) -> str:
    s = (s or "").strip()
    return s[:maxlen]


def build_handlers(
    *,
    server: Any,
    types_module: Any,
    get_http_client: Callable[[], Any],
    enforce_task_scope: Callable[[str, str | None], Awaitable[dict | None]],
    current_project_scope: Callable[[], tuple[str, bool]],
    active_scopes: set[str],
) -> dict[str, Callable[[dict], Awaitable[dict]]]:
    """Create the full set of MCP system handlers and return them as a dict.

    Parameters are injected from `app.mcp_server` to break the circular
    import: `server` + `types_module` are the raw MCP objects (may be None
    when the mcp package is missing); the remaining callables are shared
    helpers that also live in mcp_server.
    """
    # Local alias used by the tools_load handler — keeps the existing code shape.
    _active_scopes = active_scopes
    _get_http_client = get_http_client
    _enforce_task_scope = enforce_task_scope
    _current_project_scope = current_project_scope
    types = types_module

    from app.tools.system_tools import (
        system_exec, web_search, web_fetch,
        file_read, file_write, file_patch, file_list,
        git_status, git_log, git_diff, git_branches, git_commit,
        tmux_list, tmux_run, tmux_send, tmux_capture, tmux_new, tmux_kill,
    )
    from app.services.worker_supervisor import (
        handle_task_complete,
        handle_worker_claim,
        handle_worker_complete,
    )

    async def memory_search(params: dict) -> dict:
        """Semantic search across Voxy's long-term memory.

        Default scope is the current project (isolation preserved). The LLM
        may pass an explicit `scope` to bridge to global or another project
        when the user asks for it — this is the single escape hatch from the
        per-project wall. Unknown scopes fall back to `current` and are logged.
        """
        from app.services.memory_service import (
            get_memory_service,
            GLOBAL_COLLECTION,
            _project_collection,
        )
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        limit = params.get("limit", 10)
        offset = params.get("offset", 0)
        scope = (params.get("scope") or "current").strip()

        env_project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
        project_id = env_project_id

        def _current_collections() -> list[str]:
            if project_id and project_id != "system-main":
                return [_project_collection(project_id)]
            return [GLOBAL_COLLECTION, _project_collection("system-main")]

        resolved_scope = scope
        if scope == "current":
            collections = _current_collections()
        elif scope == "global":
            collections = [GLOBAL_COLLECTION]
        elif scope == "current+global":
            cur = _current_collections()
            collections = list(dict.fromkeys(cur + [GLOBAL_COLLECTION]))
        elif scope.startswith("other:"):
            other_id = scope[len("other:"):].strip()
            if not other_id:
                return {"error": "scope 'other:' requires a project id"}
            if other_id == project_id:
                collections = _current_collections()
                resolved_scope = "current"
            else:
                collections = [_project_collection(other_id)]
        else:
            logger.warning(
                f"[mcp.memory.search] unknown scope={scope!r}, falling back to current"
            )
            collections = _current_collections()
            resolved_scope = "current"
        logger.info(
            f"[mcp.memory.search] project_id={project_id!r} scope={resolved_scope!r} "
            f"collections={collections}"
        )

        try:
            ms = get_memory_service()
            results = ms.search_memory(
                query,
                collections=collections,
                limit=limit,
                offset=offset,
            )
            if not results:
                return {
                    "results": [],
                    "offset": offset,
                    "limit": limit,
                    "count": 0,
                    "scope": resolved_scope,
                    "collections": collections,
                }
            formatted = []
            for r in results:
                formatted.append({
                    "id": r.get("id", ""),
                    "text": r.get("text", ""),
                    "score": round(r.get("score", 0), 3),
                    "collection": r.get("collection", ""),
                })
            return {
                "results": formatted,
                "offset": offset,
                "limit": limit,
                "count": len(formatted),
                "has_more": len(formatted) == limit,
                "scope": resolved_scope,
                "collections": collections,
            }
        except Exception as e:
            return {"error": str(e)}

    async def knowledge_search(params: dict) -> dict:
        """RAG search on project knowledge base — on-demand tool.

        Scope is enforced by VOXYFLOW_PROJECT_ID env var. The LLM
        cannot override it; params.project_id is ignored if present
        (it was removed from the schema but defensive-coded here).
        """
        from app.services.rag_service import get_rag_service
        env_project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
        project_id = env_project_id or "system-main"
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        logger.info(f"[mcp.knowledge.search] project_id={project_id!r}")
        try:
            result = await get_rag_service().build_rag_context(project_id, query)
            return {"result": result or "No relevant knowledge found."}
        except Exception as e:
            return {"error": str(e)}

    async def memory_save(params: dict) -> dict:
        """Store a memory entry in Voxy's long-term memory (ChromaDB or file fallback).

        STRICT ISOLATION: scope is enforced by VOXYFLOW_PROJECT_ID env var.
        The LLM cannot cross-save into another project — project_id is not
        in the schema and any param value is ignored.
        """
        from app.services.memory_service import (
            get_memory_service,
            GLOBAL_COLLECTION,
            _project_collection,
        )
        text = params.get("text", "").strip()
        if not text:
            return {"error": "text is required"}
        mem_type = params.get("type", "fact")
        importance = params.get("importance", "medium")

        env_project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
        project_id = env_project_id

        if project_id and project_id != "system-main":
            collection = _project_collection(project_id)
        elif project_id == "system-main":
            collection = _project_collection("system-main")
        else:
            collection = GLOBAL_COLLECTION
        logger.info(
            f"[mcp.memory.save] project_id={project_id!r} collection={collection}"
        )

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        worker_id = os.environ.get("VOXYFLOW_WORKER_ID", "").strip()
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        if worker_id:
            source = "worker"
            speaker = "worker"
        else:
            source = "chat"
            speaker = "assistant"
        meta: dict = {
            "type": mem_type,
            "date": date_str,
            "created_at": now.isoformat(timespec="seconds"),
            "source": source,
            "speaker": speaker,
            "importance": importance,
        }
        if worker_id:
            meta["worker_id"] = worker_id
        if chat_id:
            meta["chat_id"] = chat_id
        if project_id:
            meta["project_id"] = project_id
        try:
            ms = get_memory_service()
            doc_id = ms.store_memory(
                text=text,
                collection=collection,
                metadata=meta,
            )
            if doc_id:
                # Echo the attribution prefix so Voxy sees exactly how this
                # entry will render in future "Retrieved fragments" blocks —
                # same formatter used on read, so she can confirm the speaker
                # and scope are what she intended.
                try:
                    from app.services.memory_context import MemoryContextMixin
                    attribution = MemoryContextMixin._attribution_prefix(meta)
                except Exception:
                    attribution = ""
                return {
                    "success": True,
                    "id": doc_id,
                    "collection": collection,
                    "attribution": attribution,
                    "message": (
                        f"Memory saved ({mem_type}, {importance}) {attribution}".strip()
                    ),
                }
            return {"success": False, "error": "store_memory returned None"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def memory_delete(params: dict) -> dict:
        """Delete a memory entry by ID."""
        from app.services.memory_service import get_memory_service, GLOBAL_COLLECTION
        doc_id = params.get("id", "").strip()
        if not doc_id:
            return {"error": "id is required"}
        collection = params.get("collection", GLOBAL_COLLECTION)
        try:
            ms = get_memory_service()
            deleted = ms.delete_memory(doc_id, collection=collection)
            if deleted:
                return {"success": True, "message": f"Memory {doc_id} deleted from {collection}"}
            return {"success": False, "error": f"Failed to delete memory {doc_id}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def undo_list(params: dict) -> dict:
        """List reversible actions recorded during the current chat."""
        from app.services import undo_journal
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        if not chat_id:
            return {"success": False, "error": "no active chat id — undo journal is per-chat"}
        limit = min(max(int(params.get("limit") or 5), 1), undo_journal.MAX_PER_CHAT)
        entries = undo_journal.list_entries(chat_id, limit=limit)
        return {
            "success": True,
            "count": len(entries),
            "entries": [
                {
                    "id": e.id,
                    "label": e.label,
                    "forward_tool": e.forward_tool,
                    "inverse_tool": e.inverse_tool,
                    "age_seconds": int(__import__("time").time() - e.created_at),
                }
                for e in entries
            ],
        }

    async def undo_apply(params: dict) -> dict:
        """Replay the inverse of a journaled action."""
        from app.services import undo_journal
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        if not chat_id:
            return {"success": False, "error": "no active chat id — undo journal is per-chat"}
        entry_id = (params.get("id") or "").strip() or None
        entry = undo_journal.pop_by_id(chat_id, entry_id)
        if not entry:
            if entry_id:
                return {"success": False, "error": f"no undo entry with id={entry_id}"}
            return {"success": False, "error": "nothing to undo"}

        inv = entry.inverse_tool
        args = entry.inverse_args or {}
        client = _get_http_client()
        try:
            if inv == "voxyflow.card.archive":
                resp = await client.post(f"/api/cards/{args['card_id']}/archive")
                resp.raise_for_status()
                return {"success": True, "undid": entry.label, "entry_id": entry.id}
            if inv == "voxyflow.card.restore":
                resp = await client.post(f"/api/cards/{args['card_id']}/restore")
                resp.raise_for_status()
                return {"success": True, "undid": entry.label, "entry_id": entry.id}
            if inv == "memory.delete":
                result = await memory_delete({
                    "id": args["id"],
                    **({"collection": args["collection"]} if args.get("collection") else {}),
                })
                if not result.get("success"):
                    return {
                        "success": False,
                        "error": result.get("error") or "memory.delete failed",
                        "entry_id": entry.id,
                    }
                return {"success": True, "undid": entry.label, "entry_id": entry.id}
        except Exception as e:
            logger.error(f"[undo_apply] inverse failed for {inv}: {e}")
            return {"success": False, "error": str(e), "entry_id": entry.id}
        return {"success": False, "error": f"no replay path for inverse tool {inv!r}"}

    async def memory_get(params: dict) -> dict:
        """List recent chat sessions (history overview)."""
        from app.services.session_store import SessionStore
        limit = min(params.get("limit", 10), 50)
        try:
            store = SessionStore()
            sessions = store.list_active_sessions()[:limit]
            return {"count": len(sessions), "sessions": sessions}
        except Exception as e:
            return {"error": str(e)}

    async def task_steer(params: dict) -> dict:
        """Inject a steering message into a running worker task."""
        task_id = params.get("task_id", "").strip()
        message = params.get("message", "").strip()
        if not task_id:
            return {"error": "task_id is required"}
        if not message:
            return {"error": "message is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            client = _get_http_client()
            resp = await client.post(
                f"/api/worker-tasks/{task_id}/steer",
                json={"message": message},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("queued"):
                return {"success": True, "message": f"Steering message sent to task {task_id}"}
            return {"success": False, "error": f"No active worker found for task {task_id}. Task may have already completed."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def task_peek(params: dict) -> dict:
        """Live peek into a running worker task, with DB fallback for finished tasks."""
        task_id = (params.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            client = _get_http_client()
            resp = await client.get(f"/api/worker-tasks/{task_id}/peek")
            if resp.status_code == 404:
                return {"success": False, "error": f"Worker task not found: {task_id}"}
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "success" not in data:
                data["success"] = True
            return data
        except Exception as e:
            logger.error(f"[mcp.task.peek] failed: {e}")
            return {"success": False, "error": str(e)}

    async def task_cancel(params: dict) -> dict:
        """Cancel a running worker task across all active pools."""
        task_id = (params.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            client = _get_http_client()
            resp = await client.post(f"/api/worker-tasks/{task_id}/cancel")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "success" not in data:
                data["success"] = True
            return data
        except Exception as e:
            logger.error(f"[mcp.task.cancel] failed: {e}")
            return {"success": False, "error": str(e)}

    async def sessions_list(params: dict) -> dict:
        """List active CLI subprocess sessions, scoped to the current project by default."""
        import time
        from app.services.cli_session_registry import get_cli_session_registry
        registry = get_cli_session_registry()
        current_pid, scoped = _current_project_scope()
        scope = (params.get("scope") or "").lower()
        now = time.time()

        all_sessions = registry.list_active()
        if scope == "all" or not scoped:
            filtered = all_sessions
            scope_label = "all"
        else:
            filtered = [s for s in all_sessions if (s.project_id or "") == current_pid]
            scope_label = "project"

        return {
            "success": True,
            "scope": scope_label,
            "project_id": current_pid if scope_label == "project" else None,
            "sessions": [
                {
                    "id": s.id,
                    "pid": s.pid,
                    "sessionId": s.session_id,
                    "chatId": s.chat_id,
                    "projectId": s.project_id,
                    "model": s.model,
                    "type": s.session_type,
                    "startedAt": s.started_at,
                    "durationSeconds": round(now - s.started_at, 1),
                }
                for s in filtered
            ],
            "count": len(filtered),
            "total_active": registry.count(),
        }

    async def workers_list(params: dict) -> dict:
        """List active and recent worker tasks from the session store + DB.

        Defaults to the current project; pass scope='all' for system-wide.
        """
        from app.services.worker_session_store import get_worker_session_store
        try:
            store = get_worker_session_store()
            session_id = params.get("session_id")

            current_pid, scoped = _current_project_scope()
            scope = (params.get("scope") or "").lower()
            if scope == "all" or not scoped:
                filter_pid: str | None = None
                scope_label = "all"
            else:
                filter_pid = current_pid
                scope_label = "project"

            sessions = store.get_sessions(session_id=session_id)
            if filter_pid:
                sessions = [s for s in sessions if (s.get("project_id") or "") == filter_pid]
            status_filter = params.get("status")
            if status_filter:
                sessions = [s for s in sessions if s.get("status") == status_filter]
            limit = params.get("limit", 10)
            sessions = sessions[:limit]

            base = {
                "success": True,
                "scope": scope_label,
                "project_id": filter_pid,
                "count": len(sessions),
            }
            if not sessions:
                return {**base, "result": "No active or recent workers found.", "workers": []}
            return {**base, "workers": sessions}
        except Exception as e:
            logger.error(f"[mcp.workers.list] failed: {e}")
            return {"success": False, "error": str(e)}

    async def workers_get_result(params: dict) -> dict:
        """Get full details and result of a worker task, reading from DB for full output."""
        from app.services.worker_session_store import get_worker_session_store
        task_id = (params.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            store = get_worker_session_store()
            session = store.get_session(task_id)

            # The session JSON only carries a 500-char preview of the result.
            # The full untruncated result lives in worker_tasks.result_summary
            # (Text column) — read it from the DB so the caller gets the
            # complete output, not the UI preview.
            full_result = None
            try:
                from app.database import async_session, WorkerTask
                from sqlalchemy import select
                async with async_session() as db:
                    row = (await db.execute(
                        select(WorkerTask).where(WorkerTask.id == task_id)
                    )).scalar_one_or_none()
                    if row is not None:
                        full_result = row.result_summary
                        if session is None:
                            session = {
                                "task_id": row.id,
                                "session_id": row.session_id,
                                "project_id": row.project_id,
                                "card_id": row.card_id,
                                "intent": row.action,
                                "model": row.model,
                                "status": row.status,
                                "summary": row.description,
                            }
            except Exception as db_err:
                logger.warning(f"[mcp.workers.get_result] DB read failed: {db_err}")

            if session is None:
                return {"success": False, "error": f"Worker task not found: {task_id}"}

            if full_result is not None:
                session = {**session, "result_summary": full_result}

            return {"success": True, **session}
        except Exception as e:
            logger.error(f"[mcp.workers.get_result] failed: {e}")
            return {"success": False, "error": str(e)}

    async def workers_read_artifact(params: dict) -> dict:
        """Read a slice of a finished worker's full raw output (.md artifact).

        Worker callbacks only carry a Haiku-summarized version of the result;
        the verbatim content (file dumps, command stdout, logs) is persisted
        to ~/.voxyflow/worker_artifacts/{task_id}.md by the worker pool.
        This handler reads paginated slices of that file so the dispatcher
        can retrieve exact content on demand.
        """
        from app.services.worker_artifact_store import read_artifact
        task_id = (params.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            offset = int(params.get("offset", 0) or 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            length = int(params.get("length", 50_000) or 50_000)
        except (TypeError, ValueError):
            length = 50_000
        try:
            slice_data = read_artifact(task_id, offset=offset, length=length)
            if slice_data is None:
                return {
                    "success": False,
                    "error": (
                        f"No artifact found for task {task_id}. The worker may "
                        "not have completed yet, may have produced no output, or "
                        "its artifact may have been cleaned up."
                    ),
                }
            return {"success": True, **slice_data}
        except Exception as e:
            logger.error(f"[mcp.workers.read_artifact] failed: {e}")
            return {"success": False, "error": str(e)}

    async def tools_load(params: dict) -> dict:
        """Activate additional tool scopes dynamically."""
        raw = params.get("scopes", "")
        requested = {s.strip() for s in raw.split(",") if s.strip()}
        valid_scopes = {"voxyflow", "web", "git", "tmux", "file", "system"}
        invalid = requested - valid_scopes
        if invalid:
            return {
                "success": False,
                "error": f"Unknown scopes: {invalid}. Valid: {sorted(valid_scopes)}",
            }
        newly_added = requested - _active_scopes
        _active_scopes.update(requested)
        if newly_added:
            # Best-effort notify the MCP client to re-fetch the tool list.
            # The CLI transport does not support this notification — the
            # except path is the expected behavior there, so we log at
            # debug, not warning, to avoid noise.
            try:
                ctx = server.request_context
                await ctx.session.send_notification(
                    types.ToolListChangedNotification(
                        method="notifications/tools/list_changed",
                    )
                )
                logger.info(f"[tools.load] Activated scopes {newly_added}, sent ToolListChanged")
            except Exception as e:
                logger.debug(f"[tools.load] Activated scopes {newly_added}; ToolListChanged notification unavailable: {e}")
        else:
            logger.info(f"[tools.load] Scopes {requested} already active")
        return {
            "success": True,
            "active_scopes": sorted(_active_scopes),
            "newly_loaded": sorted(newly_added),
        }

    # ---- Knowledge Graph handlers ------------------------------------------
    # Constants + helpers (_KG_MAX_*, _kg_clamp_limit, _kg_truncate) live at
    # module scope — no shadowing needed here.

    async def kg_add(params: dict) -> dict:
        """Add entity + optional relationships/attributes to the KG."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        entity_name = _kg_truncate(params.get("entity_name"), _KG_MAX_NAME)
        entity_type = _kg_truncate(params.get("entity_type"), _KG_MAX_NAME)
        if not entity_name or not entity_type:
            return {"error": "entity_name and entity_type are required"}

        try:
            eid = await kg.add_entity(entity_name, entity_type, project_id)
            result: dict = {"success": True, "entity_id": eid, "entity_name": entity_name}

            # Relationships
            rels_added = []
            for rel in params.get("relationships", [])[:50]:
                target = _kg_truncate(rel.get("target"), _KG_MAX_NAME)
                target_type = _kg_truncate(rel.get("target_type"), _KG_MAX_NAME) or "concept"
                predicate = _kg_truncate(rel.get("predicate"), _KG_MAX_NAME) or "related_to"
                if not target:
                    continue
                tid = await kg.add_entity(target, target_type, project_id)
                triple_id = await kg.add_triple(eid, predicate, tid, source="chat")
                rels_added.append({"triple_id": triple_id, "predicate": predicate, "target": target})

            # Attributes
            attrs_added = []
            for attr in params.get("attributes", [])[:50]:
                key = _kg_truncate(attr.get("key"), _KG_MAX_NAME)
                value = _kg_truncate(attr.get("value"), _KG_MAX_VALUE)
                if not key:
                    continue
                aid = await kg.add_attribute(eid, key, value)
                attrs_added.append({"attribute_id": aid, "key": key, "value": value})

            if rels_added:
                result["relationships"] = rels_added
            if attrs_added:
                result["attributes"] = attrs_added

            await kg.refresh_pinned_cache(project_id)
            logger.info(f"[mcp.kg.add] project={project_id} entity={entity_name!r} rels={len(rels_added)} attrs={len(attrs_added)}")
            return result
        except Exception as e:
            logger.error(f"[mcp.kg.add] failed: {e}")
            return {"error": str(e)}

    async def kg_query(params: dict) -> dict:
        """Search entities and relationships in the KG."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        name = params.get("name")
        entity_type = params.get("entity_type")
        limit = _kg_clamp_limit(params.get("limit"), 20)
        include_rels = params.get("include_relationships", True)
        as_of_str = params.get("as_of")
        as_of = None
        if as_of_str:
            try:
                as_of = datetime.fromisoformat(as_of_str)
            except (ValueError, TypeError):
                return {"error": f"Invalid as_of datetime: {as_of_str!r}"}

        try:
            entities = await kg.query_entities(project_id, name=name, entity_type=entity_type, as_of=as_of, limit=limit)
            result: dict = {"entities": entities, "count": len(entities)}

            if include_rels and entities:
                rels = await kg.query_relationships(project_id, entity_name=name, limit=limit)
                result["relationships"] = rels

            logger.info(f"[mcp.kg.query] project={project_id} name={name!r} found={len(entities)}")
            return result
        except Exception as e:
            logger.error(f"[mcp.kg.query] failed: {e}")
            return {"error": str(e)}

    async def kg_timeline(params: dict) -> dict:
        """Chronological entity history."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        entity_name = params.get("entity_name")
        limit = _kg_clamp_limit(params.get("limit"), 50)

        try:
            events = await kg.get_timeline(project_id, entity_name=entity_name, limit=limit)
            logger.info(f"[mcp.kg.timeline] project={project_id} entity={entity_name!r} events={len(events)}")
            return {"events": events, "count": len(events)}
        except Exception as e:
            logger.error(f"[mcp.kg.timeline] failed: {e}")
            return {"error": str(e)}

    async def kg_invalidate(params: dict) -> dict:
        """Mark a triple or attribute as ended."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        triple_id = params.get("triple_id")
        attribute_id = params.get("attribute_id")

        if not triple_id and not attribute_id:
            return {"error": "Provide triple_id or attribute_id to invalidate"}

        try:
            ok = await kg.invalidate(triple_id=triple_id, attribute_id=attribute_id)
            await kg.refresh_pinned_cache(project_id)
            logger.info(f"[mcp.kg.invalidate] project={project_id} triple={triple_id} attr={attribute_id} ok={ok}")
            return {"success": ok, "invalidated": triple_id or attribute_id}
        except Exception as e:
            logger.error(f"[mcp.kg.invalidate] failed: {e}")
            return {"error": str(e)}

    async def kg_stats(params: dict) -> dict:
        """KG counts for the current project."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        try:
            stats = await kg.get_stats(project_id)
            logger.info(f"[mcp.kg.stats] project={project_id} stats={stats}")
            return {"success": True, "project_id": project_id, **stats}
        except Exception as e:
            logger.error(f"[mcp.kg.stats] failed: {e}")
            return {"error": str(e)}

    _heartbeat_path = Path(
        os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow"))
    ) / "workspace" / "heartbeat.md"

    async def heartbeat_read(params: dict) -> dict:
        try:
            if not _heartbeat_path.exists():
                return {"content": "", "exists": False}
            return {"content": _heartbeat_path.read_text(encoding="utf-8"), "exists": True}
        except Exception as e:
            return {"error": str(e)}

    async def heartbeat_write(params: dict) -> dict:
        content = params.get("content", "")
        try:
            _heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
            _heartbeat_path.write_text(content, encoding="utf-8")
            return {"status": "ok", "bytes": len(content)}
        except Exception as e:
            return {"error": str(e)}

    handlers: dict = {
        "heartbeat_read": heartbeat_read,
        "heartbeat_write": heartbeat_write,
        "tools_load": tools_load,
        "system_exec": system_exec,
        "web_search": web_search,
        "web_fetch": web_fetch,
        "file_read": file_read,
        "file_write": file_write,
        "file_patch": file_patch,
        "file_list": file_list,
        "git_status": git_status,
        "git_log": git_log,
        "git_diff": git_diff,
        "git_branches": git_branches,
        "git_commit": git_commit,
        "tmux_list": tmux_list,
        "tmux_run": tmux_run,
        "tmux_send": tmux_send,
        "tmux_capture": tmux_capture,
        "tmux_new": tmux_new,
        "tmux_kill": tmux_kill,
        "task_complete": handle_task_complete,
        "worker_claim": handle_worker_claim,
        "worker_complete": handle_worker_complete,
        "memory_search": memory_search,
        "memory_save": memory_save,
        "memory_delete": memory_delete,
        "memory_get": memory_get,
        "undo_list": undo_list,
        "undo_apply": undo_apply,
        "knowledge_search": knowledge_search,
        "task_steer": task_steer,
        "task_peek": task_peek,
        "task_cancel": task_cancel,
        "sessions_list": sessions_list,
        "workers_list": workers_list,
        "workers_get_result": workers_get_result,
        "workers_read_artifact": workers_read_artifact,
        "kg_add": kg_add,
        "kg_query": kg_query,
        "kg_timeline": kg_timeline,
        "kg_invalidate": kg_invalidate,
        "kg_stats": kg_stats,
    }

    return handlers
