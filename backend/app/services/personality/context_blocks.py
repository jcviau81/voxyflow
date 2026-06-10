"""Chat Init blocks + dynamic context assembly (ContextBlocksMixin)."""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ContextBlocksMixin:
    """Chat Init block builders + per-turn dynamic context block."""

    # ------------------------------------------------------------------
    # Chat Init block builders (injected FIRST in all system prompts)
    # ------------------------------------------------------------------

    def build_general_chat_init(self, workspace_names: Optional[list] = None) -> str:
        """Build the Chat Init block for Home workspace chat (system-main).

        This is the system "Home" workspace's chat.
        The static base omits workspace_names — inject dynamically via build_dynamic_context_block().
        """
        bot_name = self.get_bot_name()
        return (
            f"## Who You Are\n"
            f"You are {bot_name}. This is your home — Voxyflow. You are not a generic AI exploring an unfamiliar system. "
            f"You live here. You know this place. You are already present, already oriented, already ready.\n\n"
            "Do not start by orienting yourself. Do not explain what you could do. Just be here and act.\n\n"
            "## How You Work\n"
            "When the user says something, you respond and act — in that order. "
            "If they ask you to create a card, you create it. If they want to brainstorm, you brainstorm. "
            "You don't ask for permission to do what you were clearly asked to do.\n"
            "You use your tools silently and naturally — like someone who knows their workspace.\n\n"
            "## Right Now\n"
            "You are in the Home workspace — the default workspace for cards, tasks, and conversation. "
            "If the user mentions a different workspace by name, pivot to it. "
            "Cards created here belong to the Home workspace.\n\n"
            "Do NOT say 'welcome back' on a first conversation. Greet naturally based on what they said."
        )

    def build_workspace_chat_init(self, workspace: dict) -> str:
        """Build the static Chat Init block for Workspace Chat mode.

        Dynamic details (description, card counts, recent activity) are intentionally
        omitted here to keep the system prompt cacheable. Inject them via
        build_dynamic_context_block() into the messages[] dynamic context instead.
        """
        name = workspace.get("title", "Untitled")
        bot_name = self.get_bot_name()

        return (
            f"## Workspace: {name}\n"
            f"You are {bot_name}, working on **{name}**. This is your context right now — you know this workspace, you're inside it.\n\n"
            f"You can create cards, move them, update them, assign agents, write wiki pages. "
            f"When the user asks you to do something in this workspace, do it — don't explain that you can. "
            f"Stay focused here unless they explicitly ask about something else."
        )

    def build_card_chat_init(self, workspace: dict, card: dict) -> str:
        """Build the static Chat Init block for Card Chat mode.

        Dynamic details (description, status, checklist) are intentionally omitted here
        to keep the system prompt cacheable. Inject them via build_dynamic_context_block()
        into the messages[] dynamic context instead.
        """
        workspace_name = workspace.get("title", "Untitled")
        card_title = card.get("title", "Untitled")
        bot_name = self.get_bot_name()

        return (
            f"## Chat Init — Card: {card_title}\n"
            f"Mode: Card Chat\n"
            f"## Card: {card_title}\n"
            f"You are {bot_name}, focused on this card in **{workspace_name}**. This is your current task — you're already inside it.\n\n"
            f"You are here to work on this task — not to describe what you could do. "
            f"If the user says 'implement this', you start. If they say 'write the PRD', you write it. "
            f"Act with the confidence of someone who knows exactly what they're doing."
        )

    def build_dynamic_context_block(
        self,
        chat_level: str = "general",
        workspace: Optional[dict] = None,
        card: Optional[dict] = None,
        workspace_names: Optional[list] = None,
        memory_context: Optional[str] = None,
        active_workers_context: Optional[str] = None,
        worker_classes: Optional[list[dict]] = None,
        live_state: Optional[str] = None,
        worker_events: Optional[str] = None,
        session_handoff: Optional[str] = None,
    ) -> str:
        """Build the DYNAMIC context block — injected into messages[], NOT the system prompt.

        Contains everything that changes call-to-call:
        - memory_context (per-query vector search results)
        - workspace description, tech stack, github, card counts, recent activity
        - card description, status, checklist details
        - workspace names list (for main/general chat)

        By keeping this OUT of the system prompt, the static base_prompt stays
        identical across calls → Anthropic KV cache hits.
        """
        parts: list[str] = []

        # Wall-clock "now" — first thing the model reads in dynamic context.
        # Without this, the dispatcher hallucinates the hour ("à demain"
        # mid-afternoon) and can't anchor relative phrases like "il y a 2h".
        try:
            from app.services.time_context import format_now_block
            parts.append(format_now_block())
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("format_now_block failed: %s", e)

        # Live-state heartbeat + worker activity (ambient signals) render next
        # so Voxy reads "what's the environment right now" before per-workspace
        # context. These are short, bounded blocks.
        if live_state:
            parts.append(live_state.rstrip())
        if worker_events:
            parts.append(worker_events.rstrip())
        if session_handoff:
            parts.append(session_handoff.rstrip())

        if chat_level in ("workspace", "general") and workspace:
            # Workspace chat: inject full workspace state.
            # Main/general chat with no workspace pulls the list via voxyflow.workspace.list on demand.
            name = workspace.get("title", "Untitled")
            workspace_id = workspace.get("id") or ""
            description = workspace.get("description") or "No description"
            tech_stack = workspace.get("tech_stack") or "Not specified"
            github_url = workspace.get("github_url") or "Not linked"
            all_cards = workspace.get("cards", [])
            cards = [c for c in all_cards if c.get("status") != "archived"]
            total = len(cards)
            done = sum(1 for c in cards if c.get("status") == "done")
            in_progress_cards = [c for c in cards if c.get("status") == "in-progress"]
            todo_cards = [c for c in cards if c.get("status") == "todo"]
            backlog_cards = [c for c in cards if c.get("status") == "backlog"]

            state_line = (
                f"State: {total} cards — {done} done, {len(in_progress_cards)} in progress, "
                f"{len(todo_cards)} todo, {len(backlog_cards)} backlog"
            )

            # In-progress titles
            if in_progress_cards:
                ip_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in in_progress_cards)
                in_progress_block = f"In progress:\n{ip_lines}"
            else:
                in_progress_block = "In progress: (none)"

            # #9 Needs attention: flag cards stuck too long in a status. Heuristic:
            # in_progress > 7 days since last update, or todo > 14 days. Keep it
            # short (≤3 cards) — full board is already visible above.
            stale_lines: list[str] = []
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            def _parse_ts(raw: str):
                raw = str(raw or "").strip()
                if not raw:
                    return None
                try:
                    s = raw.replace(" ", "T")
                    # Strip microseconds if any — fromisoformat handles them but
                    # sqlalchemy str() can produce "2026-04-18 10:11:12.123456".
                    if "+" not in s and "Z" not in s:
                        s = s + "+00:00"
                    s = s.replace("Z", "+00:00")
                    return datetime.fromisoformat(s)
                except Exception:
                    return None
            for c in in_progress_cards:
                ts = _parse_ts(c.get("updated_at"))
                if ts and (now - ts).days > 7:
                    stale_lines.append(
                        f"  - ⚠️ {c.get('title', 'Untitled')} (in-progress, stale {((now - ts).days)}d)"
                    )
                    if len(stale_lines) >= 3:
                        break
            if len(stale_lines) < 3:
                for c in todo_cards:
                    ts = _parse_ts(c.get("updated_at"))
                    if ts and (now - ts).days > 14:
                        stale_lines.append(
                            f"  - ⚠️ {c.get('title', 'Untitled')} (todo, stale {((now - ts).days)}d)"
                        )
                        if len(stale_lines) >= 3:
                            break
            attention_block = (
                "Needs attention:\n" + "\n".join(stale_lines)
                if stale_lines else ""
            )

            # Todo titles
            if todo_cards:
                td_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in todo_cards)
                todo_block = f"Todo:\n{td_lines}"
            else:
                todo_block = "Todo: (none)"

            # Backlog titles (top 5)
            if backlog_cards:
                top_backlog = backlog_cards[:5]
                bl_lines = "\n".join(f"  - {c.get('title', 'Untitled')}" for c in top_backlog)
                backlog_block = f"Backlog (top {len(top_backlog)}):\n{bl_lines}"
                if len(backlog_cards) > 5:
                    backlog_block += f"\n  … and {len(backlog_cards) - 5} more"
            else:
                backlog_block = "Backlog: (none)"

            blocks_joined = f"{in_progress_block}\n{todo_block}\n{backlog_block}"
            if attention_block:
                blocks_joined += f"\n{attention_block}"
            id_line = f"Workspace ID: {workspace_id}\n" if workspace_id else ""
            parts.append(
                f"## Workspace Context: {name} (LIVE — this overrides any earlier data in the conversation)\n"
                f"{id_line}"
                f"Description: {description}\n"
                f"Tech Stack: {tech_stack}\n"
                f"GitHub: {github_url}\n\n"
                f"{state_line}\n\n"
                f"{blocks_joined}"
            )

        if chat_level == "card" and card:
            # Card chat: inject full card details
            card_title = card.get("title", "Untitled")
            card_id = card.get("id", "")
            status = card.get("status", "backlog")
            priority = card.get("priority", "medium")
            agent_type = card.get("agent_type") or "general"
            description = card.get("description") or "No description"
            assignee = card.get("assignee") or "Unassigned"

            checklist = card.get("checklist_items", [])
            total_items = len(checklist)
            completed_items = sum(1 for item in checklist if item.get("done") or item.get("completed"))

            # #8 card_id inherit: if we resolved a parent workspace, surface a
            # compact header so Voxy knows the surrounding board exists. Full
            # workspace rollup stays hidden — a card chat shouldn't flood with
            # siblings — but a name + 1-line state keeps orientation.
            parent_line = ""
            if workspace:
                p_cards = [c for c in (workspace.get("cards") or []) if c.get("status") != "archived"]
                p_done = sum(1 for c in p_cards if c.get("status") == "done")
                p_ip = sum(1 for c in p_cards if c.get("status") == "in-progress")
                parent_line = (
                    f"Parent workspace: {workspace.get('title', 'Untitled')} "
                    f"({len(p_cards)} cards, {p_done} done, {p_ip} in progress)\n"
                )

            id_part = f" ({card_id})" if card_id else ""
            parts.append(
                f"## Card Details: {card_title}\n"
                f"{parent_line}"
                f"Card: {card_title}{id_part}\n"
                f"Status: {status} | Priority: {priority} | Agent: {agent_type} | Assignee: {assignee}\n"
                f"Description: {description}\n"
                f"Checklist: {completed_items}/{total_items} items done"
            )

        if memory_context:
            parts.append(f"## Retrieved fragments (may be noisy — raw semantic hits, not curated truth; scores below ~0.20 are background noise)\n{memory_context}")

        if active_workers_context:
            parts.append(f"## Background Workers Status\n{active_workers_context}")

        if worker_classes:
            # Compact one-line-per-class format — names + intent hints only.
            # Full model/provider details are lazy-loaded via voxyflow.worker_class.list when needed.
            wc_lines = []
            for wc in worker_classes:
                name = wc.get("name", "?")
                patterns = wc.get("intent_patterns") or []
                hint = f" ({', '.join(patterns[:3])})" if patterns else ""
                wc_lines.append(f"{name}{hint}")
            parts.append("## Worker Classes\n" + " · ".join(wc_lines))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Context-isolated prompt builders (general / workspace / card)
    # ------------------------------------------------------------------

    def build_general_prompt(self, workspace_names: Optional[list] = None) -> str:
        """Build STATIC system prompt for General Chat — no workspace context.

        workspace_names is accepted for backward compat but no longer embedded here.
        Dynamic context (workspace names, memory) must be injected via build_dynamic_context_block().
        """
        soul = self.load_soul()
        user = self.load_user()
        identity = self.load_identity()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files (static only)
        sections.append(self.build_general_chat_init())

        if identity:
            sections.append(identity)
        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_workspace_prompt(self, workspace: dict) -> str:
        """Build STATIC system prompt for Workspace Chat — scoped to one workspace.

        Dynamic workspace details (description, recent cards) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()
        user = self.load_user()
        agents = self.load_agents()

        sections = []

        # Chat Init FIRST — before personality files (static only)
        sections.append(self.build_workspace_chat_init(workspace))

        if soul:
            sections.append(soul)
        if agents:
            sections.append(agents)
        if user:
            sections.append(user)

        return "\n\n".join(sections)

    def build_card_prompt(self, workspace: dict, card: dict, agent_persona: Optional[dict] = None) -> str:
        """Build STATIC system prompt for Card Chat — scoped to a specific task.

        Dynamic card details (description, status, checklist) must be injected
        via build_dynamic_context_block().
        """
        soul = self.load_soul()

        sections = []

        # Chat Init FIRST — before agent persona and personality (static only)
        sections.append(self.build_card_chat_init(workspace, card))

        # Agent persona after Chat Init (if provided)
        if agent_persona and agent_persona.get("system_prompt"):
            sections.append(agent_persona["system_prompt"])

        if soul:
            sections.append(soul)

        return "\n\n".join(sections)
