// API & WebSocket
// In dev, connect via webpack proxy at /ws (proxied to ws://localhost:8000/ws)
// In prod, use env var or default to the same origin's /ws
export const WS_URL = process.env.VOXYFLOW_WS_URL || 
  (typeof window !== 'undefined' 
    ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws`
    : 'ws://localhost:8000/ws');
export const API_URL = process.env.VOXYFLOW_API_URL || 'http://localhost:8000';

// Reconnection
export const RECONNECT_MAX_ATTEMPTS = 10;
export const RECONNECT_BASE_DELAY = 1000; // ms
export const RECONNECT_MAX_DELAY = 30000; // ms
export const HEARTBEAT_INTERVAL = 30000; // 30s

// Storage
export const DB_NAME = 'voxyflow';
export const DB_VERSION = 1;
export const STORAGE_TABLES = ['messages', 'projects', 'cards', 'settings'] as const;
export const AUTO_BACKUP_INTERVAL = 300000; // 5 min

// UI
export const MOBILE_BREAKPOINT = 768;
export const TABLET_BREAKPOINT = 1024;
export const TOAST_DURATION = 4000; // ms
export const STREAMING_CHAR_DELAY = 15; // ms per character for streaming effect
export const MAX_MESSAGE_LENGTH = 10000;

// Kanban
export const CARD_STATUSES = ['idea', 'todo', 'in-progress', 'done'] as const;
export const CARD_STATUS_LABELS: Record<string, string> = {
  'idea': '💡 Idea',
  'todo': '📋 Todo',
  'in-progress': '🔨 In Progress',
  'done': '✅ Done',
};

// Agent Personas
export const AGENT_PERSONAS: Record<string, { name: string; emoji: string; description: string }> = {
  codeuse: { name: 'Codeuse', emoji: '👩‍💻', description: 'Code implementation & debugging' },
  architecte: { name: 'Architecte', emoji: '🏗️', description: 'System design & architecture' },
  designer: { name: 'Designer', emoji: '🎨', description: 'UI/UX design & styling' },
  devops: { name: 'DevOps', emoji: '⚙️', description: 'Infrastructure & deployment' },
  analyste: { name: 'Analyste', emoji: '📊', description: 'Requirements & analysis' },
  testeur: { name: 'Testeur', emoji: '🧪', description: 'Testing & quality assurance' },
  documenteur: { name: 'Documenteur', emoji: '📝', description: 'Documentation & specs' },
};

// Keyboard shortcuts
export const SHORTCUTS = {
  VOICE_TOGGLE: 'Alt+V',
  SEND_MESSAGE: 'Enter',
  NEW_LINE: 'Shift+Enter',
  TOGGLE_SIDEBAR: 'Ctrl+B',
  SWITCH_CHAT: 'Ctrl+1',
  SWITCH_KANBAN: 'Ctrl+2',
  SWITCH_PROJECTS: 'Ctrl+3',
} as const;

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

  // Voice
  VOICE_START: 'voice:start',
  VOICE_STOP: 'voice:stop',
  VOICE_TRANSCRIPT: 'voice:transcript',
  VOICE_ERROR: 'voice:error',

  // Navigation
  VIEW_CHANGE: 'nav:view:change',
  SIDEBAR_TOGGLE: 'nav:sidebar:toggle',

  // Projects & Cards
  PROJECT_CREATED: 'project:created',
  PROJECT_UPDATED: 'project:updated',
  PROJECT_DELETED: 'project:deleted',
  PROJECT_SELECTED: 'project:selected',
  CARD_CREATED: 'card:created',
  CARD_UPDATED: 'card:updated',
  CARD_DELETED: 'card:deleted',
  CARD_MOVED: 'card:moved',
  CARD_SELECTED: 'card:selected',

  // UI
  TOAST_SHOW: 'ui:toast:show',
  MODAL_OPEN: 'ui:modal:open',
  MODAL_CLOSE: 'ui:modal:close',

  // State
  STATE_CHANGED: 'state:changed',
} as const;
