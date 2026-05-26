# Voxyflow — Roadmap

> **Voice-first automated development workflow.** Voxyflow is a self-hosted,
> multi-provider AI harness that doesn't depend on any single LLM vendor.
> Bring your own model, bring your own tools, run it on your hardware.

Last updated: 2026-05-26 · See [GitHub Projects](https://github.com/jcviau81/voxyflow/projects) for the live board.

---

## 🎯 Vision

Voxyflow is the **voice-first orchestration layer** between you and your AI
coding agents. It's not another chat UI — it's a workspace where cards,
memory, knowledge graph, wiki, and worker subprocesses all coordinate to
turn voice/text intent into shipped code.

**Three commitments**:
1. **Provider-agnostic** — any major LLM provider works, swap them at any time
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

### 1. 🤖 Multi-provider runner parity
**Why**: One provider's runner is rock-solid; the others lag behind on
streaming, tool-use, error recovery, and context handling.
**What**: Bring every supported runner to the same feature bar so the
choice of provider is purely about cost/latency/preference, never about
which features work.

### 2. 🔌 Configurable MCP servers
**Why**: Tech debt — some MCP integrations are hardcoded. Users have no
clean way to plug in their own (Notion, Linear, GitHub, Slack, custom…).
**What**: Global + per-workspace MCP server registry, UI to add/edit/test
servers, proper secrets handling.

### 3. 🐳 Container bundle — Phase 1
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
- **🧠 Per-workspace memory rework** — prerequisite for full workspace isolation
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
