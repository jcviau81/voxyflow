import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Message } from '../types';
import { generateId } from '../lib/utils';

export interface MessageState {
  messages: Message[];

  // Add a single message (auto-assigns id + timestamp)
  addMessage: (message: Omit<Message, 'id' | 'timestamp'>) => Message;

  // Update fields on an existing message by id
  updateMessage: (id: string, updates: Partial<Message>) => void;

  // Merge new messages into the store, deduplicating by role+timestamp+content prefix.
  // replace=true replaces the entire store (use with care).
  setMessages: (newMessages: Message[], replace?: boolean) => void;

  // Replace all messages that belong to a given session / card / project context,
  // preserving messages from other contexts.  Used when reloading history from the backend.
  replaceSessionMessages: (
    newMessages: Message[],
    sessionId?: string,
    projectId?: string,
    cardId?: string,
  ) => void;

  // Clear all messages globally
  clearMessages: () => void;

  // Queries (non-reactive helpers)
  getMessages: (projectId?: string, sessionId?: string) => Message[];
}

export const useMessageStore = create<MessageState>()(
  persist(
    (set, get) => ({
      messages: [],

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

      replaceSessionMessages(newMessages, sessionId, projectId, cardId) {
        set((s) => {
          const kept = s.messages.filter((m) => {
            if (sessionId && m.sessionId === sessionId) return false;
            if (!sessionId && cardId && m.cardId === cardId) return false;
            if (!sessionId && !cardId && projectId && m.projectId === projectId) return false;
            return true;
          });
          return { messages: [...kept, ...newMessages] };
        });
      },

      clearMessages() {
        set({ messages: [] });
      },

      getMessages(projectId, sessionId) {
        let msgs = get().messages;
        if (projectId) msgs = msgs.filter((m) => m.projectId === projectId);
        if (sessionId) msgs = msgs.filter((m) => m.sessionId === sessionId);
        return msgs;
      },
    }),
    {
      name: 'voxyflow_messages',
    },
  ),
);
