#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Voxyflow Frontend Migration — Phase 5: Assembly & Missing Components
# Navigation, panels, project pages, and final wiring.
#
# Usage:
#   ./scripts/migrate-frontend-phase5.sh              # run all steps
#   ./scripts/migrate-frontend-phase5.sh --from 19    # resume from step 19
#   ./scripts/migrate-frontend-phase5.sh --step 25    # run only step 25
#   ./scripts/migrate-frontend-phase5.sh --dry-run    # print prompts without running
#   ./scripts/migrate-frontend-phase5.sh --pause      # pause between steps
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs/migration"
MAX_BUDGET="5.00"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── Parse args ──────────────────────────────────────────────────────
FROM_STEP=""
ONLY_STEP=""
DRY_RUN=false
PAUSE=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --from)   FROM_STEP="$2"; shift 2 ;;
    --step)   ONLY_STEP="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --pause)  PAUSE=true; shift ;;
    --budget) MAX_BUDGET="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"

# ── Shared context ─────────────────────────────────────────────────
CONTEXT="You are completing the Voxyflow frontend migration from vanilla TypeScript + webpack to React + Vite.

Phase 1-4 (steps 1-15) are DONE — all core components are already migrated in frontend-react/.
You are now in Phase 5: migrating navigation, layout, project pages, and assembling everything.

Key rules:
- Working directory: $REPO_ROOT
- Existing frontend: ./frontend/ (vanilla TS) — READ for reference, do NOT modify
- New frontend: ./frontend-react/ (React 18 + Vite + TypeScript) — write here
- Backend: FastAPI on :8000, WebSocket on /ws — do NOT touch
- Keep identical UI and behavior to the vanilla version
- Read the source vanilla TS file(s) thoroughly before writing React code
- Use existing React components already in frontend-react/src/components/
- Use existing stores (Zustand) in frontend-react/src/stores/
- Use existing hooks in frontend-react/src/hooks/
- Use shadcn/ui + Tailwind for all UI — match existing visual appearance
- After completing your work, run a TypeScript type-check (npx tsc --noEmit) in frontend-react/ to verify no type errors

Already migrated components you can import:
- KanbanBoard, KanbanCard (components/Kanban/)
- FreeBoard (components/Board/)
- CardDetailModal + 16 sub-components (components/CardDetail/)
- ChatWindow, MessageList, MessageBubble, ChatInput, SessionTabBar, etc. (components/Chat/)
- VoiceInput (components/Voice/)
- SettingsPage + 7 panels (components/Settings/)
- ChatProvider, useChatService (contexts/)
- WebSocketProvider (providers/)
- All Zustand stores (stores/)
- All API hooks (hooks/api/)"

# ── Step definitions ────────────────────────────────────────────────
declare -a STEPS=()
declare -A STEP_PROMPTS=()
declare -A STEP_DESCS=()
declare -A STEP_MODELS=()

add_step() {
  local id="$1" desc="$2" model="$3" prompt="$4"
  STEPS+=("$id")
  STEP_DESCS[$id]="$desc"
  STEP_MODELS[$id]="$model"
  STEP_PROMPTS[$id]="$prompt"
}

# ── Phase 5A — Navigation ──────────────────────────────────────────

add_step "16" "Migrate Sidebar" "sonnet" \
"Migrate the Sidebar component to React in frontend-react/src/components/Navigation/:
1. Read frontend/src/components/Navigation/Sidebar.ts (450 lines) thoroughly
2. Create Sidebar.tsx:
   - Logo & brand (Voxyflow)
   - Main item (home icon) — always at top, navigates to general chat
   - Favorites section — starred/favorite projects
   - Active Sessions section — recent chat sessions with status indicators
   - All projects grid (scrollable)
   - Footer icons: Settings, Docs, Help
3. Connect to useProjectStore, useSessionStore, useTabStore
4. Handle navigation events (view switching, sidebar toggle on mobile)
5. Use shadcn/ui + Tailwind, match existing visual appearance
6. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "17" "Migrate TabBar" "sonnet" \
"Migrate the TabBar component to React in frontend-react/src/components/Navigation/:
1. Read frontend/src/components/Navigation/TabBar.ts (403 lines) thoroughly
2. Create TabBar.tsx:
   - Tab list: Main tab + open project tabs
   - Each tab: emoji + label + notification dot (if unread) + close button (x)
   - '+' button to create new project
   - Middle-click to close tab
   - Click to switch active tab
   - Drag to reorder (optional, can use basic ordering)
3. Connect to useTabStore, useProjectStore, useNotificationStore
4. Use shadcn/ui + Tailwind
5. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "18" "Migrate TopBar" "sonnet" \
"Migrate the TopBar component to React in frontend-react/src/components/Navigation/:
1. Read frontend/src/components/Navigation/TopBar.ts (178 lines) thoroughly
2. Create TopBar.tsx:
   - Mobile hamburger menu button to toggle sidebar
   - Project name display (project emoji + name, or 'Main')
   - Mode pill with three toggle buttons: Fast (Sonnet), Deep (Opus), Analyzer
   - Voice buttons: auto-send toggle, auto-play responses toggle
   - Persist layer/voice settings to localStorage and sync to backend via API
3. Connect to useProjectStore for current project name
4. Use shadcn/ui + Tailwind
5. Verify build passes with npx tsc --noEmit in frontend-react/"

# ── Phase 5B — Side panels ─────────────────────────────────────────

add_step "19" "Migrate RightPanel" "sonnet" \
"Migrate the RightPanel component to React in frontend-react/src/components/RightPanel/:
1. Read frontend/src/components/RightPanel/RightPanel.ts (403 lines) thoroughly
2. Create RightPanel.tsx:
   - Two-tab interface: Opportunities | Notifications
   - Opportunities tab: CardSuggestion cards with title, description, and action buttons
   - Notifications tab: timestamped notifications (card moved, created, deleted, enriched, system)
     with icons and relative time formatting
   - Opportunity count badge
   - Toggle open/close via button or event
3. Connect to useNotificationStore
4. Use shadcn/ui + Tailwind
5. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "20" "Migrate WorkerPanel" "sonnet" \
"Migrate the WorkerPanel component to React in frontend-react/src/components/RightPanel/:
1. Read frontend/src/components/RightPanel/WorkerPanel.ts (523 lines) thoroughly
2. Create WorkerPanel.tsx:
   - Live view of Deep Worker tasks: taskId, action, description, status, elapsed time, model type
   - Status states: pending, running, done, failed, cancelled
   - Polling via TanStack Query (GET /api/worker-tasks, refetch every 3 seconds)
   - WebSocket sync for real-time updates via useWebSocket
   - Expandable results for completed tasks
   - Auto-dismiss completed tasks after 30 seconds
3. Create useWorkerTasks.ts hook in hooks/api/ for the polling query
4. Connect to WebSocketProvider for live updates
5. Use shadcn/ui + Tailwind
6. Verify build passes with npx tsc --noEmit in frontend-react/"

# ── Phase 5C — Project pages ───────────────────────────────────────

add_step "21" "Migrate ProjectList" "sonnet" \
"Migrate the ProjectList component to React in frontend-react/src/components/Projects/:
1. Read frontend/src/components/Projects/ProjectList.ts (451 lines) thoroughly
2. Create ProjectList.tsx:
   - Filter chips: All | Active | Completed | Archived
   - Summary bar with project counts per status
   - Grid layout showing project cards (emoji, name, description, status, color)
   - '+ New Project' button (triggers ProjectForm)
3. Create ProjectForm.tsx (read frontend/src/components/Projects/ProjectForm.ts, 804 lines):
   - Name, description, emoji selector, color palette
   - GitHub connect/create option
   - Template picker
   - Submit/cancel actions
   - Use React Hook Form + Zod for validation
4. Connect to useProjects hooks
5. Use shadcn/ui + Tailwind
6. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "22" "Migrate ProjectHeader" "sonnet" \
"Migrate the ProjectHeader component to React in frontend-react/src/components/Projects/:
1. Read frontend/src/components/Projects/ProjectHeader.ts (136 lines) thoroughly
2. Create ProjectHeader.tsx:
   - Project emoji + name (clickable to open project properties/form)
   - View tabs: Chat, Kanban, Board, Knowledge
   - Active tab highlighting
   - Hidden when no project is selected (Main tab)
3. Connect to useProjectStore for current project, emit view change events
4. Use shadcn/ui + Tailwind
5. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "23" "Migrate ProjectStats" "sonnet" \
"Migrate the ProjectStats component to React in frontend-react/src/components/Projects/:
1. Read frontend/src/components/Projects/ProjectStats.ts (1210 lines) thoroughly
2. Create ProjectStats.tsx:
   - Card status distribution (pie/bar chart)
   - Activity timeline
   - Agent performance metrics
   - Priority breakdown
   - Time tracking summaries
   - Use simple CSS/SVG charts or a lightweight chart library if needed (e.g. recharts)
3. Create any sub-components as needed to keep each under ~300 lines
4. Connect to useCards, useProjects hooks for data
5. Use shadcn/ui + Tailwind
6. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "24" "Migrate ProjectKnowledge + ProjectDocuments" "sonnet" \
"Migrate ProjectKnowledge and ProjectDocuments to React in frontend-react/src/components/Projects/:
1. Read frontend/src/components/Projects/ProjectKnowledge.ts (313 lines) thoroughly
2. Read frontend/src/components/Projects/ProjectDocuments.ts (276 lines) thoroughly
3. Create ProjectKnowledge.tsx:
   - Knowledge base entries list
   - Search/filter
   - Add/edit/delete entries
4. Create ProjectDocuments.tsx:
   - Document list with file info
   - Document viewer/preview
   - Upload functionality
5. Connect to appropriate API hooks
6. Use shadcn/ui + Tailwind
7. Verify build passes with npx tsc --noEmit in frontend-react/"

# ── Phase 5D — Page assembly ───────────────────────────────────────

add_step "25" "Assemble MainPage" "sonnet" \
"Create the MainPage component and replace the stub in router.tsx:
1. Read frontend/src/App.ts (672 lines) — understand the view switching logic (switchView method)
2. Create frontend-react/src/pages/MainPage.tsx:
   - Default view: ChatWindow
   - View switching between: ChatWindow, KanbanBoard, FreeBoard, ProjectList
   - View state managed via URL params or local state
   - ProjectHeader hidden on Main tab (no project selected)
   - Integrate VoiceInput alongside ChatWindow
3. Update router.tsx to use MainPage instead of the placeholder stub
4. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "26" "Assemble ProjectPage" "sonnet" \
"Create the ProjectPage component and replace the stub in router.tsx:
1. Read frontend/src/App.ts — understand how project context changes the view
2. Create frontend-react/src/pages/ProjectPage.tsx:
   - Reads project ID from URL params
   - ProjectHeader visible with view tabs
   - View switching: Chat, Kanban, Board, Knowledge, Stats, Docs
   - Default view: Chat
   - All views scoped to the selected project (pass projectId to components)
3. Update router.tsx to use ProjectPage instead of the placeholder stub
4. Verify build passes with npx tsc --noEmit in frontend-react/"

add_step "27" "Assemble AppShell" "sonnet" \
"Wire the complete AppShell layout in frontend-react/src/components/layout/AppShell.tsx:
1. Read frontend/src/App.ts (672 lines) — understand the full layout composition
2. Read the current AppShell.tsx to understand what's already there
3. Update AppShell.tsx to compose:
   - TabBar (top, full width)
   - Sidebar (left, collapsible)
   - TopBar (above main content)
   - Main content area (renders Outlet from React Router)
   - WorkerPanel (right-middle, collapsible)
   - RightPanel (far right, collapsible — Opportunities + Notifications)
4. Add responsive behavior:
   - Mobile: sidebar toggle via hamburger, panels hidden by default
   - Desktop: sidebar + panels visible, resizable optional
5. Wire global keyboard shortcuts (if any from App.ts)
6. Wire toast notifications (Toaster component)
7. Wire CardDetailModal as a global overlay (opened via card store)
8. Verify build passes with npx tsc --noEmit in frontend-react/"

# ── Phase 5E — Cleanup ─────────────────────────────────────────────

add_step "28" "Cleanup and final wiring" "sonnet" \
"Final cleanup pass on the frontend-react/ codebase:
1. Delete frontend-react/src/components/CardDetail/placeholders.tsx — it's obsolete,
   CardDetailModal.tsx already imports the real components (Relations, History, CardChat, DescriptionEditor)
2. Fix the TODO in KanbanCard.tsx:189 — wire the card execute action to ChatProvider's sendMessage
3. Clean up outdated comments in CardDetailModal.tsx (lines 5-6 say 'placeholder' but real components are used)
4. Implement 'Clear All Data' button in DataPanel.tsx (clear localStorage + reload)
5. Update SettingsPage.tsx comment (line 5) — all panels are now implemented, not placeholders
6. Verify all index.ts barrel exports are complete
7. Run npx tsc --noEmit — fix any type errors
8. Run npm run build — fix any build errors"

add_step "29" "Final validation" "sonnet" \
"Final E2E validation of the complete frontend-react/ application:
1. Run npm run build in frontend-react/ — fix any build errors
2. Run npx tsc --noEmit — must be zero type errors
3. Verify ALL routes render actual content (no more 'coming soon' stubs):
   - / (MainPage with ChatWindow default view)
   - /settings (SettingsPage with all panels)
   - /project/:id (ProjectPage with project-scoped views)
4. Verify the layout is complete:
   - TabBar at top
   - Sidebar on left
   - TopBar above content
   - WorkerPanel and RightPanel on right
5. Search for any remaining TODO comments and list them
6. Search for any remaining 'coming soon', 'placeholder', 'stub' text and list them
7. Report a final summary: what is 100% complete vs what needs manual testing"

# ─────────────────────────────────────────────────────────────────────
# Runner (same as phase 1-4 script)
# ─────────────────────────────────────────────────────────────────────

should_run() {
  local step_id="$1"
  if [[ -n "$ONLY_STEP" ]]; then
    [[ "$step_id" == "$ONLY_STEP" ]]
    return
  fi
  if [[ -n "$FROM_STEP" ]]; then
    local from_idx=-1 curr_idx=-1 i=0
    for s in "${STEPS[@]}"; do
      [[ "$s" == "$FROM_STEP" ]] && from_idx=$i
      [[ "$s" == "$step_id" ]] && curr_idx=$i
      ((i++))
    done
    [[ $curr_idx -ge $from_idx ]]
    return
  fi
  return 0
}

run_step() {
  local step_id="$1"
  local desc="${STEP_DESCS[$step_id]}"
  local prompt="${STEP_PROMPTS[$step_id]}"
  local step_model="${STEP_MODELS[$step_id]}"
  local log_file="$LOG_DIR/step-${step_id}-$(date +%Y%m%d-%H%M%S).log"
  local full_prompt="$CONTEXT

--- CURRENT STEP: $step_id — $desc ---

$prompt"

  echo ""
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${GREEN}Step $step_id:${NC} $desc  ${YELLOW}[$step_model]${NC}"
  echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

  if $DRY_RUN; then
    echo -e "${YELLOW}[DRY RUN] Would execute with model=$step_model:${NC}"
    echo "$full_prompt" | head -5
    echo "  ..."
    echo -e "${YELLOW}[DRY RUN] Log: $log_file${NC}"
    return 0
  fi

  if $PAUSE; then
    echo -e "${YELLOW}Press Enter to run, 's' to skip, 'q' to quit, 'o' to override model to opus:${NC}"
    read -r input
    [[ "$input" == "s" ]] && { echo "Skipped."; return 0; }
    [[ "$input" == "q" ]] && { echo "Quit."; exit 0; }
    [[ "$input" == "o" ]] && { step_model="opus"; echo -e "  ${YELLOW}Overridden to opus${NC}"; }
  fi

  echo -e "  Model: ${YELLOW}$step_model${NC}"
  echo -e "  Logging to: ${YELLOW}$log_file${NC}"
  echo -e "  Started at: $(date '+%H:%M:%S')"

  if claude -p \
    --model "$step_model" \
    --max-budget-usd "$MAX_BUDGET" \
    --output-format text \
    --permission-mode bypassPermissions \
    "$full_prompt" \
    > "$log_file" 2>&1; then
    echo -e "  ${GREEN}✓ Completed${NC} at $(date '+%H:%M:%S')"

    # Auto-commit after each step
    cd "$REPO_ROOT"
    if [[ -n $(git status --porcelain frontend-react/ 2>/dev/null) ]]; then
      git add frontend-react/
      git commit -m "migration step $step_id: $desc

Model: $step_model | Phase 5 — see FRONTEND_MIGRATION_PHASE5.md
Co-Authored-By: Claude <noreply@anthropic.com>"
      echo -e "  ${GREEN}✓ Committed${NC}"
    else
      echo -e "  ${YELLOW}⚠ No changes to commit${NC}"
    fi
  else
    echo -e "  ${RED}✗ Failed${NC} — check $log_file"
    echo -e "  Resume with: $0 --from $step_id"
    exit 1
  fi
}

# ── Main ────────────────────────────────────────────────────────────

echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Voxyflow Frontend Migration — Phase 5: Assembly        ║${NC}"
echo -e "${CYAN}║  ${NC}Steps: ${#STEPS[@]} total │ All sonnet │ Budget: \$$MAX_BUDGET/step${CYAN}    ║${NC}"
echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"

if [[ -n "$ONLY_STEP" ]]; then
  echo -e "Running only step: ${GREEN}$ONLY_STEP${NC}"
elif [[ -n "$FROM_STEP" ]]; then
  echo -e "Resuming from step: ${GREEN}$FROM_STEP${NC}"
fi

for step_id in "${STEPS[@]}"; do
  if should_run "$step_id"; then
    run_step "$step_id"
  fi
done

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Phase 5 complete! 🎉${NC}"
echo -e "${GREEN}  Logs: $LOG_DIR/${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
