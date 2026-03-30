// Voxyflow Type Definitions

export type MessageRole = 'user' | 'assistant' | 'system';
export type CardStatus = 'card' | 'idea' | 'todo' | 'in-progress' | 'done' | 'archived';
export type ViewMode = 'chat' | 'kanban' | 'freeboard' | 'projects' | 'settings' | 'stats' | 'roadmap' | 'wiki' | 'sprint' | 'docs' | 'knowledge';
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
export type AgentPersona = 'coder' | 'architect' | 'designer' | 'devops' | 'analyst' | 'tester' | 'writer';
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
  /** True if this message is a background worker result (delegate execution) */
  isWorkerResult?: boolean;
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
  isSystem?: boolean;     // True for system-main project
  deletable?: boolean;    // False for system projects
  techStack?: TechDetectResult;
  githubRepo?: string;      // "owner/repo"
  githubUrl?: string;        // "https://github.com/owner/repo"
  githubBranch?: string;     // "main"
  githubLanguage?: string;   // "TypeScript"
  isFavorite?: boolean;       // User-pinned favorite
  inheritMainContext?: boolean; // Include Main Board RAG context (default true)
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

export interface TimeEntry {
  id: string;
  cardId: string;
  durationMinutes: number;
  note?: string;
  loggedAt: number; // unix ms
}

export interface CardComment {
  id: string;
  cardId: string;
  author: string;
  content: string;
  createdAt: number; // unix ms
}

export interface ChecklistItem {
  id: string;
  cardId: string;
  text: string;
  completed: boolean;
  position: number;
  createdAt: number; // unix ms
}

export interface ChecklistProgress {
  total: number;
  completed: number;
}

export interface CardAttachment {
  id: string;
  cardId: string;
  filename: string;
  fileSize: number;
  mimeType: string;
  createdAt: number; // unix ms
}

export type CardRelationType = 'duplicates' | 'blocks' | 'is_blocked_by' | 'relates_to' | 'cloned_from' | 'duplicated_by' | 'cloned_to';

export interface CardRelation {
  id: string;
  sourceCardId: string;
  targetCardId: string;
  relationType: CardRelationType;
  createdAt: string; // ISO string
  relatedCardId: string;
  relatedCardTitle: string;
  relatedCardStatus: string;
}

export interface Card {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  projectId: string | null;  // 'system-main' = Main Board (system project)
  color?: 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange' | null;
  assignedAgent?: AgentPersona;
  agentType?: string;  // general|researcher|coder|designer|architect|writer|qa
  dependencies: string[];
  tags: string[];
  priority: number;
  position?: number;  // ordering within status column (for manual sort); defaults to 0
  createdAt: number;
  updatedAt: number;
  chatHistory: string[];
  totalMinutes?: number; // total time logged in minutes
  checklistProgress?: ChecklistProgress; // computed from checklist items
  assignee?: string | null;  // display name of person assigned
  watchers?: string;         // comma-separated watcher names
  votes?: number;            // upvote count
  sprintId?: string | null;  // sprint assignment
  recurrence?: 'daily' | 'weekly' | 'monthly' | null;  // recurring schedule
  recurrenceNext?: string | null;  // ISO datetime of next occurrence
  files?: string[];  // relative file paths linked to this card
  archivedAt?: string | null;  // ISO datetime when archived, null = active
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
  ideas: Idea[];  // @deprecated — kept for migration only
  mainBoardCards: Card[];  // @deprecated — kept for migration. Use getCardsByProject(SYSTEM_PROJECT_ID)
  // Session tabs per context (tabId → SessionInfo[])
  sessions: Record<string, SessionInfo[]>;
  // Active session per context (tabId → sessionId)
  activeSession: Record<string, string>;
  // Activity feed per project (projectId → ActivityEntry[])
  activities: Record<string, ActivityEntry[]>;
  // Unread opportunity badge count
  opportunityBadgeCount: number;
  // Notification center
  notifications: NotificationEntry[];
  notificationUnreadCount: number;
  // @deprecated — General chat now uses project session system with SYSTEM_PROJECT_ID. Kept for migration.
  generalSessions: { id: string; label: string }[];
  activeGeneralSessionId: string;
  generalSessionCounter: number;
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
  inheritMainContext?: boolean;
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

/**
 * @deprecated Use Card with `projectId = null` and `status = 'card'` instead.
 * Kept temporarily for localStorage migration.
 */
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

// Notification Center
export type NotificationType =
  | 'card_moved'
  | 'card_created'
  | 'card_deleted'
  | 'card_enriched'
  | 'opportunity'
  | 'service_down'
  | 'document_indexed'
  | 'focus_completed'
  | 'system';

export interface NotificationEntry {
  id: string;
  type: NotificationType;
  message: string;
  timestamp: number;
  read: boolean;
  link?: string;
}

// Card History / Audit Log
export interface CardHistoryEntry {
  id: string;
  cardId: string;
  fieldChanged: string;
  oldValue: string | null;
  newValue: string | null;
  changedAt: string;
  changedBy: string;
}

// Sprint Planning
export type SprintStatus = 'planning' | 'active' | 'completed';

export interface Sprint {
  id: string;
  projectId: string;
  name: string;
  goal?: string | null;
  startDate: string;   // ISO date string
  endDate: string;     // ISO date string
  status: SprintStatus;
  createdAt: string;
  cardCount: number;
}
