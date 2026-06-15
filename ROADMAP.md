# Voxyflow — Roadmap

> **Voice-first automated development workflow.** Voxyflow is a self-hosted,
> multi-provider AI harness that doesn't depend on any single LLM vendor.
> Bring your own model, bring your own tools, run it on your hardware.

Last updated: 2026-06-15 · See [GitHub Projects](https://github.com/jcviau81/voxyflow/projects) for the live board.

---

## 🎯 Vision

Voxyflow is the **voice-first orchestration layer** between you and your AI
coding agents. It's not another chat UI — it's a workspace where cards,
memory, knowledge graph, wiki, and worker subprocesses all coordinate to
turn voice/text intent into shipped code.

**Three commitments**:
1. **Provider-agnostic** — Claude Code & Codex CLI (subscription auth), the
   native Anthropic SDK, Ollama/local, and any OpenAI-compatible API
   (OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio) all run today; swap
   any layer at any time
2. **Self-hosted by default** — your data, your machine, your rules
3. **Voice as a first-class input** — not a gimmick, the primary modality

---

## 🚧 Now (current focus)

The next tasks. These are mostly sequential — each unblocks the rest.

### 1. 🔌 Configurable MCP servers *(next priority)*
**Why**: Tech debt — some MCP integrations are hardcoded. Users have no
clean way to plug in their own (Notion, Linear, GitHub, Slack, custom…).
**What**: Global + per-workspace MCP server registry, UI to add/edit/test
servers, proper secrets handling.

### 2. ⌨️ `voxyflow tui`
**Why**: The `voxy` power CLI shipped (cards / workspaces / config / doctor
over the REST/WS API); the remaining piece of terminal-first access is an
interactive UI for SSH/remote workflows.
**What**: A full-screen `voxyflow tui` (k9s/lazygit-style) over the same API.

### 3. 🧠 Per-workspace memory rework
**Why**: Hardens the workspace-isolation guarantees and is the prerequisite
for the multi-tenant (Phase 2) explorations.
**What**: Revisit the L0/L1/L2 memory tiers and per-workspace ChromaDB
scoping so isolation is structural, not convention.

### 4. 📚 Documentation overhaul
**Why**: Onboarding still assumes tribal knowledge.
**What**: Slim README, `install.sh`-first onboarding, glossary, and a single
source of truth for the provider/worker/dispatcher model.

---

## 🔜 Next (1-3 months)

- **🎯 RAG benchmark suite** — golden set + recall@k + CI gate before any embedding/chunking change
- **🔁 CI reproducibility** — pin backend deps (lockfile/constraints) so a fresh install can't drift the suite red, and bump GitHub Actions off Node 20
- **📣 Positioning refresh** — narrative around being the harness that outlives any single vendor's API change

---

## 🌱 Later (exploring)

- **🐳 Container bundle** — `install.sh` + systemd is the supported install today; a reproducible `docker compose up` bundle (core + voice synthesis, optional per-workspace container isolation) remains a future exploration, not a committed direction
- **Hosted Pro** — optional managed offering and LLM provider partnerships
- **Hardened workspace isolation** — multi-tenant scenarios (Phase 2)
- **Wake word + voice routing** — "Hey Voxy" always-on

---

## 🧪 How we ship

- `main` is **protected** — every change goes through a PR
- `feature/*` → `dev` (auto-deployed to the dev instance) → human validation → `main`
- CI runs ruff (F821) + pytest + workspace-isolation smoke test on the backend, and typecheck + build on the frontend, for every PR
- Install is `install.sh` + systemd user services (uvicorn backend, Vite build behind Caddy); releases are tagged

---

## 📦 Recently shipped

### dev → main release *(2026-06-15)*
- **Multi-provider architecture** — native Anthropic SDK plus OpenAI-compatible providers (OpenAI, OpenRouter, Groq, Mistral, Gemini, LM Studio) and Ollama, alongside Claude/Codex CLI; named "My Providers" endpoints, capability registry, live reachability probes
- **Codex CLI parity complete** — steerable degraded `cancel + resume` strategy, capacity fallback chain, inline-first dispatcher CRUD, plus pytest validation parity (capacity / callback / cancel / steer) and a live Playwright E2E harness
- **Dispatcher ruleset overhaul** — one decision table, single dispatcher tool set in `registry.py` for any provider, tool surface hardened against oversized results, generic bulk-by-list for id-only ops
- **Worker reliability** — reduced over-delegation, completion that sticks, per-worker-class reasoning effort, per-workspace cwd sandbox, orchestration leak fixes
- **`voxy` power CLI** — `card` / `workspace` / `use` / `config` / `update` / `doctor` over the REST/WS API
- **One-shot install** — `install.sh` + systemd unit templates (replaces fragile `git pull` installs)
- **Frontend** — command palette (Ctrl+K), code splitting, kanban virtualization, stale lazy-chunk recovery, read-only Storage settings panel, sidebar footer buttons (notifications / docs / help)
- **Autonomy** — nightly memory curation + natural-language scheduled tasks; self-improving skills loop + programmatic tool calling
- **Models** — dynamic Anthropic listing, alias-only CLI models, Opus 4.8 surfaced
- **Onboarding** — Models & Providers explainer step (replaces the legacy API-key form)
- **Quality** — 83 review-confirmed bugs fixed; large module refactors (ClaudeService, api_caller, MCP tool defs, cards/workspaces route packages, PersonalityService); ChromaDB concurrent-access lock + WS reconnect retry; provider-agnostic personality prompts
- **Project → Workspace** terminology migration finished (final regression pass)

### Earlier
- **Codex CLI runner parity** *(2026-05-27)* — Codex CLI (ChatGPT account auth) as a complete execution path: dispatcher + workers, thread persistence via `codex exec resume`
- **Prompt footprint −55%** and **context footprint −53%** across dispatcher and workers
- **Workspace memory scoping fix** — workspace memory no longer leaks across workspaces; ledger auto-scoping
- **1M context toggle** and **improved model picker UI** in workspace settings
- **WebSocket duplication fix** in the dispatcher event stream

---

## 🤝 Contributing

Voxyflow is open source. See `CONTRIBUTING.md` for the PR workflow and
dev setup.
