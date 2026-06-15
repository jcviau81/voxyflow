import type { Message } from '../../types';

// ---------------------------------------------------------------------------
// Chat event callback types — components subscribe to these via context
// ---------------------------------------------------------------------------

export type ChatEventCallback = (data: Record<string, unknown>) => void;

export interface ChatCallbacks {
  onMessageReceived?: (message: Message) => void;
  onMessageStreaming?: (data: { messageId: string; content: string; chunk: string }) => void;
  onMessageStreamEnd?: (data: { messageId: string; content: string }) => void;
  onMessageEnrichment?: (message: Message) => void;
  onModelStatus?: (data: { model: string; state: string }) => void;
  onTaskStarted?: ChatEventCallback;
  onTaskProgress?: ChatEventCallback;
  onTaskCompleted?: ChatEventCallback;
  onTaskCancelled?: ChatEventCallback;
  onTaskTimeout?: ChatEventCallback;
  onBoardExecuteCardStart?: ChatEventCallback;
  onBoardExecuteCardDone?: ChatEventCallback;
  onBoardExecuteComplete?: ChatEventCallback;
  onBoardExecuteCancelled?: ChatEventCallback;
  onBoardExecuteError?: ChatEventCallback;
  onVoiceFillInput?: (data: { text: string }) => void;
  onVoiceBufferUpdate?: (data: { text: string }) => void;
  onVoiceRecordingStop?: () => void;
  onActionConfirmRequired?: (data: {
    taskId: string;
    action: string;
    message: string;
    sessionId?: string;
  }) => Promise<boolean>;
}


// ---------------------------------------------------------------------------
// Context value
// ---------------------------------------------------------------------------

export interface ChatContextValue {
  /** Send a user message to the backend */
  sendMessage: (
    content: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
  ) => Message;
  /** Send a hidden system-init message (no user bubble) */
  sendSystemInit: (
    contextHint: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
  ) => void;
  /** Load chat history from backend API */
  loadHistory: (
    chatId: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
    replaceSession?: boolean,
  ) => Promise<Message[]>;
  /** Get messages from the local store */
  getHistory: (workspaceId?: string, sessionId?: string) => Message[];
  /** Clear all local messages */
  clearHistory: () => void;
  /** Simulate character-by-character streaming for a message. Pass an AbortSignal to stop early. */
  simulateStreaming: (messageId: string, fullContent: string, signal?: AbortSignal) => Promise<void>;
  /** Set the active session ID (called by ChatWindow) */
  setActiveSessionId: (sessionId: string | undefined) => void;
  /** Register event callbacks (returns unsubscribe fn) */
  registerCallbacks: (callbacks: ChatCallbacks) => () => void;
  /** Get layer state from localStorage */
  getLayerState: () => Record<string, boolean>;
  /** Handle incoming voice transcript (called by VoiceInput component) */
  handleVoiceTranscript: (transcript: string, isFinal: boolean) => void;
  /** Handle voice recording stop (called by VoiceInput component) */
  handleVoiceStop: () => void;
  /** Create a card from a suggestion (called by Opportunities panel) */
  createCardFromSuggestion: (data: { title: string; description?: string }) => void;
  /** Directly spawn a worker to execute a card (bypasses chat layer) */
  executeCard: (cardId: string, workspaceId?: string) => void;
}

// ---------------------------------------------------------------------------
// Internal streaming state (not reactive — managed via refs)
// ---------------------------------------------------------------------------

export interface StreamState {
  content: string;
  messageId: string;
}
