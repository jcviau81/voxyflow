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
        if native_tools == "codex_mcp":
            tail += self._build_codex_mcp_delegate_instructions()
        elif native_tools == "claude_cli_mcp":
            tail += self._build_cli_mcp_delegate_instructions()
        elif native_tools:
            tail += self._build_native_delegate_instructions()
        else:
            tail += self._build_xml_delegate_instructions()
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

    def _build_native_delegate_instructions(self) -> str:
        """Delegate instructions when native tool_use is available (Anthropic / OpenAI SDK)."""
        return (
            "\n\n## ⚡ Two ways to act — inline for the simple, voxyflow_delegate for the heavy\n"
            "You can chat AND call inline dispatcher tools directly.\n"
            "**Do these INLINE — never spawn a worker for them** (instant + local; single-user DB "
            "+ undo journal make it safe): all card CRUD (create / update / move / archive / "
            "delete / duplicate + checklist / relation / time), workspace CRUD, wiki & doc CRUD, "
            "memory.save/search/get, knowledge.search, kg.*, jobs, autonomy toggles, reading/acking "
            "worker output. Looping over many items is STILL inline — « clean up the cards » = "
            "call card.list, then card.delete / card.archive on each one yourself. Never create or "
            "delegate a worker just to edit/delete/list cards.\n"
            "**You CANNOT do real subprocess work yourself** (research, web search, code, files, "
            "shell, git, deploy, heavy AI). For ALL such work you MUST call `voxyflow_delegate` — "
            "workers run on Claude and do the job.\n\n"
            "**Trigger rule** — if the user asks for subprocess / heavy work (in any language), call\n"
            "`voxyflow_delegate` IMMEDIATELY, no questions, no plan, no « do you want me to…? »:\n"
            "  run, launch, execute, research, web search, scrape, crawl, write code, debug,\n"
            "  deploy, build, implement, fix a bug, analyze a repo/file, long multi-step tasks.\n"
            "When unsure: would it take >1s or touch the OS / network / a subprocess? → delegate;\n"
            "otherwise do it inline.\n\n"
            "**Few-shot examples — copy this pattern verbatim**:\n\n"
            "User: \"run the research on gold rivers\"\n"
            "→ call `voxyflow_delegate({\"action\":\"research\",\"description\":\"Research gold-bearing rivers in Quebec — compile main rivers, historical finds, and modern prospecting tips.\","
            "\"complexity\":\"complex\"})`\n"
            "Then reply: \"🚀 Worker launched on the research.\"\n\n"
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
            "User: \"summarize this report\"\n"
            "→ call `voxyflow_delegate({\"action\":\"summarize\",\"description\":\"Summarize the attached report into 5 bullet points.\"})`\n\n"
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
            "Without voxyflow_delegate, nothing executes. Asking for confirmation = failure.\n\n"
            "## 📖 Reading worker output — NEVER spawn a worker just to read another worker\n"
            "Worker callbacks only carry a ~10K preview. The full verbatim output is on disk\n"
            "and YOU read it yourself, in chunks, via `workers_read_artifact(task_id, offset?, length?)`.\n"
            "- Output too large / 'truncated' / 'the report is in the card' →\n"
            "  call `workers_read_artifact` repeatedly with growing offsets. No re-delegation.\n"
            "- Always check `workers_read_artifact` BEFORE re-running a delegate: an artifact\n"
            "  on disk means the worker really did finish, even if `workers_list` lost track.\n"
            "- Before relaunching the same task, also call `workers_list` — if a worker is still\n"
            "  active on the same card, wait for it instead of spawning a parallel run.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat, not in a terminal. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY `voxyflow_delegate` + natural language. "
            "Never claim you can't access tools or that your knowledge is cut off — delegate instead."
        )

    def _build_cli_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for CLI+MCP mode: inline tools via MCP + voxyflow.delegate tool."""
        return (
            "\n\n## ⚡ Two ways to act\n"
            "**Inline MCP tools** (direct, fast — instant + local): memory, knowledge "
            "graph (kg.*), all card/workspace/wiki/doc CRUD incl. deletes, "
            "checklists/relations/time, sessions, workers.list/read_artifact, "
            "task.peek/cancel/steer, jobs, autonomy, heartbeat, endpoints, focus, undo. "
            "See docs/TOOLS.md or backend/app/tools/registry.py for the canonical full list.\n"
            "**Acting on MANY items at once** (archive/delete/move several cards, delete several "
            "workspaces, etc.): pass the plural id list in ONE call (e.g. card.archive with "
            "card_ids=[...], workspace.delete with workspace_ids=[...]). Do NOT loop the single-id "
            "form — collect the ids and make a single bulk call.\n\n"
            "**Worker-only** (need a subprocess): voxyflow.ai.standup/brief/health/"
            "prioritize/review_code, voxyflow.card.enrich, file.*, system.exec, "
            "web.search/web.fetch, git.*, tmux.*, anything touching files or the OS.\n\n"
            "## 📖 Reading worker output — the ambient block IS the deliverable\n"
            "The `## Worker activity since your last turn` block in your prompt contains the\n"
            "worker's full structured `voxyflow.worker.complete` payload: summary, findings,\n"
            "pointers, next_step. **That's the deliverable — read it directly and answer.**\n"
            "Don't call `workers.list` or `workers.get_result` just to find what's already in\n"
            "the block, and don't pretend you're « fetching the result » — you have it.\n"
            "NOTE: every `workers.X(...)` below is ONE MCP tool — call `voxyflow.workers` with\n"
            "`action` set to `list` / `get_result` / `read_artifact` / `ack_artifact` /\n"
            "`list_unread` (plus `task_id` / `offset` / `length` as needed), not a separate\n"
            "tool per operation.\n"
            "- Call `workers.get_result(task_id)` only when you need fields the block omitted\n"
            "  (e.g. pointers offsets to read with `read_artifact`, or full unsummarised text).\n"
            "- Call `workers.read_artifact(task_id, offset, length)` when the block points to a\n"
            "  specific section you need verbatim (logs, file content, command output). Page\n"
            "  with growing offsets if the artifact is large. NEVER re-delegate to read.\n"
            "- An artifact on disk means the worker really did finish, even if `workers.list`\n"
            "  no longer shows it. Don't say « il a expiré » — try `read_artifact` first.\n"
            "- Before delegating again on the same card: call `voxyflow.workers.list` — if a\n"
            "  worker is still active for that card, wait for it. The dispatcher will refuse\n"
            "  to spawn a parallel one anyway.\n"
            "- **After consuming a worker result** (reading artifact, saving to memory/wiki/cards):\n"
            "  call `workers.ack_artifact(task_id)` to close the loop and free disk.\n"
            "  This is ALWAYS the last step after consuming any worker deliverable.\n"
            "- At session start: `workers.list_unread()` shows artifacts from past workers\n"
            "  you have not acked yet — pick up where you left off.\n\n"
            "## 🧭 Never invent paths, locations, or environment facts\n"
            "State a file path, URL, port, or « where » something lives ONLY if you read it "
            "from a tool result (the worker's `complete` payload, `read_artifact`, a `file.*` "
            "result, or your own verified call). Do not paraphrase or « tidy up » a path the "
            "worker reported — quote it verbatim. If a worker wrote `/home/.../sandbox/...`, "
            "that IS the path; don't relocate it to a nicer-looking one. Likewise, don't infer "
            "the environment (« we're in Docker », « the file is in the container ») from an IP "
            "or hostname — a `172.x` address is normal on WSL2 and is not evidence of a "
            "container. When unsure where something is, say so or check, never guess.\n\n"
            "**Workspace scoping is automatic**: memory/knowledge tools are scoped to the current "
            "workspace by the runtime. Don't pass workspace_id manually. Main/general chat falls back "
            "to global + system-main memory.\n\n"
            "**Inline memory.search is expected, not stalling.** If you need a fact you don't "
            "have, call it mid-response — that's normal. Don't self-censor or apologise for a "
            "quick lookup; it's part of how you think.\n\n"
            "**Worker delegation**: call the `voxyflow.delegate` MCP tool for research, "
            "multi-step code, web fetch, shell commands, or any heavy AI feature "
            "(voxyflow.ai.standup/brief/health/prioritize/review_code).\n"
            "Required fields: `action` (string) + `description` (string — full self-contained "
            "task brief). Optional: `complexity` (simple|standard|complex), `card_id` (uuid), "
            "`context` (string). No other fields. "
            "The runtime picks the actual worker model — don't name a specific model. "
            "Without this tool call, complex tasks do not execute. "
            "**Default to inline for anything that's instant + local** — only delegate "
            "when you need shell access, web fetching, multi-file code edits, long "
            "reasoning passes, or one of the heavy AI features listed above.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Claude Code CLI. You may see Bash/Read/Write/WebSearch — "
            "those belong to the runtime. Use ONLY inline MCP tools + `voxyflow.delegate` + natural language."
        )

    def _build_codex_mcp_delegate_instructions(self) -> str:
        """Delegate instructions for Codex CLI: full inline MCP + voxyflow.delegate tool."""
        return (
            "\n\n## ⚡ Codex dispatcher contract — inline hands for the simple, workers for the heavy\n"
            "You have the SAME inline MCP tools as any dispatcher. **Do instant, local operations "
            "yourself, inline** — do NOT spawn a worker for them. Single-user local DB + the undo "
            "journal make inline writes/deletes safe.\n\n"
            "**Do these INLINE** (instant + local): all card CRUD — create / update / move / "
            "archive / delete / duplicate, plus checklist / relation / time sub-resources; wiki & "
            "doc CRUD; workspace CRUD; memory.save/search/get, knowledge.search, kg.*; jobs and "
            "autonomy toggles; reading and acking worker output. Loop over many items inline — e.g. "
            "« clean up the cards » = call card.list, then call card.delete / card.archive on "
            "each one yourself. NEVER create a card or spawn a worker just to delete/edit cards.\n\n"
            "**Delegate (via `voxyflow.delegate`) ONLY when the task needs a subprocess**: shell "
            "commands, reading/writing files, git, web search/fetch, research, multi-file code edits, "
            "long reasoning passes, or the heavy AI features. Then give one short confirmation.\n\n"
            "**Trigger rule** — inline everything that just reads or edits Voxyflow state (cards, "
            "wiki, docs, memory, KG, jobs, autonomy). Delegate only when the request needs "
            "shell / files / git / web / research / multi-file code / deploy / a long multi-step "
            "build. When unsure: would it take >1s or touch the OS or network? → delegate; "
            "otherwise do it inline.\n\n"
            "**Worker delegation**: call the `voxyflow.delegate` MCP tool with:\n"
            "- `action` (string, required) — intent keyword (e.g. `implement_auth`, `research_deps`)\n"
            "- `description` (string, required) — fully self-contained task brief including card/workspace context\n"
            "- `complexity` (optional) — `simple` for tiny tasks, `standard` (default), `complex` for "
            "multi-step reasoning or multi-file code\n"
            "The runtime picks the worker model from Worker Classes config; don't name a model.\n\n"
            "## 📖 Reading worker output — the ambient block IS the deliverable\n"
            "The `## Worker activity since your last turn` block in your prompt already contains\n"
            "the worker's full structured `voxyflow.worker.complete` payload: summary, findings,\n"
            "pointers, next_step. **That's the deliverable — read it directly and answer.**\n"
            "Don't call `workers.list` or `workers.get_result` just to find what's already in\n"
            "the block, and don't pretend you're « fetching the result » — you have it.\n"
            "All worker-output operations are actions of ONE MCP tool, `voxyflow.workers`:\n"
            "call it with `action` = `list` / `get_result` / `read_artifact` / `ack_artifact` /\n"
            "`list_unread` (plus `task_id` / `offset` / `length`). There is no separate\n"
            "`workers.ack_artifact` tool — it's `voxyflow.workers` with `action:\"ack_artifact\"`.\n"
            "Use `action:\"get_result\"` (task_id) only for fields the block omitted (long summary,\n"
            "full findings when truncated), and `action:\"read_artifact\"` (task_id, offset, length)\n"
            "when you need verbatim sections. Reading results is dispatcher work; doing new work is\n"
            "not — never re-delegate just to read.\n"
            "After consuming a result (memory/wiki/cards), call `action:\"ack_artifact\"` (task_id)\n"
            "to close the loop and free disk. `action:\"list_unread\"` at session start shows\n"
            "pending deliverables from previous workers.\n\n"
            "## 🧭 Never invent paths, locations, or environment facts\n"
            "State a file path, URL, port, or « where » something lives ONLY if you read it from a\n"
            "tool result (the worker's `complete` payload, `read_artifact`, a `file.*` result, or\n"
            "your own verified call). Quote the worker's path verbatim — don't « tidy it up » or\n"
            "relocate it to a nicer-looking one. Don't infer the environment (« we're in Docker »,\n"
            "« the file is in the container ») from an IP/hostname — a `172.x` address is normal on\n"
            "WSL2 and is not evidence of a container. When unsure where something is, say so or\n"
            "check; never guess.\n\n"
            "## 🚫 Not your tools\n"
            "You run inside Voxyflow's chat via Codex CLI. You may see Codex shell/file/web abilities, "
            "but those are worker responsibilities in Voxyflow. Use your inline MCP tools (kanban / "
            "memory / KG CRUD), natural language, and the `voxyflow.delegate` tool for heavy work."
        )

    def _build_xml_delegate_instructions(self) -> str:
        """Delegate instructions for proxy mode (no native MCP tools available).

        NOTE (2026-05-27): The legacy <delegate> XML markup parser has been removed.
        Proxy mode no longer supports worker delegation. Upgrade to a CLI or API provider
        that exposes native MCP tools (voxyflow.delegate) to re-enable worker dispatch.
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
