
## Hidden UI Features (last audited 2026-04-23)

Current status of the features that were deferred in the 2026-03-20 "Hidden UI Features" note:

| Feature | Status |
|---------|--------|
| Stats tab (📊) | **Shipped.** Present in `WORKSPACE_TABS` in `frontend-react/src/components/Workspaces/WorkspaceHeader.tsx`. |
| Roadmap tab (📅) | **Dropped.** No code left in the repo; revive from git history if needed. |
| Sprints tab (🏃) | **Dropped.** No code left in the repo; revive from git history if needed. |
| `/standup` slash command | **Dropped as a slash command.** The standup feature now lives in the Stats panel via `StandupSection` (`frontend-react/src/components/Workspaces/StandupSection.tsx`) and the `/api/workspaces/{id}/standup` endpoint. |

Agile features (sprints, velocity, roadmap) remain out of scope until there's a concrete need — the kanban + autonomy flow is now the primary loop.
