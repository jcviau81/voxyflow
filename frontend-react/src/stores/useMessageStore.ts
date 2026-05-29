import { create } from 'zustand';
import type { Message, MessageDelegate } from '../types';
import { generateId } from '../lib/utils';

// Evict legacy persisted chat messages. Keeping them in localStorage caused
// stale history to be shown on load (before the backend fetch resolved) and
// drifted away from the server's canonical history on cross-device use.
// Backend is now the single source of truth; ChatWindow reloads on mount.
if (typeof window !== 'undefined') {
  try { window.localStorage.removeItem('voxyflow_messages'); } catch { /* ignore */ }
}

export interface MessageState {
  messages: Message[];

  // Sessions where a worker just completed and Voxy's follow-up reply is expected.
  // Keyed by sessionId; flipped on by task:completed and off by the next chat:response.
  pendingAssistantBySession: Record<string, boolean>;

  // Add a single message (auto-assigns id + timestamp)
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => Message;

  // Update fields on an existing message by id
  updateMessage: (id: string, updates: Partial<Message>) => void;

  // Remove a single message by id (no-op if not present — keeps the
  // cross-tab WS broadcast handler idempotent against the local
  // optimistic remove).
  removeMessage: (id: string) => void;

  // Merge new messages into the store, deduplicating by role+timestamp+content prefix.
  // replace=true replaces the entire store (use with care).
  setMessages: (newMessages: Message[], replace?: boolean) => void;

  // Replace all messages that belong to a given session / card / workspace context,
  // preserving messages from other contexts.  Used when reloading history from the backend.
  replaceSessionMessages: (
    newMessages: Message[],
    sessionId?: string,
    workspaceId?: string,
    cardId?: string,
  ) => void;

  // Clear all messages globally
  clearMessages: () => void;

  // Mark/unmark a session as awaiting Voxy's reply (drives typing indicator).
  setPendingAssistant: (sessionId: string, pending: boolean) => void;

  // Queries (non-reactive helpers)
  getMessages: (workspaceId?: string, sessionId?: string) => Message[];

  /**
   * Attach a delegate payload to the most recent non-streaming assistant message
   * for the given sessionId. Called when task:started fires so the DelegateBadge
   * can appear in the bubble that triggered the delegate.
   */
  attachDelegateToLastMessage: (sessionId: string, delegate: MessageDelegate) => void;
}

export const useMessageStore = create<MessageState>()((set, get) => ({
  messages: [],
  pendingAssistantBySession: {},

  addMessage(message) {
    const fullMessage: Message = {
      ...message,
      id: generateId(),
      timestamp: Date.now(),
    };
    set((s) => ({ messages: [...s.messages, fullMessage] }));
    return fullMessage;
  },

  updateMessage(id, updates) {
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...updates } : m)),
    }));
  },

  removeMessage(id) {
    set((s) => {
      const next = s.messages.filter((m) => m.id !== id);
      if (next.length === s.messages.length) return s;
      return { messages: next };
    });
  },

  setMessages(newMessages, replace = false) {
    if (replace) {
      set({ messages: newMessages });
      return;
    }
    set((s) => {
      const safeSlice = (c: unknown) => (typeof c === 'string' ? c : String(c ?? '')).slice(0, 50);
      const existingKeys = new Set(
        s.messages.map((m) => `${m.role}:${m.timestamp}:${safeSlice(m.content)}`),
      );
      const toAdd = newMessages.filter(
        (m) => !existingKeys.has(`${m.role}:${m.timestamp}:${safeSlice(m.content)}`),
      );
      if (toAdd.length === 0) return s;
      return { messages: [...s.messages, ...toAdd] };
    });
  },

  replaceSessionMessages(newMessages, sessionId, workspaceId, cardId) {
    set((s) => {
      const kept = s.messages.filter((m) => {
        if (sessionId && m.sessionId === sessionId) return false;
        if (!sessionId && cardId && m.cardId === cardId) return false;
        if (!sessionId && !cardId && workspaceId && m.workspaceId === workspaceId) return false;
        return true;
      });
      return { messages: [...kept, ...newMessages] };
    });
  },

  clearMessages() {
    set({ messages: [], pendingAssistantBySession: {} });
  },

  setPendingAssistant(sessionId, pending) {
    if (!sessionId) return;
    set((s) => {
      const current = s.pendingAssistantBySession[sessionId] ?? false;
      if (current === pending) return s;
      const next = { ...s.pendingAssistantBySession };
      if (pending) {
        next[sessionId] = true;
      } else {
        delete next[sessionId];
      }
      return { pendingAssistantBySession: next };
    });
  },

  getMessages(workspaceId, sessionId) {
    let msgs = get().messages;
    if (workspaceId) msgs = msgs.filter((m) => m.workspaceId === workspaceId);
    if (sessionId) msgs = msgs.filter((m) => m.sessionId === sessionId);
    return msgs;
  },

  attachDelegateToLastMessage(sessionId, delegate) {
    set((s) => {
      // Find the most recent completed (non-streaming) assistant message for this session.
      const messages = [...s.messages];
      let targetIdx = -1;
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.role === 'assistant' && m.sessionId === sessionId && !m.streaming) {
          targetIdx = i;
          break;
        }
      }
      if (targetIdx === -1) return s; // no suitable message found — discard silently
      const target = messages[targetIdx];
      const existingDelegates = target.delegates ?? [];
      // Deduplicate: don't add the same task_id twice
      if (delegate._task_id && existingDelegates.some((d) => d._task_id === delegate._task_id)) {
        return s;
      }
      messages[targetIdx] = {
        ...target,
        delegates: [...existingDelegates, delegate],
      };
      return { messages };
    });
  },
}));
