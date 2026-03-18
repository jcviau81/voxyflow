// Voxyflow Type Definitions

export type MessageRole = 'user' | 'assistant' | 'system';
export type CardStatus = 'idea' | 'todo' | 'in-progress' | 'done';
export type ViewMode = 'chat' | 'kanban' | 'freeboard' | 'projects' | 'settings';
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
export type AgentPersona = 'codeuse' | 'architecte' | 'designer' | 'devops' | 'analyste' | 'testeur' | 'documenteur';
export type ModelName = 'fast' | 'deep' | 'analyzer';
export type ModelState = 'active' | 'thinking' | 'idle' | 'error';

export interface ModelStatusEvent {
  model: ModelName;
  state: ModelState;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  projectId?: string;
  sessionId?: string;
  cardId?: string;
  streaming?: boolean;
  audioBuffer?: ArrayBuffer;
  /** True if this is a Deep layer enrichment/correction follow-up */
  enrichment?: boolean;
  /** The type of enrichment: deeper thought or correction */
  enrichmentAction?: 'enrich' | 'correct';
  /** Which model produced this message */
  model?: string;
}

export interface TechInfo {
  name: string;
  icon: string;
  category: string;
  version?: string;
  source?: string;
}

export interface TechDetectResult {
  path: string;
  technologies: TechInfo[];
  file_counts: Record<string, number>;
  total_files: number;
  error?: string;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  emoji?: string;
  color?: string;
  localPath?: string;
  createdAt: number;
  updatedAt: number;
  cards: string[];
  archived: boolean;
  techStack?: TechDetectResult;
  githubRepo?: string;      // "owner/repo"
  githubUrl?: string;        // "https://github.com/owner/repo"
  githubBranch?: string;     // "main"
  githubLanguage?: string;   // "TypeScript"
}

export interface GitHubRepoInfo {
  valid: boolean;
  full_name: string;
  description: string;
  default_branch: string;
  language: string | null;
  stars: number;
  private: boolean;
  html_url: string;
  clone_url: string;
  updated_at: string;
}

export interface AgentInfo {
  type: string;
  name: string;
  emoji: string;
  description: string;
  strengths: string[];
  keywords: string[];
}

export interface Card {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  projectId: string;
  assignedAgent?: AgentPersona;
  agentType?: string;  // ember|researcher|coder|designer|architect|writer|qa
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
  activeTab: string;
  openTabs: Tab[];
  ideas: Idea[];
  // Session tabs per context (tabId → SessionInfo[])
  sessions: Record<string, SessionInfo[]>;
  // Active session per context (tabId → sessionId)
  activeSession: Record<string, string>;
  // Activity feed per project (projectId → ActivityEntry[])
  activities: Record<string, ActivityEntry[]>;
  // Unread opportunity badge count
  opportunityBadgeCount: number;
}

// Session tabs (per project/card context)
export interface SessionInfo {
  id: string;
  chatId: string;
  title: string;
  createdAt: number;
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

export interface Tab {
  id: string;           // 'main' or project UUID
  label: string;        // '💬 Main' or project name
  emoji?: string;       // project emoji
  closable: boolean;    // Main = false, projects = true
  hasNotification: boolean;
  isActive: boolean;
}

export interface ProjectFormData {
  title: string;
  description?: string;
  emoji?: string;
  color?: string;
  localPath?: string;
  status?: 'active' | 'archived';
  githubRepo?: string;
  githubUrl?: string;
  githubBranch?: string;
  githubLanguage?: string;
  templateId?: string;
}

export interface ProjectTemplate {
  id: string;
  name: string;
  emoji: string;
  description: string;
  color: string;
  cards: Array<{ title: string; status: string; priority: number; agent_type?: string }>;
}

export interface ProjectFormShowEvent {
  mode: 'create' | 'edit';
  project?: Project;
  prefillTitle?: string;
}

export interface CardSuggestion {
  id: string;
  title: string;
  description?: string;
  agentType?: string;
  agentName?: string;
  agentEmoji?: string;
  timestamp: number;
}

export interface Idea {
  id: string;
  content: string;
  createdAt: number;
  source: 'manual' | 'analyzer';
  color?: 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange';
  body?: string;
}

export interface ModelLayerConfig {
  provider_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
}

export interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;
  analyzer: ModelLayerConfig;
}

// Activity Feed
export type ActivityType =
  | 'card_created'
  | 'card_moved'
  | 'card_deleted'
  | 'document_uploaded'
  | 'chat_message';

export interface ActivityEntry {
  id: string;
  projectId: string;
  type: ActivityType;
  message: string;
  timestamp: number;
}
