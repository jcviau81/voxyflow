"""Chat history + sliding-window summarization mixin for ClaudeService.

Extracted verbatim from app.services.claude_service.

ChatHistoryMixin expects the composing class to provide (created in
ClaudeService.__init__):
  - ``self._histories``      — _LRUDict of chat_id → list[dict] (reached into by
                               worker_pool / chat_orchestration; do NOT rename)
  - ``self._history_locks``  — _LRUDict of chat_id → asyncio.Lock
  - ``self.haiku_model`` / ``self.haiku_client`` / ``self.haiku_client_type``
  - ``self._call_api``       — provided by ApiCallerMixin
"""

import asyncio
import logging

from app.config import get_settings
from app.services.session_store import session_store
from app.services.time_context import format_message_timestamp, utc_now_iso

logger = logging.getLogger(__name__)

# Machine-generated dispatcher prompts injected by the orchestrator: worker
# auto-callbacks (worker_pool._run_debounced_callback) and direct-action
# re-triggers (delegate_dispatch). They must reach the model as input for the
# in-flight turn, but they are not real user turns — persisted history tags
# them type="system" and the reload path drops them from future model context.
_SYNTHETIC_PROMPT_PREFIXES = ("[worker-callback]", "[SYSTEM: Direct action")


def _is_synthetic_prompt(content: str) -> bool:
    """True if *content* is an orchestrator-injected pseudo-user prompt."""
    return str(content or "").startswith(_SYNTHETIC_PROMPT_PREFIXES)


class ChatHistoryMixin:
    """History helpers (accessible across layers via the ClaudeService singleton)."""

    def get_history(self, chat_id: str) -> list[dict]:
        """Return conversation history for *chat_id*, loading from the session
        store on first access.  Because ClaudeService is a singleton, this
        history is shared across all layers (fast, deep, haiku).

        NOTE: Callers that mutate the history (append) should use
        _append_and_persist() under the per-chat lock instead of
        manipulating the list directly.
        """
        if chat_id not in self._histories:
            # Drop orchestrator-injected pseudo-user prompts on reload — they
            # were one-shot inputs (the type tag is stripped by the store, so
            # match on the known prefixes). The API merges any resulting
            # consecutive same-role turns.
            self._histories[chat_id] = [
                m for m in session_store.get_history_for_claude(chat_id, limit=40)
                if not (m.get("role") == "user" and _is_synthetic_prompt(m.get("content", "")))
            ]
        return self._histories[chat_id]

    # Keep the underscore alias so existing internal callers don't break.
    _get_history = get_history

    def cleanup_chat(self, chat_id: str) -> None:
        """Drop the in-memory history for *chat_id* (no-op if absent).

        Public replacement for external callers that used to reach into
        ``self._histories.pop(chat_id, None)`` directly (e.g. worker_pool's
        sub-chat cleanup). The next get_history() reloads from the session
        store.
        """
        self._histories.pop(chat_id, None)

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        """Return the per-chat_id asyncio.Lock (created on first access)."""
        return self._history_locks[chat_id]

    async def _append_and_persist_async(self, chat_id: str, role: str, content: str,
                                        model: str | None = None, msg_type: str | None = None,
                                        session_id: str | None = None):
        """Locked, dedup-guarded append + persist.  Prefer this over the sync version."""
        async with self._get_lock(chat_id):
            history = self._get_history(chat_id)

            # Dedup guard: skip if last message has same role+content
            if history and history[-1].get("role") == role and history[-1].get("content") == content:
                logger.debug(f"[dedup] Skipping duplicate {role} message for {chat_id}")
                return

            ts = utc_now_iso()
            history.append({"role": role, "content": content, "timestamp": ts})
            msg = {"role": role, "content": content, "timestamp": ts}
            if model:
                msg["model"] = model
            if msg_type:
                msg["type"] = msg_type
            if session_id:
                msg["session_id"] = session_id
            session_store.save_message(chat_id, msg)

    def _append_and_persist(self, chat_id: str, role: str, content: str,
                            model: str | None = None, msg_type: str | None = None,
                            session_id: str | None = None):
        """Sync version with dedup guard (no async lock).
        Kept for backward compat — prefer _append_and_persist_async in async code."""
        history = self._get_history(chat_id)
        # Dedup guard: skip if last message has same role+content
        if history and history[-1].get("role") == role and history[-1].get("content") == content:
            logger.debug(f"[dedup] Skipping duplicate {role} message for {chat_id}")
            return
        ts = utc_now_iso()
        history.append({"role": role, "content": content, "timestamp": ts})
        msg = {"role": role, "content": content, "timestamp": ts}
        if model:
            msg["model"] = model
        if msg_type:
            msg["type"] = msg_type
        if session_id:
            msg["session_id"] = session_id
        session_store.save_message(chat_id, msg)

    # ------------------------------------------------------------------
    # Sliding window with summarization
    # ------------------------------------------------------------------

    async def _summarize_evicted_messages(self, chat_id: str, messages: list[dict], existing_text: str = "") -> str:
        """Use Haiku to summarize evicted messages, appending to any existing summary."""
        if not messages:
            return existing_text

        # Build the content to summarize
        convo_lines = []
        for m in messages:
            role = m.get("role", "unknown").upper()
            convo_lines.append(f"{role}: {m.get('content', '')}")
        new_convo = "\n".join(convo_lines)

        prompt_parts = []
        if existing_text:
            prompt_parts.append(f"Previous conversation summary:\n{existing_text}\n\n---\n")
        prompt_parts.append(f"New messages to incorporate:\n{new_convo}")
        prompt_parts.append(
            "\n\nWrite a concise summary (1-3 paragraphs) capturing: key decisions made, "
            "topics discussed, important context, and any pending actions or requests. "
            "Merge with the previous summary if one exists. Be factual and brief."
        )

        try:
            summary = await self._call_api(
                model=self.haiku_model,
                system="You are a conversation summarizer. Output only the summary, nothing else.",
                messages=[{"role": "user", "content": "".join(prompt_parts)}],
                client=self.haiku_client,
                client_type=self.haiku_client_type,
                use_tools=False,
                layer="dispatcher",
                chat_level="general",
            )
            return (summary or "").strip()
        except Exception as e:
            logger.warning(f"[sliding_window] Haiku summarization failed: {e}")
            # Fallback: keep existing summary unchanged
            return existing_text

    @staticmethod
    def _strip_timestamps_into_content(messages: list[dict]) -> list[dict]:
        """Convert ``[{role, content, timestamp}]`` → ``[{role, content}]``
        with the timestamp prefixed onto each content string.

        This is the single boundary where timestamps leave the in-memory
        history and enter the API payload. Native Anthropic / OpenAI-compat
        backends reject unknown keys on messages[], so we fold the
        timestamp into ``content`` here instead of passing it as metadata.
        """
        out: list[dict] = []
        for m in messages:
            content = m.get("content", "")
            ts_raw = m.get("timestamp")
            label = format_message_timestamp(ts_raw) if ts_raw else ""
            if label and isinstance(content, str) and content:
                content = f"[{label}] {content}"
            out.append({"role": m.get("role", "user"), "content": content})
        return out

    async def _get_windowed_history(self, chat_id: str) -> list[dict]:
        """Return messages for Claude API with sliding window summarization.

        If history exceeds chat_window_size, older messages are summarized
        via Haiku and injected as a context block before the recent messages.

        Per-message timestamps are folded into each ``content`` string at
        this boundary (e.g. ``[2026-05-08 14:32 EDT] {original}``) so the
        model can reason about elapsed time without leaking unknown keys
        to APIs that reject them.
        """
        settings = get_settings()
        window = settings.chat_window_size
        history = self._get_history(chat_id)

        if len(history) <= window:
            return self._strip_timestamps_into_content(history)

        # Determine what needs summarizing
        existing = session_store.load_summary(chat_id)
        already_summarized = existing["summarized_count"] if existing else 0
        cutoff = len(history) - window  # everything before this index gets summarized

        if cutoff > already_summarized:
            # New messages to evict — summarize them incrementally
            existing_text = existing["summary_text"] if existing else ""
            newly_evicted = history[already_summarized:cutoff]
            summary_text = await self._summarize_evicted_messages(chat_id, newly_evicted, existing_text)
            if summary_text:
                session_store.save_summary(chat_id, summary_text, cutoff)
        else:
            summary_text = existing["summary_text"] if existing else ""

        recent = self._strip_timestamps_into_content(history[-window:])

        if summary_text:
            summary_msg = {
                "role": "user",
                "content": (
                    f"[CONVERSATION CONTEXT — Summary of earlier messages]\n\n"
                    f"{summary_text}\n\n"
                    f"[END OF SUMMARY — The conversation continues below]"
                ),
            }
            return [summary_msg, {"role": "assistant", "content": "Understood, I have the context from our earlier conversation."}, *recent]

        return recent
