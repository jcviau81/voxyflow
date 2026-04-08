// Voxyflow Type Definitions — ported from frontend/src/types/index.ts

export type MessageRole = 'user' | 'assistant' | 'system';
export type CardStatus = 'card' | 'idea' | 'todo' | 'in-progress' | 'done' | 'archived';
export type ViewMode =
  | 'chat'
  | 'kanban'
  | 'freeboard'
  | 'projects'
  | 'settings'
  | 'stats'
  | 'knowledge';
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
  enrichment?: boolean;
  enrichmentAction?: 'enrich' | 'correct';
  model?: string;
  isWorkerResult?: boolean;
  truncated?: boolean;
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

export interface CardComment {
  id: string;
  cardId: string;
  author: string;
  content: string;
  createdAt: number;
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
  projectId: string | null;
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
  sprintId?: string | null;
  preferredModel?: 'haiku' | 'sonnet' | 'opus' | null;
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
  projectId: string;
  type: ActivityType;
  message: string;
  timestamp: number;
}

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

export interface WebSocketMessage {
  type: string;
  payload: Record<string, unknown>;
  id?: string;
  timestamp?: number;
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

export interface CardHistoryEntry {
  id: string;
  cardId: string;
  fieldChanged: string;
  oldValue: string | null;
  newValue: string | null;
  changedAt: string;
  changedBy: string;
}

export type SprintStatus = 'planning' | 'active' | 'completed';

export interface Sprint {
  id: string;
  projectId: string;
  name: string;
  goal?: string | null;
  startDate: string;
  endDate: string;
  status: SprintStatus;
  createdAt: string;
  cardCount: number;
}
