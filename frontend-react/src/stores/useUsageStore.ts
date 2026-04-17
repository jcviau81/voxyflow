import { create } from 'zustand';

export interface ChatUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheCreationTokens?: number;
  contextWindow: number;
  model?: string;
  updatedAt: number;
}

export interface UsageState {
  byChat: Record<string, ChatUsage>;
  setUsage: (chatId: string, usage: Omit<ChatUsage, 'updatedAt'>) => void;
  clearUsage: (chatId: string) => void;
  getUsage: (chatId: string | null | undefined) => ChatUsage | undefined;
}

export const useUsageStore = create<UsageState>((set, get) => ({
  byChat: {},

  setUsage: (chatId, usage) =>
    set((s) => ({
      byChat: {
        ...s.byChat,
        [chatId]: { ...usage, updatedAt: Date.now() },
      },
    })),

  clearUsage: (chatId) =>
    set((s) => {
      if (!(chatId in s.byChat)) return s;
      const next = { ...s.byChat };
      delete next[chatId];
      return { byChat: next };
    }),

  getUsage: (chatId) => {
    if (!chatId) return undefined;
    return get().byChat[chatId];
  },
}));
