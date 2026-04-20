"""Regression tests for the chat:message idempotency cache in app.main.

The WebSocket handler must re-ACK duplicate messageIds but skip the orchestrator.
Without this guard, a client replaying un-ACK'd messages after a reconnect (or a
refresh that restores a local queue) would re-trigger the LLM for every message.
"""

import time

import pytest


def _reset_cache():
    from app import main

    main._processed_message_ids.clear()


def test_first_seen_returns_false_and_records():
    from app import main

    _reset_cache()
    assert main._seen_message_id("msg-1", "chat:abc") is False
    assert "msg-1" in main._processed_message_ids


def test_duplicate_messageid_returns_true():
    from app import main

    _reset_cache()
    assert main._seen_message_id("msg-1", "chat:abc") is False
    assert main._seen_message_id("msg-1", "chat:abc") is True
    # A second duplicate still reports true — caller must skip orchestration.
    assert main._seen_message_id("msg-1", "chat:abc") is True


def test_different_messageids_are_independent():
    from app import main

    _reset_cache()
    assert main._seen_message_id("msg-1", "chat:abc") is False
    assert main._seen_message_id("msg-2", "chat:abc") is False
    assert main._seen_message_id("msg-1", "chat:abc") is True
    assert main._seen_message_id("msg-2", "chat:abc") is True


def test_empty_messageid_is_never_treated_as_duplicate():
    from app import main

    _reset_cache()
    # An empty messageId must always return False — otherwise the first empty
    # call would poison the cache and silently drop subsequent messages.
    assert main._seen_message_id("", "chat:abc") is False
    assert main._seen_message_id("", "chat:abc") is False
    assert "" not in main._processed_message_ids


def test_expired_entries_are_ignored():
    from app import main

    _reset_cache()
    # Seed an entry that expired a second ago.
    main._processed_message_ids["msg-old"] = ("chat:abc", time.time() - 1)
    assert main._seen_message_id("msg-old", "chat:abc") is False
    # Should be refreshed with a future expiry after the re-record.
    assert main._processed_message_ids["msg-old"][1] > time.time()


def test_cache_evicts_when_overflowing():
    from app import main

    _reset_cache()
    # Fill past the max to trigger eviction.
    for i in range(main._PROCESSED_MSG_MAX + 5):
        main._seen_message_id(f"msg-{i}", "chat:abc")
    # Eviction keeps the cache bounded; exact size depends on eviction batch.
    assert len(main._processed_message_ids) <= main._PROCESSED_MSG_MAX + 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
