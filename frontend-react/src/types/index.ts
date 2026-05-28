// Voxyflow Type Definitions — ported from frontend/src/types/index.ts

export type MessageRole = 'user' | 'assistant' | 'system';
export type CardStatus = 'backlog' | 'todo' | 'in-progress' | 'done' | 'archived';
export type ViewMode =
  | 'chat'
  | 'kanban'
  | 'freeboard'
  | 'workspaces'
  | 'settings'
  | 'stats'
  | 'knowledge'
  | 'archives';
export type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
export type AgentPersona = 'coder' | 'architect' | 'designer' | 'devops' | 'analyst' | 'tester' | 'writer';
export type ModelName = 'fast' | 'deep';
export type ModelState = 'active' | 'thinking' | 'idle' | 'error';

export interface ModelStatusEvent {
  model: ModelName;
  state: ModelState;
}

/** A single delegate call embedded in an assistant message (from voxyflow.delegate tool_use). */
export interface MessageDelegate {
  action: string;
  description: string;
  complexity?: 'simple' | 'standard' | 'complex';
  card_id?: string;
  context?: string;
  /** Task ID assigned by the orchestrator (populated when task:started fires). */
  _task_id?: string;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  workspaceId?: string;
  sessionId?: string;
  cardId?: string;
  streaming?: boolean;
  audioBuffer?: ArrayBuffer;
  enrichment?: boolean;
  enrichmentAction?: 'enrich' | 'correct';
  model?: string;
  truncated?: boolean;
  queued?: boolean;
  /** Delegate calls attached to this message (voxyflow.delegate tool_use). */
  delegates?: MessageDelegate[];
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

export interface Workspace {
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
  isSystem?: boolean;
  deletable?: boolean;
  techStack?: TechDetectResult;
  githubRepo?: string;
  githubUrl?: string;
  githubBranch?: string;
  githubLanguage?: string;
  isFavorite?: boolean;
  inheritMainContext?: boolean;
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
  loggedAt: number;
}

export interface ChecklistItem {
  id: string;
  cardId: string;
  text: string;
  completed: boolean;
  position: number;
  createdAt: number;
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
  createdAt: number;
}

export type CardRelationType =
  | 'duplicates'
  | 'blocks'
  | 'is_blocked_by'
  | 'relates_to'
  | 'cloned_from'
  | 'duplicated_by'
  | 'cloned_to';

export interface CardRelation {
  id: string;
  sourceCardId: string;
  targetCardId: string;
  relationType: CardRelationType;
  createdAt: string;
  relatedCardId: string;
  relatedCardTitle: string;
  relatedCardStatus: string;
}

export interface Card {
  id: string;
  title: string;
  description: string;
  status: CardStatus;
  workspaceId: string | null;
  color?: 'yellow' | 'blue' | 'green' | 'pink' | 'purple' | 'orange' | null;
  assignedAgent?: AgentPersona;
  agentType?: string;
  dependencies: string[];
  tags: string[];
  priority: number;
  position?: number;
  createdAt: number;
  updatedAt: number;
  chatHistory: string[];
  totalMinutes?: number;
  checklistProgress?: ChecklistProgress;
  assignee?: string | null;
  watchers?: string;
  votes?: number;
  preferredModel?: string | null;  // null = Auto, otherwise a worker class id
  recurring?: boolean;
  recurrence?: 'daily' | 'weekly' | 'monthly' | null;
  recurrenceNext?: string | null;
  files?: string[];
  archivedAt?: string | null;
}

export interface Tab {
  id: string;
  label: string;
  emoji?: string;
  closable: boolean;
  hasNotification: boolean;
  isActive: boolean;
}

export interface SessionInfo {
  id: string;
  chatId: string;
  title: string;
  createdAt: number;
}

export type ActivityType =
  | 'card_created'
  | 'card_moved'
  | 'card_deleted'
  | 'document_uploaded'
  | 'chat_message';

export interface ActivityEntry {
  id: string;
  workspaceId: string;
  type: ActivityType;
  message: string;
  timestamp: number;
}

export type NotificationType =
  | 'card_moved'
  | 'card_created'
  | 'card_deleted'
  | 'card_enriched'
  | 'service_down'
  | 'document_indexed'
  | 'focus_completed'
  | 'system'
  | 'worker_completed'
  | 'system_job';

export interface NotificationEntry {
  id: string;
  type: NotificationType;
  message: string;
  timestamp: number;
  read: boolean;
  link?: string;
  taskId?: string;
  jobId?: string;
  success?: boolean;
  details?: string;
}

export interface WebSocketMessage {
  type: string;
  payload: Record<string, unknown>;
  id?: string;
  timestamp?: number;
}

export interface WorkspaceFormData {
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

export interface WorkspaceTemplate {
  id: string;
  name: string;
  emoji: string;
  description: string;
  color: string;
  cards: Array<{ title: string; status: string; priority: number; agent_type?: string }>;
}

export interface CardHistoryEntry {
  id: string;
  cardId: string;
  fieldChanged: string;
  oldValue: string | null;
  newValue: string | null;
  changedAt: string;
  changedBy: string;
}


