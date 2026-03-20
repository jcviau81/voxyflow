
## Hidden UI Features (2026-03-20)

The following features are implemented but hidden from the interface pending a more solid core flow:

| Feature | Location | How to re-enable |
|---------|----------|-----------------|
| Stats tab (📊) | `frontend/src/components/Projects/ProjectHeader.ts` | Uncomment `stats` entry in `PROJECT_TABS` |
| Roadmap tab (📅) | Same file | Uncomment `roadmap` entry |
| Sprints tab (🏃) | Same file | Uncomment `sprint` entry |
| /standup command | `frontend/src/components/Chat/SlashCommands.ts` | Uncomment the entry |

These are not deleted — they are deferred until the kanban + core tool flow is solid.

## Hidden UI Features (2026-03-20)

The following features are implemented but hidden from the interface pending a more solid core flow:

| Feature | Location | How to re-enable |
|---------|----------|-----------------|
| Stats tab (📊) | `frontend/src/components/Projects/ProjectHeader.ts` | Uncomment `stats` in PROJECT_TABS |
| Roadmap tab (📅) | Same file | Uncomment `roadmap` in PROJECT_TABS |
| Sprints tab (🏃) | Same file | Uncomment `sprint` in PROJECT_TABS |
| /standup command | `frontend/src/components/Chat/SlashCommands.ts` | Uncomment the entry |

Decision: Focus on kanban + core tools first. Agile features (sprints, velocity, standups) deferred until the base flow is fluid.
