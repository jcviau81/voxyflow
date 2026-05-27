# Voxyflow — Roadmap

> **Voice-first automated development workflow.** Voxyflow is a self-hosted,
> multi-provider AI harness that doesn't depend on any single LLM vendor.
> Bring your own model, bring your own tools, run it on your hardware.

Last updated: 2026-05-27 · See [GitHub Projects](https://github.com/jcviau81/voxyflow/projects) for the live board.

---

## 🎯 Vision

Voxyflow is the **voice-first orchestration layer** between you and your AI
coding agents. It's not another chat UI — it's a workspace where cards,
memory, knowledge graph, wiki, and worker subprocesses all coordinate to
turn voice/text intent into shipped code.

**Three commitments**:
1. **Provider-agnostic** — Claude Code, Codex CLI, Ollama/local, and OpenAI-compatible APIs all run today; swap at any time
2. **Self-hosted by default** — your data, your machine, your rules
3. **Voice as a first-class input** — not a gimmick, the primary modality

---

## 🚧 Now (current focus)

The next 4-6 weeks. These are mostly sequential — each unblocks the rest.

### 0. 🧱 Dev/prod infrastructure split *(critical)*
**Why**: We can't safely develop Voxyflow *on* the running Voxyflow.
**What**: Dedicated dev instance, strategic branches (`feature/*` → `dev` →
`main`, with `main` protected), CI baseline (lint, type check, build) and
auto-deploy of `dev` to the dev instance.

### 1. ✅ Multi-provider runner parity *(shipped 2026-05-27)*
**Codex CLI is now a complete execution path** — dispatcher + workers run on
Codex CLI (ChatGPT account auth), validated end-to-end via live smoke test
(2-turn chat + dispatcher→worker→complete delegation).

Shipped:
- Thread persistence via `codex exec resume` — conversations survive across turns without replaying full history
- Arg-ordering fix — root flags (`-a/-C/-m/-s`) must precede `exec`; subcommand flags follow. Caught and fixed from a live crash.

**Active provider paths today**: Claude Code (primary), Codex CLI, Ollama/local, OpenAI-compatible APIs.

Still in progress for Codex:
- **Steerable strategy** — live stdin steering isn't portable the same way as Claude; decision pending between degraded `cancel + resume` and explicit opt-out
- **CI validation suite** — manual E2E smoke test covers the critical path today but isn't reproducible in CI; formal suite to be defined

### 2. 🔌 Configurable MCP servers
**Why**: Tech debt — some MCP integrations are hardcoded. Users have no
clean way to plug in their own (Notion, Linear, GitHub, Slack, custom…).
**What**: Global + per-workspace MCP server registry, UI to add/edit/test
servers, proper secrets handling.

### 3. 🐳 Container bundle — Phase 1 *(next priority)*
**Why**: `git pull` installs are fragile; the expected entry point is
`docker compose up`.
**What**: Reproducible images for the core and the voice synthesis side,
plus **per-workspace container isolation** so concurrent workspaces stop
stepping on each other's services.

### 4. ⌨️ Extended CLI
**Why**: Power users want terminal-first access; SSH/remote needs it.
**What**: `voxyflow card / workspace / wiki / memory` inline commands,
then a full `voxyflow tui` (k9s/lazygit-style).

---

## 🔜 Next (1-3 months)

- **🧪 End-to-end smoke-test runner** — becomes the dev→prod promotion gate
- **🧠 Per-workspace memory rework** — prerequisite for full workspace isolation (also prerequisite for Docker Phase 1)
- **📚 Documentation overhaul** — slim README, container-first install, glossary
- **🧹 Workspace rename regression sweep** — catch leftovers from the Project→Workspace migration
- **📣 Positioning refresh** — narrative around being the harness that outlives any single vendor's API change

---

## 🌱 Later (exploring)

- **🎯 RAG benchmark suite** — golden set + recall@k + CI gate before any embedding/chunking change
- **Hosted Pro** — optional managed offering and LLM provider partnerships
- **Hardened workspace isolation** — multi-tenant scenarios (Phase 2)
- **Wake word + voice routing** — "Hey Voxy" always-on

---

## 🧪 How we ship

- `main` is **protected** — every change goes through a PR
- `feature/*` → `dev` (auto-deployed to the dev instance) → human validation → `main`
- CI runs lint + type check + build on every PR
- Releases are tagged; container images are published once Phase 1 is stable

---

## 📦 Recently shipped

- **Codex CLI runner parity** *(2026-05-27)* — Codex CLI (ChatGPT account auth) is now a complete execution path: dispatcher + workers, thread persistence via `codex exec resume`, arg-ordering fix. Live E2E smoke test passed.
- **Prompt footprint −55%** and **context footprint −53%** across dispatcher and workers
- **Workspace memory scoping fix** — workspace memory no longer leaks across workspaces
- **Ledger auto-scoping** — eliminated a class of cross-workspace bugs
- **1M context toggle** for the long-context model in workspace settings
- **Improved model picker UI** in workspace settings
- **Project → Workspace** terminology migration (UI + API + docs)
- **WebSocket duplication fix** in the dispatcher event stream
- **Dispatcher protocols consolidated** — single coherent path regardless of provider

---

## 🤝 Contributing

Voxyflow is open source. See `CONTRIBUTING.md` for the PR workflow and
dev setup.
