# Live scenario tests

End-to-end QA scenarios that drive the **real deployed app** (backend-served
bundle on :8000) with **real LLM calls** — the dispatcher answers, inline MCP
tools fire, and S3 spawns an actual claude-CLI worker subprocess.

They are NOT part of the regular e2e suite (`tests/e2e/`, vite dev, cheap):
they cost tokens, run serially, and can take minutes.

```bash
# all scenarios (backend up on :8000, claude CLI logged in)
npx playwright test --config=playwright.live.config.ts

# one scenario
npx playwright test --config=playwright.live.config.ts 02-dispatcher-inline
```

| Spec | What it proves |
|------|----------------|
| `01-board-realtime` | API-side card changes appear on the board live over WS |
| `02-dispatcher-inline` | Simple CRUD asked in chat is done inline by the dispatcher — cards created, **no worker spawned** |
| `03-worker-delegation` | A research request spawns a real worker that reaches a terminal state, with the live delegate badge and worker panel updating (takes minutes) |
| `04-bulk-ops` | "Archive everything" empties the board via the bulk id-list path |

Each spec creates a throwaway `QA_*` workspace and deletes it in
`afterEach`/`finally`. Artifacts go to `test-results-live/` and
`playwright-report-live/` (both gitignored).

LLM assertions are intentionally outcome-based (cards exist, worker reached a
terminal state) rather than wording-based — replies are non-deterministic.

Override the target with `LIVE_BASE_URL` (defaults to `http://localhost:8000`).
