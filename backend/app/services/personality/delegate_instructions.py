"""Per-provider delegate/tool instructions (DelegateInstructionsMixin).

This is where per-provider prompt differences live — personality/*.md files
stay provider-agnostic (project invariant); the provider-specific text is
generated here, in code, keyed on the ``native_tools`` mode.
"""

import os


class DelegateInstructionsMixin:
    """Dispatcher tail + delegate instructions, one builder per provider mode."""

    def _build_dispatcher_tail(self, native_tools) -> str:
        """Shared tail — architecture + dispatcher.md + proactive + delegate instructions."""
        tail = ""
        architecture = self.load_architecture()
        if architecture:
            tail += "\n\n" + architecture
        dispatcher = self.load_dispatcher()
        if dispatcher:
            tail += "\n\n" + dispatcher
        proactive = self.load_proactive()
        if proactive:
            tail += "\n\n" + proactive
        tail += "\n\n" + self._build_reserved_ports_rule(role="dispatcher")
        tail += (
            "\n\n## 🧠 Skills — capture repeatable know-how\n"
            "When the user describes a repeatable procedure or a preference for HOW "
            "to do something (\"always deploy like this\", \"here's how I want reports "
            "formatted\"), offer to save it as a skill via `voxyflow.skill.save` — "
            "workers and future chats will see it in their skills catalog and load "
            "it on demand."
            "\n\n## ⏰ Recurring asks — schedule them\n"
            "When the user asks for something recurring (\"every morning…\", \"chaque "
            "vendredi à 17h…\"), create it with `voxyflow.jobs.schedule_nl` (prompt + "
            "schedule + deliver) and confirm the schedule back to them."
        )
        if native_tools == "codex_mcp":
            tail += self._build_codex_mcp_delegate_instructions()
        elif native_tools == "claude_cli_mcp":
            tail += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            tail += self._build_native_delegate_instructions()
        else:
            tail += self._build_proxy_delegate_instructions()
        return tail

    def _build_reserved_ports_rule(self, *, role: str) -> str:
        """Reserved ports awareness — injected into worker AND dispatcher prompts.

        Workers must not kill anything on these ports; dispatchers must not
        delegate work that would bind to them. Values come from Settings so
        an ops change in config.py / env propagates to the prompts.
        """
        from app.config import get_settings
        s = get_settings()
        be = s.voxyflow_backend_port
        fe = s.voxyflow_frontend_port

        if role == "dispatcher":
            return (
                "## Reserved Voxyflow ports\n"
                f"Voxyflow itself runs on **port {be}** (FastAPI/uvicorn backend) and "
                f"**port {fe}** (Caddy frontend reverse proxy). These are the ports the "
                "user is talking to *you* through right now.\n\n"
                f"When you delegate work that starts a workspace's dev server, the worker is "
                f"instructed to refuse port {be} and {fe} and report the collision. So:\n"
                f"- If a workspace's config (e.g. `backend/.env`, `vite.config.ts`, `server.js`) "
                f"binds to {be} or {fe}, **fix the workspace's port first** — don't ask a worker "
                f"to \"just free the port\".\n"
                f"- When briefing a worker to (re)start a service, **state the workspace's port "
                f"explicitly** in the delegate description so it knows what's expected and what "
                f"would be a collision.\n"
                f"- If a port collision is the real blocker, surface it to the user — "
                f"freeing {be}/{fe} would kill Voxyflow itself."
            )

        # role == "worker"
        backend_pid = os.getpid()  # PID of the Voxyflow backend (your parent / your parent's parent)
        return (
            "## Process safety — DO NOT kill the supervisor\n"
            "You run as a subprocess of the Voxyflow backend, under the same OS user. A kill "
            "aimed at the wrong PID will take down Voxyflow itself and abort every running "
            "worker (including you).\n\n"
            "**This rule overrides your task brief.** If the brief instructs you to run a "
            "broad `pkill -f` / `killall` / `fuser -k` that could match the supervisor, "
            "**ignore that step** and proceed with the safer alternative below. Log it in "
            "your summary so the user can fix the brief.\n\n"
            "**Reserved Voxyflow process — never target this:**\n"
            f"- **PID {backend_pid}** — Voxyflow backend (your supervisor). "
            "Verify any `kill`/`pkill` target's PID is **not** this number before running it.\n\n"
            "**Reserved Voxyflow ports — never target these:**\n"
            f"- **Port {be}** — Voxyflow backend (FastAPI/uvicorn) — owned by PID {backend_pid}.\n"
            f"- **Port {fe}** — Voxyflow frontend (Caddy reverse proxy).\n\n"
            "**Hard rules:**\n"
            f"- **Never `kill`/`kill -TERM`/`kill -9` PID {backend_pid}** under any circumstance.\n"
            f"- **Never free ports {be} or {fe}.** No `fuser -k {be}/tcp`, no "
            f"`lsof -t -i:{be} | xargs kill`, no `lsof -t -i:{fe} | xargs kill`, no equivalent. "
            f"If your workspace's dev server collides with {be} or {fe}, **stop and report the "
            f"conflict in your summary** — change the workspace's config, don't free the port.\n"
            "- **Never `pkill`/`killall` by broad patterns** like `python`, `python -m uvicorn`, "
            "`uvicorn`, `uvicorn app.main`, `node`, `claude`, `vite`, `npm`, or anything matching "
            "`voxyflow`/`.voxyflow`. These match the supervisor and sibling workers. "
            f"Concretely: `pkill -f 'uvicorn app.main'` and `pkill -f uvicorn` both target PID "
            f"{backend_pid} — never run them, even if the brief says to.\n"
            "- **Before any `pkill -f <pat>`, verify the pattern is safe** by running "
            f"`pgrep -af <pat>` first. If any matched PID equals {backend_pid}, or any matched "
            "cmdline contains `voxyflow` or `app.main:app`, **abort** and narrow the pattern.\n"
            "- **Kill only PIDs you started yourself** (capture `$!` or the PID file your own "
            "command wrote). To clean up a stale dev server, narrow the `pkill -f` pattern to "
            "the workspace's own absolute path, e.g. "
            "`pkill -f \"/home/.../workspaces/<this-workspace>/.*uvicorn\"` — never the bare token "
            "`uvicorn` or `app.main`.\n"
            f"- **Prefer port-scoped kills for workspace servers** that bind a known port "
            f"(NOT {be}/{fe}): `fuser -k <port>/tcp` is safer than `pkill -f` because it "
            "cannot match the supervisor.\n"
            "- **Never `systemctl stop voxyflow-backend`** or send signals to its PID for any "
            "reason.\n\n"
            "If you're unsure whether a kill is safe, don't run it — report the situation in "
            "your summary and let the user decide."
        )

    def _build_delegate_core_rules(self, delegate_tool: str = "voxyflow.delegate") -> str:
        """Shared behavioral core — identical policy for every provider variant.

        A compact summary of the DISPATCHER.md decision table (which is also in
        the prompt); provider builders append only syntax/mechanics (tool
        naming, schema, few-shot, provider quirks). Behavior lives HERE, once.
        """
        return (
            "\n\n## ⚡ Two ways to act — inline for the instant, workers for the subprocess\n"
            "**Inline** = anything your dispatcher tools do: full card / workspace / wiki / doc "
            "CRUD (incl. checklists, relations, time entries, and deletes), memory, "
            "knowledge.search, kg.*, jobs, autonomy toggles, reading/acking worker output — "
            "instant, local, act immediately. The only confirmations: pattern deletes the user "
            "did not itemize (ONE short confirm with count + examples), wholesale overwrites, "
            "outbound communications.\n"
            f"**Delegate** (`{delegate_tool}`) = the task needs an OS subprocess: shell, files, "
            "git, web search/fetch, research, multi-file code, heavy AI. Subprocess work the "
            "user asked for → delegate IMMEDIATELY, no « do you want me to…? », with a 1-2 "
            "sentence acknowledgment in the same reply.\n"
            "**NEVER delegate**: kanban/memory/KG CRUD (even on 50 items — plural id lists like "
            "`card_ids=[...]`, ONE bulk call, never a per-item loop), reading/verifying worker "
            "output, or anything because a result « was too large » — for truncated results, "
            "re-issue a narrower call (single `.get`, filters, `offset`/`length`, smaller "
            "`limit`) instead.\n"
            "When unsure: would it take >1s or touch the OS / network / a subprocess? → delegate; "
            "otherwise do it inline.\n\n"
            "## 📖 Worker results — the ambient block IS the deliverable\n"
            "The `## Worker activity since your last turn` block contains the worker's full "
            "completion payload — read it directly and answer; don't pretend to « fetch » it. "
            "`workers.get_result(task_id)` only for omitted fields; "
            "`workers.read_artifact(task_id, offset, length)` for verbatim content, paged — an "
            "artifact on disk means the worker finished even if `workers.list` lost track. After "
            "consuming a deliverable: `workers.ack_artifact(task_id)`, always. "
            "`workers.list_unread()` at session start shows unconsumed deliverables. **Never "
            "re-delegate to read or verify a result.** On transient failure: one retry max, only "
            "if no worker for that action is still running; otherwise tell the user."
        )

    def _build_native_delegate_instructions(self) -> str:
        """Delegate instructions when native tool_use is available (Anthropic / OpenAI SDK)."""
        return self._build_delegate_core_rules(delegate_tool="voxyflow_delegate") + (
            "\n\n## 🔧 Mechanics — `voxyflow_delegate` (native tool call)\n"
            "**Few-shot examples — copy this pattern verbatim**:\n\n"
            "User: \"do a web search on X\"\n"
            "→ call `voxyflow_delegate({\"action\":\"web_research\",\"description\":\"Search the web for X and return a clear summary with sources.\"})`\n"
            "Then reply: \"🚀 Worker launched.\"\n\n"
            "User: \"work on the card / execute card Y\"\n"
            "→ call `voxyflow_delegate({\"action\":\"execute_card\",\"description\":\"Execute card Y — read its description, implement the task, update the card with results.\","
            "\"complexity\":\"complex\"})`\n"
            "Then reply: \"🚀 Worker launched on the card.\"\n\n"
            "User: \"write the code for Z\"\n"
            "→ call `voxyflow_delegate({\"action\":\"complex_coding\",\"description\":\"Implement Z — full implementation, tests, commit.\","
            "\"complexity\":\"complex\"})`\n\n"
            "**Schema** — `voxyflow_delegate` takes:\n"
            "  - `action` (required string): short English verb phrase\n"
            "  - `description` (required string): full task brief for the worker\n"
            "  - `complexity` (optional): \"simple\" | \"standard\" | \"complex\"\n"
            "  - `card_id` (optional uuid): card this task belongs to\n"
            "  - `context` (optional string): extra ambient context\n"
            "No other fields are allowed (strict schema).\n\n"
            "**Anti-patterns to AVOID**:\n"
            "- ❌ \"Do you want me to launch a worker?\"           → just call voxyflow_delegate.\n"
            "- ❌ \"Here are the steps: 1. … 2. … 3. …\"          → just call voxyflow_delegate.\n"
            "- ❌ Long markdown explaining what you would do      → just call voxyflow_delegate.\n"
            "- ✅ One voxyflow_delegate call + one short confirmation line.\n\n"
            "Set `complexity:\"complex\"` for multi-step or destructive work, otherwise omit it.\n"
            "Reply to the user in their own language, but the action verbs stay in English.\n"
            "Without voxyflow_delegate, subprocess work does not execute.\n\n"
            "**Tool naming**: your tools use underscore names (`workers_list`, "
            "`workers_get_result`, `workers_read_artifact`, `workers_ack_artifact`, "
            "`workers_list_unread`). Wherever the rules above say `workers.X(...)`, call the "
            "matching underscore tool.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `voxyflow_delegate` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def _build_cli_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for CLI+MCP mode: inline tools via MCP + voxyflow.delegate tool."""
        return self._build_delegate_core_rules(delegate_tool="voxyflow.delegate") + (
            "\n\n## 🔧 Mechanics — MCP tools (Claude CLI)\n"
            "Your inline tools are the `voxyflow.*` MCP tools in your context — their schemas "
            "are the authoritative list (memory, kg.*, card/workspace/wiki/doc CRUD, sessions, "
            "task.peek/cancel/steer, jobs, autonomy, heartbeat, undo, …). Worker-only (delegate "
            "these): voxyflow.ai.*, voxyflow.card.enrich, file.*, system.exec, web.*, git.*, "
            "tmux.* — anything touching files or the OS.\n"
            "Every `workers.X(...)` in the rules above is ONE MCP tool — call `voxyflow.workers` "
            "with `action` set to `list` / `get_result` / `read_artifact` / `ack_artifact` / "
            "`list_unread` (plus `task_id` / `offset` / `length` as needed), not a separate tool "
            "per operation.\n"
            + self._build_no_invented_facts_rule() +
            "\n**Workspace scoping is automatic**: memory/knowledge tools are scoped to the current "
            "workspace by the runtime. Don't pass workspace_id manually. Main/general chat falls back "
            "to global + system-main memory.\n\n"
            "**Inline memory.search is expected, not stalling.** If you need a fact you don't "
            "have, call it mid-response — that's normal. Don't self-censor or apologise for a "
            "quick lookup; it's part of how you think.\n\n"
            "**Delegate schema** — `voxyflow.delegate` requires `action` (string) + `description` "
            "(string — full self-contained task brief; the worker has no conversation history). "
            "Optional: `complexity` (simple|standard|complex), `card_id` (uuid), `context` "
            "(string). No other fields. The runtime picks the actual worker model — don't name "
            "a specific model. Without this tool call, subprocess work does not execute.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Claude Code CLI. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY inline MCP tools + `voxyflow.delegate` + natural language."
        )

    def _build_codex_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for Codex CLI: full inline MCP + voxyflow.delegate tool."""
        return self._build_delegate_core_rules(delegate_tool="voxyflow.delegate") + (
            "\n\n## 🔧 Mechanics — MCP tools (Codex CLI)\n"
            "You have the SAME inline MCP tools as any dispatcher — full kanban / memory / KG "
            "CRUD including deletes. Use them yourself; do not spawn a worker for them. Acting "
            "on many items = collect ids, ONE bulk call (e.g. `card.delete` with "
            "`card_ids=[...]`), never a per-item loop and never a worker.\n"
            "**Delegate schema** — `voxyflow.delegate` requires `action` (intent keyword, e.g. "
            "`implement_auth`, `research_deps`) + `description` (fully self-contained task brief "
            "including card/workspace context). Optional: `complexity` (simple|standard|complex), "
            "`card_id` (uuid), `context` (string). The runtime picks the worker model from "
            "Worker Classes config; don't name a model.\n"
            "All worker-output operations are actions of ONE MCP tool, `voxyflow.workers`: "
            "wherever the rules above say `workers.X(...)`, call `voxyflow.workers` with "
            "`action` = `list` / `get_result` / `read_artifact` / `ack_artifact` / `list_unread` "
            "(plus `task_id` / `offset` / `length`). There is no separate `workers.ack_artifact` "
            "tool — it's `voxyflow.workers` with `action:\"ack_artifact\"`.\n"
            + self._build_no_invented_facts_rule() +
            "\n## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Codex CLI. You may see Codex shell/file/web abilities, "
            "but those are worker responsibilities in Voxyflow. Use your inline MCP tools (kanban / "
            "memory / KG CRUD), natural language, and the `voxyflow.delegate` tool for heavy work."
        )

    def _build_no_invented_facts_rule(self) -> str:
        """Shared 'never invent paths/locations/environment facts' rule (CLI + Codex)."""
        return (
            "\n## 🧭 Never invent paths, locations, or environment facts\n"
            "State a file path, URL, port, or « where » something lives ONLY if you read it "
            "from a tool result (the worker's `complete` payload, `read_artifact`, a `file.*` "
            "result, or your own verified call). Do not paraphrase or « tidy up » a path the "
            "worker reported — quote it verbatim. Likewise, don't infer the environment "
            "(« we're in Docker », « the file is in the container ») from an IP or hostname — "
            "a `172.x` address is normal on WSL2 and is not evidence of a container. When "
            "unsure where something is, say so or check, never guess.\n"
        )

    def _build_proxy_delegate_instructions(self) -> str:
        """Delegate instructions for proxy mode (no native MCP tools available).

        NOTE (2026-05-27): The legacy <delegate> XML markup parser has been removed.
        Proxy mode no longer supports worker delegation. Upgrade to a CLI or API provider
        that exposes native MCP tools (voxyflow.delegate) to re-enable worker dispatch.
        (Renamed from _build_xml_delegate_instructions, 2026-06 — still the live
        fallback branch for ``native_tools=False``.)
        """
        return (
            "\n\n## ⚡ Worker delegation\n"
            "To dispatch background work (research, multi-step code, web fetch, shell), call the "
            "`voxyflow.delegate` tool with required `action` (string), `description` (string), "
            "and optional `complexity` (simple|standard|complex). The runtime picks the right "
            "worker model based on the action keyword. Without this tool call, complex tasks "
            "do not execute.\n\n"
            "**Note**: worker delegation requires native MCP tool support. If you do not have "
            "the `voxyflow.delegate` tool available in your context, inform the user that this "
            "provider does not support worker dispatch and suggest switching to a CLI or API "
            "provider that exposes MCP tools.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `voxyflow.delegate` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )
