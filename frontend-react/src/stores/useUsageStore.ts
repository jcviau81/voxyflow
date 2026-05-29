import { create } from 'zustand';

/** Per-source token weight of the context WE inject into the dispatcher. */
export interface ContextBreakdown {
  system: number;    // base prompt (personality + dispatcher/delegate instructions)
  tools: number;     // MCP / tool schemas
  memory: number;    // memory + RAG context
  workspace: number; // workspace state + cards
  workers: number;   // ambient worker activity + live state
  sessions: number;  // conversation history
  total: number;
  exact: boolean;    // false = ~chars/4 fallback (tiktoken unavailable)
}

export interface ChatUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheCreationTokens?: number;
  contextWindow: number;
  model?: string;
  contextBreakdown?: ContextBreakdown | null;
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
