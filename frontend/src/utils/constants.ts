// System project — the built-in "Main" project (id matches backend SYSTEM_MAIN_PROJECT_ID)
export const SYSTEM_PROJECT_ID = 'system-main';

// API & WebSocket
// In dev, connect via webpack proxy at /ws (proxied to ws://localhost:8000/ws)
// In prod, use env var or default to the same origin's /ws
export const WS_URL = process.env.VOXYFLOW_WS_URL || 
  (typeof window !== 'undefined' 
    ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
    : 'ws://localhost:8000/ws');
export const API_URL = process.env.VOXYFLOW_API_URL || '';

// Reconnection
export const RECONNECT_MAX_ATTEMPTS = 10;
export const RECONNECT_BASE_DELAY = 1000; // ms
export const RECONNECT_MAX_DELAY = 30000; // ms
export const HEARTBEAT_INTERVAL = 30000; // 30s

// UI
export const TOAST_DURATION = 4000; // ms
export const STREAMING_CHAR_DELAY = 15; // ms per character for streaming effect
export const STREAMING_SAFETY_TIMEOUT = 30000; // 30s — force-end streaming if no completion arrives
export const MAX_MESSAGE_LENGTH = 10000;

// Kanban
export const CARD_STATUSES = ['idea', 'todo', 'in-progress', 'done'] as const;
export const CARD_STATUS_LABELS: Record<string, string> = {
  'card': '📝 Card',
  'idea': '💡 Idea',
  'todo': '📋 Todo',
  'in-progress': '🔨 In Progress',
  'done': '✅ Done',
  'archived': '📦 Archived',
};

// Agent Personas (legacy, used by old assignedAgent field)
export const AGENT_PERSONAS: Record<string, { name: string; emoji: string; description: string }> = {
  coder: { name: 'Coder', emoji: '👩‍💻', description: 'Code implementation & debugging' },
  architect: { name: 'Architect', emoji: '🏗️', description: 'System design & architecture' },
  designer: { name: 'Designer', emoji: '🎨', description: 'UI/UX design & styling' },
  devops: { name: 'DevOps', emoji: '⚙️', description: 'Infrastructure & deployment' },
  analyst: { name: 'Analyst', emoji: '📊', description: 'Requirements & analysis' },
  tester: { name: 'Tester', emoji: '🧪', description: 'Testing & quality assurance' },
  writer: { name: 'Writer', emoji: '📝', description: 'Documentation & specs' },
};

// Agent type → emoji mapping for the 6 specialized agent types (general is the default fallback, not a selectable persona)
export const AGENT_TYPE_EMOJI: Record<string, string> = {
  researcher: '🔍',
  coder: '💻',
  designer: '🎨',
  architect: '🏗️',
  writer: '✍️',
  qa: '🧪',
};

// Agent type → display info (general is the default fallback, not a selectable persona)
export const AGENT_TYPE_INFO: Record<string, { name: string; emoji: string; description: string }> = {
  researcher: { name: 'Researcher', emoji: '🔍', description: 'Research & analysis' },
  coder: { name: 'Coder', emoji: '💻', description: 'Code implementation & debugging' },
  designer: { name: 'Designer', emoji: '🎨', description: 'UI/UX design & styling' },
  architect: { name: 'Architect', emoji: '🏗️', description: 'System design & planning' },
  writer: { name: 'Writer', emoji: '✍️', description: 'Content & documentation' },
  qa: { name: 'QA', emoji: '🧪', description: 'Testing & quality assurance' },
};

// Events
export const EVENTS = {
  // Connection
  WS_CONNECTED: 'ws:connected',
  WS_DISCONNECTED: 'ws:disconnected',
  WS_MESSAGE: 'ws:message',
  WS_ERROR: 'ws:error',

  // Chat
  MESSAGE_SENT: 'chat:message:sent',
  MESSAGE_RECEIVED: 'chat:message:received',
  MESSAGE_STREAMING: 'chat:message:streaming',
  MESSAGE_STREAM_END: 'chat:message:stream-end',
  MESSAGE_ENRICHMENT: 'chat:message:enrichment',
  MODEL_STATUS: 'chat:model:status',

  // Voice
  VOICE_START: 'voice:start',
  VOICE_STOP: 'voice:stop',
  VOICE_TRANSCRIPT: 'voice:transcript',
  VOICE_ERROR: 'voice:error',
  WAKEWORD_DETECTED: "wakeword:detected",
  WAKEWORD_ERROR: "wakeword:error",

  // Navigation
  VIEW_CHANGE: 'nav:view:change',
  SIDEBAR_TOGGLE: 'nav:sidebar:toggle',

  // Tabs
  TAB_SWITCH: 'nav:tab:switch',
  TAB_OPEN: 'nav:tab:open',
  TAB_CLOSE: 'nav:tab:close',
  TAB_NOTIFICATION: 'nav:tab:notification',

  // Projects & Cards
  PROJECT_CREATED: 'project:created',
  PROJECT_UPDATED: 'project:updated',
  PROJECT_DELETED: 'project:deleted',
  PROJECT_SELECTED: 'project:selected',
  PROJECT_PROPERTIES_OPEN: 'project:properties:open',
  CARD_CREATED: 'card:created',
  CARD_UPDATED: 'card:updated',
  CARD_DELETED: 'card:deleted',
  CARD_MOVED: 'card:moved',
  CARD_SELECTED: 'card:selected',

  // Project Form
  PROJECT_FORM_SHOW: 'project:form:show',
  PROJECT_FORM_SUBMIT: 'project:form:submit',
  PROJECT_FORM_CANCEL: 'project:form:cancel',

  // UI
  TOAST_SHOW: 'ui:toast:show',
  MODAL_OPEN: 'ui:modal:open',
  MODAL_CLOSE: 'ui:modal:close',

  // Opportunities
  CARD_SUGGESTION: 'opportunities:card-suggestion',
  CREATE_CARD_FROM_SUGGESTION: 'opportunities:create-card',
  OPPORTUNITIES_COUNT: 'opportunities:count',
  OPPORTUNITIES_TOGGLE: 'opportunities:toggle',

  // Ideas (deprecated — use MAIN_BOARD events)
  IDEA_SUGGESTION: 'ideas:suggestion',
  IDEA_ADDED: 'ideas:added',
  IDEA_DELETED: 'ideas:deleted',

  // Main Board Cards
  MAIN_BOARD_UPDATED: 'mainboard:updated',
  MAIN_BOARD_CARD_CREATED: 'mainboard:card:created',
  MAIN_BOARD_CARD_DELETED: 'mainboard:card:deleted',

  // Settings
  SETTINGS_OPEN: 'settings:open',
  DOCS_OPEN: 'settings:docs:open',
  HELP_OPEN: 'settings:help:open',

  // Welcome
  WELCOME_ACTION: 'welcome:action',

  // Layers
  LAYER_TOGGLE: 'layer:toggle',

  // Slash commands
  SESSION_NEW: 'session:new',
  AGENT_SWITCH: 'agent:switch',

  // Session tabs (project/card context)
  SESSION_TAB_SWITCH: 'session:tab:switch',
  SESSION_TAB_CLOSE: 'session:tab:close',
  SESSION_TAB_NEW: 'session:tab:new',
  SESSION_TAB_UPDATE: 'session:tab:update',

  // State
  STATE_CHANGED: 'state:changed',

  // Documents
  DOCUMENT_UPLOADED: 'document:uploaded',

  // Activity Feed
  ACTIVITY_ADDED: 'activity:added',

  // Notification Center
  NOTIFICATION_ADDED: 'notification:added',
  NOTIFICATION_COUNT: 'notification:count',
  NOTIFICATION_CLEARED: 'notification:cleared',
  NOTIFICATION_PANEL_TOGGLE: 'notification:panel:toggle',

  // Focus Mode
  FOCUS_MODE_ENTER: 'focus:enter',
  FOCUS_MODE_EXIT: 'focus:exit',

  // Chat History Search
  CHAT_SEARCH_OPEN: 'chat:search:open',
  CHAT_SEARCH_CLOSE: 'chat:search:close',
  CHAT_SEARCH_JUMP: 'chat:search:jump',

  // Tag filter (emitted by KanbanCard tag click)
  KANBAN_TAG_FILTER: 'kanban:tag:filter',

  // Tool execution (from backend tool:executed WS event)
  TOOL_EXECUTED: 'tool:executed',

  // Deep Worker Tasks (event bus)
  TASK_STARTED: 'task:started',
  TASK_PROGRESS: 'task:progress',
  TASK_COMPLETED: 'task:completed',
  TASK_CANCELLED: 'task:cancelled',
  TASK_TIMEOUT: 'task:timeout',

  // Message Reactions
  MESSAGE_REACTION: 'chat:message:reaction',

  // Direct Actions (fast-path CRUD, no worker)
  ACTION_STARTED: 'action:started',
  ACTION_COMPLETED: 'action:completed',
  ACTION_CONFIRM_REQUIRED: 'action:confirm_required',

  // Board Execution
  BOARD_EXECUTE_START: 'kanban:execute:start',
  BOARD_EXECUTE_CARD_START: 'kanban:execute:card:start',
  BOARD_EXECUTE_CARD_DONE: 'kanban:execute:card:done',
  BOARD_EXECUTE_COMPLETE: 'kanban:execute:complete',
  BOARD_EXECUTE_CANCELLED: 'kanban:execute:cancelled',
  BOARD_EXECUTE_ERROR: 'kanban:execute:error',
} as const;
