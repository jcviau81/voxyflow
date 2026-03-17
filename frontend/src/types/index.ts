// Voxyflow Type Definitions

export type MessageRole = 'user' | 'assistant' | 'system';
export type CardStatus = 'idea' | 'todo' | 'in-progress' | 'done';
export type ViewMode = 'chat' | 'kanban' | 'projects' | 'settings';
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
export type AgentPersona = 'codeuse' | 'architecte' | 'designer' | 'devops' | 'analyste' | 'testeur' | 'documenteur';

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  projectId?: string;
  cardId?: string;
  streaming?: boolean;
  audioBuffer?: ArrayBuffer;
  /** True if this is an Opus enrichment/correction follow-up */
  enrichment?: boolean;
  /** The type of enrichment: deeper thought or correction */
  enrichmentAction?: 'enrich' | 'correct';
  /** Which model produced this message */
  model?: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  createdAt: number;
  updatedAt: number;
  cards: string[];
  archived: boolean;
}

export interface Card {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  projectId: string;
  assignedAgent?: AgentPersona;
  dependencies: string[];
  tags: string[];
  priority: number;
  createdAt: number;
  updatedAt: number;
  chatHistory: string[];
}

export interface AppStateData {
  currentView: ViewMode;
  currentProjectId: string | null;
  selectedCardId: string | null;
  messages: Message[];
  projects: Project[];
  cards: Card[];
  sidebarOpen: boolean;
  connectionState: ConnectionState;
  voiceActive: boolean;
  volume: number;
  theme: 'dark' | 'light';
}

export interface WebSocketMessage {
  type: string;
  payload: Record<string, unknown>;
  id?: string;
  timestamp?: number;
}

export interface SttResult {
  transcript: string;
  confidence: number;
  isFinal: boolean;
}

export interface StorageQuery {
  field?: string;
  value?: unknown;
  limit?: number;
  offset?: number;
  orderBy?: string;
  order?: 'asc' | 'desc';
}

export interface ToastOptions {
  message: string;
  type: 'info' | 'success' | 'warning' | 'error';
  duration?: number;
  action?: {
    label: string;
    callback: () => void;
  };
}

export interface ComponentBase {
  render(): void;
  update(data: unknown): void;
  destroy(): void;
}

export type EventHandler = (...args: unknown[]) => void;

export interface ApiClientConfig {
  url: string;
  reconnectAttempts: number;
  reconnectDelay: number;
  heartbeatInterval: number;
}

export interface AudioQueueItem {
  buffer: ArrayBuffer;
  id: string;
}
