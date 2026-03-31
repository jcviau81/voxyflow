#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Voxyflow Frontend Migration — Automated Runner
# Runs each migration step as a headless Claude Code agent pass.
#
# Usage:
#   ./scripts/migrate-frontend.sh              # run all steps from the beginning
#   ./scripts/migrate-frontend.sh --from 4a    # resume from step 4a
#   ./scripts/migrate-frontend.sh --step 7     # run only step 7
#   ./scripts/migrate-frontend.sh --dry-run    # print prompts without running
#   ./scripts/migrate-frontend.sh --pause      # pause for confirmation between steps
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$REPO_ROOT/logs/migration"
PLAN="$REPO_ROOT/FRONTEND_MIGRATION.md"
MODEL="opus"
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
    --model)  MODEL="$2"; shift 2 ;;
    --budget) MAX_BUDGET="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$LOG_DIR"

# ── Shared context injected into every prompt ───────────────────────
CONTEXT="You are migrating the Voxyflow frontend from vanilla TypeScript + webpack to React + Vite.

Key rules:
- Working directory: $REPO_ROOT
- Existing frontend: ./frontend/ (vanilla TS) — READ but do NOT modify
- New frontend: ./frontend-react/ (React 18 + Vite + TypeScript) — write here
- Backend: FastAPI on :8000, WebSocket on /ws — do NOT touch
- Keep identical UI and behavior to the vanilla version
- Use the libraries listed in FRONTEND_MIGRATION.md (shadcn/ui, @dnd-kit, Zustand, TanStack Query, React Router, Picmo, react-markdown, React Hook Form + Zod)
- Read the source vanilla TS file(s) thoroughly before writing React code
- Read FRONTEND_MIGRATION.md for full context on the migration plan
- After completing your work, run a TypeScript type-check (npx tsc --noEmit) in frontend-react/ to verify no type errors"

# ── Step definitions ────────────────────────────────────────────────
# Each step: ID | Description | Prompt
# The prompt tells the agent exactly what to do in one pass.

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

# ── Phase 1: Setup + foundations ────────────────────────────────────

add_step "1" "Scaffold Vite project" "sonnet" \
"Scaffold the React + Vite project:
1. Run: npx create-vite@latest frontend-react -- --template react-ts  (in $REPO_ROOT)
2. cd frontend-react && npm install
3. Remove the default App.tsx boilerplate content, replace with a minimal 'Hello Voxyflow' placeholder
4. Verify it builds: npm run build"

add_step "2" "Configure SSL + proxy" "sonnet" \
"Configure Vite dev server in frontend-react/vite.config.ts:
1. Read FRONTEND_MIGRATION.md for the exact SSL + proxy config
2. SSL: read SSL_KEY_PATH / SSL_CERT_PATH from .env.local using loadEnv (NOT VITE_ prefixed)
3. Proxy: /api → http://localhost:8000, /ws → ws://localhost:8000
4. Create frontend-react/.env.local.example with placeholder paths (do NOT commit actual cert paths)
5. Verify the config is valid TypeScript"

add_step "3" "Install Tailwind + shadcn/ui" "sonnet" \
"Set up Tailwind CSS and shadcn/ui in frontend-react/:
1. Install and configure Tailwind CSS v4 for Vite (follow latest docs pattern)
2. Set up shadcn/ui: npx shadcn@latest init
3. Add a few base components: button, input, dialog, dropdown-menu, card
4. Set up the base theme colors to work with a dark/light mode toggle
5. Verify build passes"

add_step "4a" "Zustand core store" "sonnet" \
"Create the core Zustand store in frontend-react/src/stores/:
1. Read frontend/src/state/AppState.ts thoroughly — understand the state shape
2. Create useProjectStore.ts: projects array, CRUD operations, active project selection
3. Create useCardStore.ts: cards array, CRUD operations, filtering, mirroring ReactiveCardStore logic
4. Create useThemeStore.ts: theme (dark/light), accent color, persistence to localStorage
5. Export clean TypeScript types for all state shapes
6. All stores should use Zustand's persist middleware for localStorage sync where appropriate"

add_step "4b" "Zustand session/tab store" "sonnet" \
"Create session and tab Zustand stores in frontend-react/src/stores/:
1. Read frontend/src/state/AppState.ts — focus on session and tab management sections
2. Create useSessionStore.ts: sessions CRUD, active session, createSession, closeSession, switchSession
3. Create useTabStore.ts: openProjectTab, closeTab, switchTab, tab ordering
4. Ensure stores have proper TypeScript types matching the existing data shapes
5. Verify build passes"

add_step "4c" "Zustand messages/notifications store" "sonnet" \
"Create message and notification Zustand stores in frontend-react/src/stores/:
1. Read frontend/src/state/AppState.ts — focus on messages, activity feed, and notification sections
2. Create useMessageStore.ts: messages array, setMessages, replaceSessionMessages, clearMessages, per-session message management
3. Create useNotificationStore.ts: notifications (max 100), activity feed (max 50), opportunity badge
4. Ensure stores match existing data contracts
5. Verify build passes"

add_step "5a" "REST API hooks (TanStack Query)" "sonnet" \
"Port REST API calls to TanStack Query hooks in frontend-react/src/hooks/api/:
1. npm install @tanstack/react-query
2. Read frontend/src/services/ApiClient.ts — identify ALL REST endpoints
3. Create useCards.ts: useCards query, useCreateCard, usePatchCard, useDeleteCard, useArchiveCard, useDuplicateCard, useCloneCard, useMoveCard mutations
4. Create useProjects.ts: useProjects query, useCreateProject, useUpdateProject mutations
5. Create useSessions.ts: useSessions query, useSyncSessions, useDeleteSession mutations
6. Create useAgents.ts: useAgents query
7. Set up QueryClientProvider in App.tsx
8. Use proper query keys, stale times, and optimistic updates where appropriate
9. Verify build passes"

add_step "5b" "WebSocket lifecycle hook" "opus" \
"Create the WebSocket lifecycle hook in frontend-react/src/hooks/:
1. Read frontend/src/services/ApiClient.ts — focus on WS connection lifecycle (connect, disconnect, reconnect, heartbeat, exponential backoff)
2. Create useWebSocket.ts: manages a single persistent WS connection
   - Connect with auth token
   - Exponential backoff reconnection (preserve existing timing/logic)
   - Heartbeat/ping mechanism
   - Message handler registry (subscribe/unsubscribe pattern)
   - Connection state (connecting, connected, disconnected, reconnecting)
3. Create WebSocketProvider context that wraps the app
4. Verify build passes"

add_step "5c" "Offline queue" "opus" \
"Create the offline message queue in frontend-react/src/hooks/:
1. Read frontend/src/services/ApiClient.ts — focus on offline queue, localStorage persistence, retry on reconnect
2. Create useOfflineQueue.ts hook:
   - Queue messages when WS is disconnected
   - Persist queue to localStorage
   - Flush queue on reconnect (in order)
   - Expose queue status (pending count)
3. Integrate with the WebSocketProvider from step 5b
4. Verify build passes"

add_step "6" "React Router + auth" "sonnet" \
"Set up routing and authentication in frontend-react/:
1. npm install react-router-dom
2. Read the existing frontend to understand navigation patterns (what views/pages exist)
3. Create src/router.tsx with routes: / (board/kanban), /settings, /project/:id — match existing navigation
4. Create src/hooks/useAuth.ts: token storage, token refresh logic, isAuthenticated state
5. Create ProtectedRoute wrapper component
6. Set up the app shell layout (sidebar/header navigation matching existing UI structure)
7. Verify build passes"

# ── Phase 2: Simple components + services ───────────────────────────

add_step "7" "Migrate KanbanCard" "sonnet" \
"Migrate KanbanCard to React in frontend-react/src/components/Kanban/:
1. Read frontend/src/components/Kanban/KanbanCard.ts (719 lines) thoroughly
2. Create KanbanCard.tsx: replicate ALL visual elements and behavior
   - Card header, description preview, footer with badges
   - Vote tracking, assignee avatars (8 colors), tag colors (8 palettes)
   - Context menu (Execute, Duplicate, Clone/Move, Archive)
   - Selection mode, drag setup (prepare for @dnd-kit integration later)
   - Filters (query/priority/agent/tag)
3. Use shadcn/ui components where appropriate (DropdownMenu for context menu, Badge, Card)
4. Use Tailwind for all styling — match existing visual appearance
5. Connect to Zustand stores (useCardStore, useProjectStore)
6. Verify build passes"

add_step "8" "Migrate FreeBoard" "sonnet" \
"Migrate FreeBoard to React in frontend-react/src/components/Board/:
1. Read frontend/src/components/Kanban/FreeBoard.ts (538 lines) thoroughly
2. Create FreeBoard.tsx: replicate ALL visual elements and behavior
   - Card grid rendering with color dots
   - Header with add button
   - Empty state
   - Card element builder (title/description/footer/actions)
   - Project picker dropdown
   - Move to Kanban action
   - Add form with color selector
3. Use shadcn/ui + Tailwind, connect to Zustand stores
4. Verify build passes"

add_step "9" "Migrate ChatService" "opus" \
"Port ChatService to React context + hooks in frontend-react/src/contexts/:
1. Read frontend/src/services/ChatService.ts (738 lines) thoroughly — understand EVERY handler
2. Create ChatProvider.tsx / useChatService.ts:
   - Streaming message accumulation with safety timeouts (preserve exact logic)
   - Session-specific message routing
   - Voice auto-send with 3s silence timer
   - Force-end streaming on disconnect
   - TTS trigger via MESSAGE_RECEIVED / MESSAGE_STREAM_END events
   - Enrichment handling, model status, tool results, worker tasks, card suggestions
3. Integrate with useWebSocket from step 5b and useMessageStore from step 4c
4. Verify build passes"

# ── Phase 3: Complex components ─────────────────────────────────────

add_step "10" "Migrate KanbanBoard" "opus" \
"Migrate KanbanBoard to React in frontend-react/src/components/Kanban/:
1. npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
2. Read frontend/src/components/Kanban/KanbanBoard.ts (936 lines) thoroughly
3. Create KanbanBoard.tsx with:
   - Search bar with debounce
   - Priority/agent/tag filter chips
   - Column rendering for each status (todo/in-progress/done/archived)
   - @dnd-kit drag-drop between columns and card reordering
   - Bulk select toolbar
   - Dependency graph overlay
   - Board execution with progress tracking
   - Import/export utilities
4. Use KanbanCard from step 7, shadcn/ui, Tailwind
5. Connect to Zustand stores and API hooks
6. Verify build passes"

add_step "11a" "CardDetailModal — shell + layout" "opus" \
"Create the CardDetailModal shell in frontend-react/src/components/CardDetail/:
1. Read frontend/src/components/CardDetailModal.ts (2058 lines) — focus on: modal open/close lifecycle, overall layout structure, navigation between sections
2. Create CardDetailModal.tsx:
   - Modal shell using shadcn Dialog
   - Open/close lifecycle with URL state
   - Layout: sidebar (project picker, status, priority, assignee, dates) + main content area
   - Project picker dropdown, status/priority dropdowns, color picker
   - Agent selector, assignee/watchers with avatar grid
   - Date pickers
   - Tab navigation for content sections (will be filled in 11b/11c)
3. Create placeholder components for sections that will be built in 11b and 11c
4. Connect to Zustand stores + API mutations (usePatchCard)
5. Verify build passes"

add_step "11b" "CardDetailModal — section components" "sonnet" \
"Build CardDetailModal section components in frontend-react/src/components/CardDetail/sections/:
1. Read frontend/src/components/CardDetailModal.ts — focus on section builders
2. Create these section components:
   - TimeTracking.tsx: time tracking display with pie chart
   - Comments.tsx: nested comments with replies, add/edit/delete
   - Checklist.tsx: checklist items with drag reorder, add/toggle/delete
   - Files.tsx: file attachments with preview, upload, delete
   - Votes.tsx: vote display and toggle
3. Each component should be self-contained with its own API hooks
4. Wire them into CardDetailModal.tsx (replace placeholders from 11a)
5. Verify build passes"

add_step "11c" "CardDetailModal — relations + chat + editor" "opus" \
"Build remaining CardDetailModal sections in frontend-react/src/components/CardDetail/:
1. Read frontend/src/components/CardDetailModal.ts — focus on relations, history, chat, CodeMirror
2. Create:
   - Relations.tsx: depends-on, blocks, related-to — with add/remove
   - History.tsx: activity/history timeline
   - CardChat.tsx: embedded card-specific chat panel (reuse ChatProvider from step 9)
   - DescriptionEditor.tsx: CodeMirror editor using @uiw/react-codemirror for card description
3. npm install @uiw/react-codemirror (and language extensions as needed)
4. Wire into CardDetailModal.tsx
5. Verify build passes"

add_step "12" "Migrate VoiceInput" "sonnet" \
"Migrate VoiceInput to React in frontend-react/src/components/Voice/:
1. Read frontend/src/components/VoiceInput.ts (605 lines) thoroughly
2. Create VoiceInput.tsx:
   - Wake word toggle
   - PTT vs toggle mode detection
   - Transcript display
   - Button render (mobile/desktop handlers)
   - Recording state management
   - Auto-send debounce
   - Keyboard shortcut (Alt+V)
   - Whisper WASM worker integration via useRef (reuse existing worker)
3. Connect to ChatProvider for sending transcripts
4. Verify build passes"

add_step "13a" "ChatWindow — message list" "sonnet" \
"Build ChatWindow message rendering in frontend-react/src/components/Chat/:
1. npm install react-markdown react-syntax-highlighter @tanstack/react-virtual
2. Read frontend/src/components/Chat/ChatWindow.ts (1581 lines) — focus on message list rendering
3. Create:
   - MessageList.tsx: virtual scrolled list of messages, auto-scroll to bottom logic
   - MessageBubble.tsx: individual message rendering with markdown (react-markdown), code blocks (syntax highlighter), timestamps, avatar
   - StreamingMessage.tsx: live streaming message display
4. Handle TTS trigger on MESSAGE_RECEIVED / MESSAGE_STREAM_END
5. Connect to useMessageStore and ChatProvider
6. Verify build passes"

add_step "13b" "ChatWindow — input area + panels" "opus" \
"Build ChatWindow input and panels in frontend-react/src/components/Chat/:
1. Read frontend/src/components/Chat/ChatWindow.ts — focus on input area, menus, panels
2. Create:
   - ChatInput.tsx: textarea with paste-to-code, keyboard shortcuts (Enter/Shift+Enter/Escape), model status bar
   - SlashCommandMenu.tsx: slash commands dropdown
   - EmojiPicker.tsx: Picmo integration
   - SessionTabBar.tsx: session tabs (create, close, switch)
   - ChatSearch.tsx: search within chat messages
   - SmartSuggestions.tsx: suggested prompts/actions
3. Create ChatWindow.tsx that composes MessageList + ChatInput + all panels
4. Connect to stores and ChatProvider
5. Verify build passes"

add_step "14a" "SettingsPage — Appearance + Theme" "sonnet" \
"Build Settings appearance panel in frontend-react/src/components/Settings/:
1. Read frontend/src/components/Settings/SettingsPage.ts (2420 lines) — focus on appearance/theme section
2. Create:
   - SettingsPage.tsx: settings layout shell with sidebar navigation between panels
   - AppearancePanel.tsx: theme toggle (dark/light), accent color picker
3. Connect to useThemeStore
4. Use React Hook Form for form state
5. Verify build passes"

add_step "14b" "SettingsPage — Models + Ollama" "sonnet" \
"Build Settings models panel in frontend-react/src/components/Settings/:
1. Read frontend/src/components/Settings/SettingsPage.ts — focus on model/Ollama sections
2. Create ModelPanel.tsx:
   - Model layers configuration (default/thinking/analyzer/worker) with test buttons
   - Ollama integration: health check, dynamic model fetching
   - Model selection dropdowns
3. Use React Hook Form + appropriate API hooks
4. Wire into SettingsPage.tsx
5. Verify build passes"

add_step "14c" "SettingsPage — Voice + STT/TTS" "sonnet" \
"Build Settings voice panel in frontend-react/src/components/Settings/:
1. Read frontend/src/components/Settings/SettingsPage.ts — focus on voice/STT/TTS sections
2. Create VoicePanel.tsx:
   - STT engine selection (browser, Whisper local)
   - Whisper local configuration
   - TTS engine selection with voice preview
   - Wake word toggle
   - Auto-send configuration
3. Wire into SettingsPage.tsx
4. Verify build passes"

add_step "14d" "SettingsPage — GitHub + Workspace + Data" "sonnet" \
"Build remaining Settings panels in frontend-react/src/components/Settings/:
1. Read frontend/src/components/Settings/SettingsPage.ts — focus on GitHub, workspace, data, about sections
2. Create:
   - GitHubPanel.tsx: token setup, status check, repository connection
   - WorkspacePanel.tsx: max context window, connection settings
   - DataPanel.tsx: export data, reset data
   - AboutPanel.tsx: version info, health bar (service status)
   - JobsPanel.tsx: job scheduler UI
3. Wire all panels into SettingsPage.tsx
4. Verify build passes"

# ── Phase 4: Swap ──────────────────────────────────────────────────

add_step "15" "E2E validation" "sonnet" \
"Validate the complete frontend-react/ build:
1. Run npm run build in frontend-react/ — fix any build errors
2. Run npx tsc --noEmit — fix any type errors
3. Check that all routes are reachable: /, /settings, /project/:id
4. Verify all components are imported and rendered (no dead code / missing imports)
5. List any remaining TODO comments or placeholder components
6. Report a summary of what's complete and what needs manual testing"

# ─────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────

should_run() {
  local step_id="$1"
  if [[ -n "$ONLY_STEP" ]]; then
    [[ "$step_id" == "$ONLY_STEP" ]]
    return
  fi
  if [[ -n "$FROM_STEP" ]]; then
    # Find index of FROM_STEP and current step
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

Model: $step_model | Automated migration — see FRONTEND_MIGRATION.md
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

# Count models
SONNET_COUNT=0; OPUS_COUNT=0
for s in "${STEPS[@]}"; do
  if [[ "${STEP_MODELS[$s]}" == "sonnet" ]]; then
    SONNET_COUNT=$((SONNET_COUNT + 1))
  else
    OPUS_COUNT=$((OPUS_COUNT + 1))
  fi
done

echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  Voxyflow Frontend Migration — Automated Runner         ║${NC}"
echo -e "${CYAN}║  ${NC}Steps: ${#STEPS[@]} total │ Sonnet: $SONNET_COUNT │ Opus: $OPUS_COUNT │ Budget: \$$MAX_BUDGET/step${CYAN} ║${NC}"
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
echo -e "${GREEN}  Migration complete! 🎉${NC}"
echo -e "${GREEN}  Logs: $LOG_DIR/${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
