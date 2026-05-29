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
    current_workspace_scope: Callable[[], tuple[str, bool]],
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
    _current_workspace_scope = current_workspace_scope
    types = types_module

    from app.tools.system_tools import (
        system_exec, web_search, web_fetch,
        file_read, file_write, file_patch, file_list,
        git_status, git_log, git_diff, git_branches, git_commit,
        tmux_list, tmux_run, tmux_send, tmux_capture, tmux_new, tmux_kill,
    )
    from app.services.worker_supervisor import (
        handle_worker_claim,
        handle_worker_complete,
    )

    async def memory_search(params: dict) -> dict:
        """Semantic search across Voxy's long-term memory.

        Default scope is the current workspace (isolation preserved). The LLM
        may pass an explicit `scope` to bridge to global or another workspace
        when the user asks for it — this is the single escape hatch from the
        per-workspace wall. Unknown scopes fall back to `current` and are logged.
        """
        from app.services.memory_service import (
            get_memory_service,
            GLOBAL_COLLECTION,
            _workspace_collection,
        )
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        limit = params.get("limit", 10)
        offset = params.get("offset", 0)
        scope = (params.get("scope") or "current").strip()

        env_workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
        workspace_id = env_workspace_id

        def _current_collections() -> list[str]:
            if workspace_id and workspace_id != "system-main":
                return [_workspace_collection(workspace_id)]
            return [GLOBAL_COLLECTION, _workspace_collection("system-main")]

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
                return {"error": "scope 'other:' requires a workspace id"}
            if other_id == workspace_id:
                collections = _current_collections()
                resolved_scope = "current"
            else:
                collections = [_workspace_collection(other_id)]
        else:
            logger.warning(
                f"[mcp.memory.search] unknown scope={scope!r}, falling back to current"
            )
            collections = _current_collections()
            resolved_scope = "current"
        logger.info(
            f"[mcp.memory.search] workspace_id={workspace_id!r} scope={resolved_scope!r} "
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
        """RAG search on workspace knowledge base — on-demand tool.

        Scope is enforced by VOXYFLOW_WORKSPACE_ID env var. The LLM
        cannot override it; params.workspace_id is ignored if present
        (it was removed from the schema but defensive-coded here).
        """
        from app.services.rag_service import get_rag_service
        env_workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
        workspace_id = env_workspace_id or "system-main"
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        logger.info(f"[mcp.knowledge.search] workspace_id={workspace_id!r}")
        try:
            result = await get_rag_service().build_rag_context(workspace_id, query)
            return {"result": result or "No relevant knowledge found."}
        except Exception as e:
            return {"error": str(e)}

    async def memory_save(params: dict) -> dict:
        """Store a memory entry in Voxy's long-term memory (ChromaDB or file fallback).

        STRICT ISOLATION: scope is enforced by VOXYFLOW_WORKSPACE_ID env var.
        The LLM cannot cross-save into another workspace — workspace_id is not
        in the schema and any param value is ignored.
        """
        from app.services.memory_service import (
            get_memory_service,
            GLOBAL_COLLECTION,
            _workspace_collection,
        )
        text = params.get("text", "").strip()
        if not text:
            return {"error": "text is required"}
        mem_type = params.get("type", "fact")
        importance = params.get("importance", "medium")

        env_workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
        workspace_id = env_workspace_id

        if workspace_id and workspace_id != "system-main":
            collection = _workspace_collection(workspace_id)
        elif workspace_id == "system-main":
            collection = _workspace_collection("system-main")
        else:
            collection = GLOBAL_COLLECTION
        logger.info(
            f"[mcp.memory.save] workspace_id={workspace_id!r} collection={collection}"
        )

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        worker_id = os.environ.get("VOXYFLOW_WORKER_ID", "").strip()
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        # Caller-supplied speaker overrides the default — lets the bot record
        # the user's quotes with speaker="user" instead of mis-attributing them
        # to itself. Only honoured outside the worker path (workers always
        # speak as "worker").
        requested_speaker = str(params.get("speaker") or "").strip().lower()
        if worker_id:
            source = "worker"
            speaker = "worker"
        else:
            source = "chat"
            speaker = requested_speaker if requested_speaker in {"user", "assistant"} else "assistant"
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
        if workspace_id:
            meta["workspace_id"] = workspace_id
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
        """Delete a memory entry by ID.

        Default behavior (no `collection` param): cascade across every
        collection in the *current scope* (same set used by `memory.search`
        with `scope=current`). This is the safe default — it prevents the
        old "success but orphan copy left behind" bug that existed when an
        ID was present in multiple scope collections (e.g. Home, where
        legacy migration duplicated docs across `memory-global` and
        `memory-workspace-system-main`).

        Pass an explicit `collection` to target a single collection (used
        by the undo journal, which records the exact write target).
        """
        from app.services.memory_service import (
            get_memory_service,
            GLOBAL_COLLECTION,
            _workspace_collection,
        )
        doc_id = params.get("id", "").strip()
        if not doc_id:
            return {"error": "id is required"}
        explicit_collection = params.get("collection")

        try:
            ms = get_memory_service()

            if explicit_collection:
                deleted = ms.delete_memory(doc_id, collection=explicit_collection)
                if deleted:
                    return {
                        "success": True,
                        "deleted_from": [explicit_collection],
                        "count": 1,
                        "message": f"Memory {doc_id} deleted from {explicit_collection}",
                    }
                return {"success": False, "error": f"Failed to delete memory {doc_id}"}

            env_workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
            if env_workspace_id and env_workspace_id != "system-main":
                scope_collections = [_workspace_collection(env_workspace_id)]
            else:
                scope_collections = [GLOBAL_COLLECTION, _workspace_collection("system-main")]

            deleted_from = ms.delete_memory_cascade(doc_id, scope_collections)
            if not deleted_from:
                return {
                    "success": False,
                    "error": f"Memory {doc_id} not found in current scope",
                    "searched": scope_collections,
                }
            return {
                "success": True,
                "deleted_from": deleted_from,
                "count": len(deleted_from),
                "message": (
                    f"Memory {doc_id} deleted from {len(deleted_from)} "
                    f"collection(s): {', '.join(deleted_from)}"
                ),
            }
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
        """List active CLI subprocess sessions, scoped to the current workspace by default."""
        import time
        from app.services.cli_session_registry import get_cli_session_registry
        registry = get_cli_session_registry()
        current_pid, scoped = _current_workspace_scope()
        scope = (params.get("scope") or "").lower()
        now = time.time()

        all_sessions = registry.list_active()
        if scope == "all" or not scoped:
            filtered = all_sessions
            scope_label = "all"
        else:
            filtered = [s for s in all_sessions if (s.workspace_id or "") == current_pid]
            scope_label = "workspace"

        return {
            "success": True,
            "scope": scope_label,
            "workspace_id": current_pid if scope_label == "workspace" else None,
            "sessions": [
                {
                    "id": s.id,
                    "pid": s.pid,
                    "sessionId": s.session_id,
                    "chatId": s.chat_id,
                    "workspaceId": s.workspace_id,
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

        Defaults to the current workspace; pass scope='all' for system-wide.
        """
        from app.services.worker_session_store import get_worker_session_store
        try:
            store = get_worker_session_store()
            session_id = params.get("session_id")

            current_pid, scoped = _current_workspace_scope()
            scope = (params.get("scope") or "").lower()
            if scope == "all" or not scoped:
                filter_pid: str | None = None
                scope_label = "all"
            else:
                filter_pid = current_pid
                scope_label = "workspace"

            sessions = store.get_sessions(session_id=session_id)
            if filter_pid:
                sessions = [s for s in sessions if (s.get("workspace_id") or "") == filter_pid]
            status_filter = params.get("status")
            if status_filter:
                sessions = [s for s in sessions if s.get("status") == status_filter]
            limit = params.get("limit", 10)
            sessions = sessions[:limit]

            base = {
                "success": True,
                "scope": scope_label,
                "workspace_id": filter_pid,
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

            # The session JSON only carries a short preview of the result.
            # The full untruncated result lives in worker_tasks.result_summary
            # (Text column) again as of the 2026-05-26 truncation fix, so read
            # it from the DB and prefer that over the UI preview.
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
                                "workspace_id": row.workspace_id,
                                "card_id": row.card_id,
                                "intent": row.action,
                                "model": row.model,
                                "status": row.status,
                                "summary": row.description,
                            }
            except Exception as db_err:
                logger.warning(f"[mcp.workers.get_result] DB read failed: {db_err}")

            # Resolve the structured worker.complete payload (findings,
            # pointers, etc.) — supervisor first (live, in-memory), then the
            # on-disk sidecar (survives restart / GC). This is what the
            # dispatcher actually needs to act; the .md artifact is verbose
            # narration on top.
            from app.services.worker_artifact_store import read_completion
            from app.services.worker_supervisor import get_worker_supervisor
            completion = get_worker_supervisor().get_completion_payload(task_id)
            if not completion:
                completion = read_completion(task_id)

            if session is None:
                # Last-resort fallback: the in-memory supervisor and the DB
                # row may have both been GC'd, but the artifact on disk has
                # no TTL. If we can find one, reconstruct a minimal payload
                # from its frontmatter so the dispatcher gets "the worker
                # did finish" instead of an "expired" guess.
                from app.services.worker_artifact_store import read_artifact_meta
                meta = read_artifact_meta(task_id)
                if meta is not None:
                    reconstructed: dict = {
                        "success": True,
                        "task_id": task_id,
                        "status": meta.get("status") or "completed",
                        "intent": meta.get("intent"),
                        "model": meta.get("model"),
                        "workspace_id": meta.get("workspace_id"),
                        "card_id": meta.get("card_id"),
                        "session_id": meta.get("session_id"),
                        "summary": (
                            "Reconstructed from on-disk artifact (in-memory "
                            "tracking expired). Use voxyflow.workers.read_artifact "
                            "to read the full output."
                        ),
                        "artifact_path": meta.get("path"),
                        "artifact_chars": meta.get("chars"),
                        "artifact_written_at": meta.get("written_at"),
                        "source": "artifact_frontmatter",
                    }
                    if completion:
                        reconstructed["completion"] = completion
                    return reconstructed
                return {"success": False, "error": f"Worker task not found: {task_id}"}

            if full_result is not None:
                session = {**session, "result_summary": full_result}

            response = {"success": True, **session}
            if completion:
                response["completion"] = completion
            return response
        except Exception as e:
            logger.error(f"[mcp.workers.get_result] failed: {e}")
            return {"success": False, "error": str(e)}

    async def workers_read_artifact(params: dict) -> dict:
        """Read a slice of a finished worker's full raw output (.md artifact).

        Worker callbacks only carry a summarized version of the result;
        the verbatim content (file dumps, command stdout, logs) is persisted
        to ~/.voxyflow/worker_artifacts/{task_id}.md by the worker pool.
        This handler reads paginated slices of that file so the dispatcher
        can retrieve exact content on demand.

        Side effect: marks read_at in the lifecycle metadata sidecar on first
        call (idempotent). Works even after in-memory task state is purged.
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
            # read_artifact now marks read_at automatically (idempotent).
            slice_data = read_artifact(task_id, offset=offset, length=length)
            if slice_data is None:
                return {
                    "success": False,
                    "error": (
                        f"No artifact found for task {task_id}. The worker may "
                        "not have completed yet, may have produced no output, or "
                        "the artifact was already acked (call workers.list_unread to check)."
                    ),
                }
            return {"success": True, **slice_data}
        except Exception as e:
            logger.error(f"[mcp.workers.read_artifact] failed: {e}")
            return {"success": False, "error": str(e)}

    async def workers_ack_artifact(params: dict) -> dict:
        """Acknowledge a worker artifact: delete the .md file, keep metadata trace.

        Must be called after the dispatcher has consumed the artifact content.
        Sets acked_at and frees disk space. The metadata sidecar (.meta.json)
        and completion sidecar (.completion.json) are kept for audit trail.
        """
        from app.services.worker_artifact_store import ack_artifact
        task_id = (params.get("task_id") or "").strip()
        if not task_id:
            return {"success": False, "error": "task_id is required"}
        scope_err = await _enforce_task_scope(task_id, params.get("scope"))
        if scope_err is not None:
            return scope_err
        try:
            result = ack_artifact(task_id)
            return result
        except Exception as e:
            logger.error(f"[mcp.workers.ack_artifact] failed: {e}")
            return {"success": False, "error": str(e)}

    async def workers_list_unread(params: dict) -> dict:
        """List worker artifacts that have not yet been acked.

        Returns artifacts sorted by created_at desc. Each entry includes
        task_id, created_at, read_at, size_bytes, and summary_preview
        (first 200 chars of the completion summary, if available).
        """
        from app.services.worker_artifact_store import list_unread
        try:
            limit = int(params.get("limit", 50) or 50)
        except (TypeError, ValueError):
            limit = 50
        try:
            items = list_unread(limit=limit)
            return {"success": True, "unread": items, "count": len(items)}
        except Exception as e:
            logger.error(f"[mcp.workers.list_unread] failed: {e}")
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
        workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        entity_name = _kg_truncate(params.get("entity_name"), _KG_MAX_NAME)
        entity_type = _kg_truncate(params.get("entity_type"), _KG_MAX_NAME)
        if not entity_name or not entity_type:
            return {"error": "entity_name and entity_type are required"}

        try:
            eid = await kg.add_entity(entity_name, entity_type, workspace_id)
            result: dict = {"success": True, "entity_id": eid, "entity_name": entity_name}

            # Relationships
            rels_added = []
            for rel in params.get("relationships", [])[:50]:
                target = _kg_truncate(rel.get("target"), _KG_MAX_NAME)
                target_type = _kg_truncate(rel.get("target_type"), _KG_MAX_NAME) or "concept"
                predicate = _kg_truncate(rel.get("predicate"), _KG_MAX_NAME) or "related_to"
                if not target:
                    continue
                tid = await kg.add_entity(target, target_type, workspace_id)
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

            await kg.refresh_pinned_cache(workspace_id)
            logger.info(f"[mcp.kg.add] workspace={workspace_id} entity={entity_name!r} rels={len(rels_added)} attrs={len(attrs_added)}")
            return result
        except Exception as e:
            logger.error(f"[mcp.kg.add] failed: {e}")
            return {"error": str(e)}

    async def kg_query(params: dict) -> dict:
        """Search entities and relationships in the KG."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip() or "system-main"
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
            entities = await kg.query_entities(workspace_id, name=name, entity_type=entity_type, as_of=as_of, limit=limit)
            result: dict = {"entities": entities, "count": len(entities)}

            if include_rels and entities:
                rels = await kg.query_relationships(workspace_id, entity_name=name, limit=limit)
                result["relationships"] = rels

            logger.info(f"[mcp.kg.query] workspace={workspace_id} name={name!r} found={len(entities)}")
            return result
        except Exception as e:
            logger.error(f"[mcp.kg.query] failed: {e}")
            return {"error": str(e)}

    async def kg_timeline(params: dict) -> dict:
        """Chronological entity history."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        entity_name = params.get("entity_name")
        limit = _kg_clamp_limit(params.get("limit"), 50)

        try:
            events = await kg.get_timeline(workspace_id, entity_name=entity_name, limit=limit)
            logger.info(f"[mcp.kg.timeline] workspace={workspace_id} entity={entity_name!r} events={len(events)}")
            return {"events": events, "count": len(events)}
        except Exception as e:
            logger.error(f"[mcp.kg.timeline] failed: {e}")
            return {"error": str(e)}

    async def kg_invalidate(params: dict) -> dict:
        """Mark a triple or attribute as ended."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        triple_id = params.get("triple_id")
        attribute_id = params.get("attribute_id")

        if not triple_id and not attribute_id:
            return {"error": "Provide triple_id or attribute_id to invalidate"}

        try:
            ok = await kg.invalidate(triple_id=triple_id, attribute_id=attribute_id)
            await kg.refresh_pinned_cache(workspace_id)
            logger.info(f"[mcp.kg.invalidate] workspace={workspace_id} triple={triple_id} attr={attribute_id} ok={ok}")
            return {"success": ok, "invalidated": triple_id or attribute_id}
        except Exception as e:
            logger.error(f"[mcp.kg.invalidate] failed: {e}")
            return {"error": str(e)}

    async def kg_stats(params: dict) -> dict:
        """KG counts for the current workspace."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip() or "system-main"
        kg = get_knowledge_graph_service()

        try:
            stats = await kg.get_stats(workspace_id)
            logger.info(f"[mcp.kg.stats] workspace={workspace_id} stats={stats}")
            return {"success": True, "workspace_id": workspace_id, **stats}
        except Exception as e:
            logger.error(f"[mcp.kg.stats] failed: {e}")
            return {"error": str(e)}

    _heartbeat_path = Path(
        os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow"))
    ) / "sandbox" / "heartbeat.md"

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

    async def session_read(params: dict) -> dict:
        """Read session history and return a condensed timeline of key events."""
        import json
        import re as _re

        try:
            from app.services.session_store import session_store as store

            chat_id = (params.get("chat_id") or "").strip()
            if not chat_id:
                workspace_id = os.environ.get("VOXYFLOW_WORKSPACE_ID", "")
                chat_id = f"workspace:{workspace_id}" if workspace_id else ""
            if not chat_id:
                return {"success": False, "error": "chat_id required (or set VOXYFLOW_WORKSPACE_ID env var)"}

            last_n = min(max(int(params.get("last_n_messages", 200) or 200), 10), 500)
            focus = params.get("focus", "all")

            all_messages = store.load_session(chat_id)
            if not all_messages:
                return {"success": True, "chat_id": chat_id, "total_messages": 0, "timeline": "", "summary": "No messages found."}

            total = len(all_messages)
            messages = all_messages[-last_n:]

            summary_text = ""
            summarized_count = 0
            try:
                safe_id = chat_id.replace(":", "/").replace("..", "")
                data_dir = os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow"))
                summary_path = Path(data_dir) / "sessions" / f"{safe_id}.summary.json"
                if summary_path.exists():
                    summary_data = json.loads(summary_path.read_text())
                    summary_text = summary_data.get("summary_text", "")
                    summarized_count = summary_data.get("summarized_count", 0)
            except Exception:
                summarized_count = 0

            timeline: list[dict] = []
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                ts = msg.get("timestamp", msg.get("created_at", ""))
                ts = ts[:19] if isinstance(ts, str) else ""

                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    ).strip()
                if not content:
                    continue

                content_lower = content.lower()

                if role == "user":
                    if content.startswith("[SYSTEM:") and len(content) > 500:
                        first_line = content.split("\n")[0][:200]
                        if focus != "decisions":
                            timeline.append({"ts": ts, "role": "system", "event": "worker_event", "text": first_line})
                        continue
                    is_go = content.strip().lower() in ("go", "ok", "oui", "yes", "go!", "go ?", "go?")
                    if is_go:
                        timeline.append({"ts": ts, "role": "user", "event": "go_signal", "text": "✅ GO"})
                    elif len(content) > 5:
                        timeline.append({"ts": ts, "role": "user", "event": "instruction", "text": content[:300]})

                elif role == "assistant":
                    # Note: legacy <delegate> XML markup no longer parsed (removed 2026-05-27).
                    # Worker delegations are now tracked via native voxyflow.delegate tool_use.
                    if focus != "delegates" and "<delegate>" not in content:
                        if len(content) < 20:
                            continue
                        keywords = (
                            "plan", "go?", "install", "deploy", "ssh", "playwright", "brain", "m5max",
                            "dashboard", "fix", "repair", "script", "worker", "je vais", "on va",
                            "je relis", "j'ai relu", "voici", "résumé", "confirmé", "annulé",
                        )
                        if any(kw in content_lower for kw in keywords) or len(content) < 400:
                            timeline.append({"ts": ts, "role": "assistant", "event": "decision", "text": content[:300]})

            lines: list[str] = []
            if summary_text and summarized_count > 0:
                covered_end = messages[0].get("timestamp", "")[:19] if messages else ""
                lines.append(f"=== SUMMARY (first {summarized_count} messages, before {covered_end}) ===")
                lines.append(summary_text[:1500])
                lines.append("")

            lines.append(f"=== TIMELINE (last {len(messages)} of {total} messages) ===")
            for event in timeline:
                ts_str = event.get("ts", "")[-8:] if event.get("ts") else "??:??:??"
                role_icon = "👤" if event["role"] == "user" else ("🤖" if event["role"] == "assistant" else "⚙️")
                lines.append(f"[{ts_str}] {role_icon} {event['text']}")

            if not timeline:
                lines.append("(no notable events found in scanned range)")

            return {
                "success": True,
                "chat_id": chat_id,
                "total_messages": total,
                "scanned": len(messages),
                "events_found": len(timeline),
                "timeline": "\n".join(lines),
            }
        except Exception as e:
            logger.error(f"[mcp.session.read] failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    handlers: dict = {
        "heartbeat_read": heartbeat_read,
        "heartbeat_write": heartbeat_write,
        "session_read": session_read,
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
        "workers_ack_artifact": workers_ack_artifact,
        "workers_list_unread": workers_list_unread,
        "kg_add": kg_add,
        "kg_query": kg_query,
        "kg_timeline": kg_timeline,
        "kg_invalidate": kg_invalidate,
        "kg_stats": kg_stats,
        "voxyflow_delegate": voxyflow_delegate_handler,
    }

    return handlers


async def voxyflow_delegate_handler(params: dict) -> dict:
    """Handler for the voxyflow.delegate MCP tool.

    Validates the strict JSON schema, then registers the delegate payload for
    the orchestrator to spawn a background worker.

    In-process mode (SSE / FastAPI): writes directly to ClaudeService._pending_delegates
    so the orchestrator's ``pop_pending_delegates`` collects it after the stream.

    Subprocess mode (stdio / Codex MCP): ClaudeService singleton is unavailable
    (separate OS process), so the payload is POSTed asynchronously to the
    FastAPI backend at ``/api/worker-tasks/delegate-queue``, which writes it into
    ``ClaudeService._pending_delegates`` for the orchestrator to pick up.

    NOTE: This handler is NOT yet invoked from api_caller.py paths — those use the
    ``_call_api_stream_with_delegate`` / ``_call_api_stream_openai_with_delegate``
    methods directly.  This handler is only reached when Claude calls
    ``voxyflow.delegate`` via MCP tool_use (CLI+MCP path).
    """
    from app.tools.delegate_tool import validate_delegate_input, make_tool_result_error

    ok, err = validate_delegate_input(params)
    if not ok:
        return {"success": False, "error": "VALIDATION_FAILED", "message": err,
                "hint": "Fix the payload fields: action (string) + description (string) required."}

    # Best-effort: add to ClaudeService pending delegates
    chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
    try:
        from app.services.claude_service import ClaudeService
        svc = ClaudeService._instance
        if svc is not None and chat_id:
            # In-process path (FastAPI / SSE mode): write directly to pending store.
            svc._pending_delegates.setdefault(chat_id, []).append(dict(params))
            logger.info(
                f"[voxyflow.delegate MCP] Queued for chat {chat_id}: "
                f"action={params.get('action')}"
            )
        elif chat_id:
            # Subprocess mode (mcp_stdio.py is a separate OS process from FastAPI).
            # Module-level dicts are not shared across processes, so we POST the
            # payload to the FastAPI backend via HTTP instead.  Use the shared
            # async client (base_url=VOXYFLOW_API_BASE) so we never block the
            # event loop with a synchronous request.
            #
            # ``params`` is already schema-validated, so forwarding all non-None
            # fields (action, description, complexity, context, card_id) keeps
            # the "one worker per card" dedup and card attachment intact.
            body = {"chat_id": chat_id, **{k: v for k, v in params.items() if v is not None}}
            try:
                # Reuse the shared persistent async client (base_url=VOXYFLOW_API_BASE).
                # Imported locally to avoid a circular import at module load time.
                from app.mcp_server import _get_http_client
                client = _get_http_client()
                resp = await client.post("/api/worker-tasks/delegate-queue", json=body)
                resp.raise_for_status()
                logger.info(
                    f"[voxyflow.delegate MCP/stdio] POSTed delegate to backend for chat {chat_id}: "
                    f"action={params.get('action')}"
                )
            except Exception as http_err:
                logger.warning(f"[voxyflow.delegate MCP/stdio] HTTP queue failed: {http_err}")
        else:
            logger.warning("[voxyflow.delegate MCP] No chat_id available — delegate lost. Set VOXYFLOW_CHAT_ID.")
    except Exception as e:
        logger.warning(f"[voxyflow.delegate MCP] Could not queue delegate: {e}")

    return {
        "success": True,
        "status": "delegated",
        "message": (
            f"Task '{params.get('action')}' dispatched to background worker. "
            "The worker will execute the task and report results back."
        ),
    }
