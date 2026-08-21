"""A worker must never claim the chat's Codex thread.

Workers share their ``chat_id`` with the workspace chat. ``_handle_event``
recorded ``thread.started`` under that chat_id for every session type, so the
next dispatcher turn resumed the *worker's* thread. Consequences, all observed:

* the dispatcher's forced ``read-only`` policy landed on a worker that was
  still running, and its next ``apply_patch`` died with
  ``bwrap: loopback: Failed RTM_NEWADDR`` (bwrap cannot start on hosts with
  ``kernel.apparmor_restrict_unprivileged_userns=1``);
* the two sessions saw each other's transcript.

Only ``session_type == "chat"`` may own the chat→thread mapping.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm.codex_backend import CodexCliBackend  # noqa: E402

CHAT_ID = "workspace:f0c3149b-853f-496c-bdfa-3dc883c9d17a"


async def _feed(backend, thread_id: str, chat_id: str):
    """Replay a thread.started event the way _call_once's reader does."""
    from app.services.llm.codex_backend import _CallContext

    await backend._handle_event(
        {"type": "thread.started", "thread_id": thread_id},
        [],
        _CallContext(),
        None,
        chat_id=chat_id,
    )


@pytest.mark.asyncio
async def test_worker_thread_does_not_overwrite_chat_thread():
    backend = CodexCliBackend()

    # The chat establishes its thread, then a worker starts on the same chat_id.
    await _feed(backend, "chat-thread-1", CHAT_ID)
    # _call_once passes "" for non-chat sessions — that is the fix under test.
    await _feed(backend, "worker-thread-2", "")

    assert backend.get_thread_id(CHAT_ID) == "chat-thread-1", (
        "the worker hijacked the chat's thread; the next dispatcher turn would "
        "resume the worker's session and force read-only onto a running worker"
    )


@pytest.mark.asyncio
async def test_chat_thread_is_still_recorded():
    backend = CodexCliBackend()
    await _feed(backend, "chat-thread-1", CHAT_ID)
    assert backend.get_thread_id(CHAT_ID) == "chat-thread-1"


@pytest.mark.asyncio
async def test_worker_still_tracks_its_own_thread_for_steer():
    """Steer resumes via the per-call result, not the chat map — keep that working."""
    from app.services.llm.codex_backend import _CallContext

    backend = CodexCliBackend()
    ctx = _CallContext()
    await backend._handle_event(
        {"type": "thread.started", "thread_id": "worker-thread-2"},
        [], ctx, None, chat_id="",
    )
    assert ctx.thread_id == "worker-thread-2"
    assert backend.get_thread_id(CHAT_ID) == ""
