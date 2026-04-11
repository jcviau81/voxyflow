import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { SessionInfo } from '../types';
import { generateId } from '../lib/utils';

const MAX_SESSIONS_PER_TAB = 5;

/**
 * Map scope to the canonical chatId prefix used by the backend.
 * Backend always uses "project:" for both project and general chats,
 * and "card:" for card chats. We must match this exactly or the
 * backend will reject our chatId and store messages under a different key.
 */
function chatIdPrefix(scope: 'general' | 'project' | 'card'): string {
  return scope === 'card' ? 'card' : 'project';
}

export interface SessionState {
  // tabId → list of sessions (ordered)
  sessions: Record<string, SessionInfo[]>;
  // tabId → active sessionId
  activeSession: Record<string, string>;

  // Local session creation (synchronous fallback)
  createSession: (tabId: string, scope?: 'general' | 'project' | 'card') => SessionInfo;

  // Add a server-created session (POST /api/sessions returned a stable chatId)
  addServerSession: (tabId: string, chatId: string, title: string) => SessionInfo;

  // Replace all sessions for a tabId with server-sourced data (startup sync)
  setServerSessions: (tabId: string, sessions: SessionInfo[]) => void;

  // Close a session — won't close the last one (use resetLastSession instead)
  closeSession: (tabId: string, sessionId: string) => void;

  // Replace all sessions with a single fresh Session 1 (used when resetting the last session)
  resetLastSession: (tabId: string, scope?: 'general' | 'project' | 'card') => SessionInfo;

  // Set the active session for a tabId
  setActiveSession: (tabId: string, sessionId: string) => void;

  // Get sessions for a tabId, auto-creating an initial session if none exist
  getSessions: (tabId: string, scope?: 'general' | 'project' | 'card') => SessionInfo[];

  // Get the active SessionInfo for a tabId
  getActiveSession: (tabId: string) => SessionInfo;

  // Get the chatId for the active session of a tabId
  getActiveChatId: (tabId: string) => string;

  // Inject a server-sourced session without changing the active session
  injectServerSession: (
    tabId: string,
    opts: { chatId: string; title: string; messageCount: number }
  ) => void;

  // Update a session's title (e.g. after first message)
  updateSessionTitle: (tabId: string, sessionId: string, title: string) => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      sessions: {},
      activeSession: {},

      createSession: (tabId, scope = 'project') => {
        const existing = get().sessions[tabId] || [];
        if (existing.length >= MAX_SESSIONS_PER_TAB) {
          return existing[existing.length - 1];
        }
        const sessionNumber = existing.length + 1;
        // Use a unique suffix so new sessions never collide with old chat history
        const uniqueSuffix = Date.now().toString(36);
        const prefix = chatIdPrefix(scope);
        const chatId =
          sessionNumber === 1
            ? `${prefix}:${tabId}`
            : `${prefix}:${tabId}:s-${uniqueSuffix}`;
        const session: SessionInfo = {
          id: generateId(),
          chatId,
          title: `Session ${sessionNumber}`,
          createdAt: Date.now(),
        };
        set((state) => ({
          sessions: {
            ...state.sessions,
            [tabId]: [...existing, session],
          },
          activeSession: {
            ...state.activeSession,
            [tabId]: session.id,
          },
        }));
        return session;
      },

      addServerSession: (tabId, chatId, title) => {
        const existing = get().sessions[tabId] || [];
        const found = existing.find((s) => s.chatId === chatId);
        if (found) return found;

        const session: SessionInfo = {
          id: generateId(),
          chatId,
          title,
          createdAt: Date.now(),
        };
        set((state) => ({
          sessions: {
            ...state.sessions,
            [tabId]: [...existing, session],
          },
          activeSession: {
            ...state.activeSession,
            [tabId]: session.id,
          },
        }));
        return session;
      },

      setServerSessions: (tabId, sessions) => {
        set((state) => {
          const currentActive = state.activeSession[tabId];
          const activeStillExists = sessions.some((s) => s.id === currentActive);
          return {
            sessions: {
              ...state.sessions,
              [tabId]: sessions,
            },
            activeSession: {
              ...state.activeSession,
              [tabId]:
                activeStillExists
                  ? currentActive
                  : sessions.length > 0
                  ? sessions[0].id
                  : '',
            },
          };
        });
      },

      closeSession: (tabId, sessionId) => {
        const existing = get().sessions[tabId] || [];
        const updated = existing.filter((s) => s.id !== sessionId);

        if (updated.length === 0) {
          // Last session — don't leave an empty tab, handled by resetLastSession
          return;
        }

        set((state) => {
          const wasActive = state.activeSession[tabId] === sessionId;
          return {
            sessions: {
              ...state.sessions,
              [tabId]: updated,
            },
            activeSession: {
              ...state.activeSession,
              [tabId]: wasActive ? updated[0].id : state.activeSession[tabId],
            },
          };
        });
      },

      resetLastSession: (tabId, scope = 'project') => {
        // Replace ALL sessions for this tab with a single fresh Session 1
        const chatId = `${chatIdPrefix(scope)}:${tabId}`;
        const session: SessionInfo = {
          id: generateId(),
          chatId,
          title: 'Session 1',
          createdAt: Date.now(),
        };
        set((state) => ({
          sessions: {
            ...state.sessions,
            [tabId]: [session],
          },
          activeSession: {
            ...state.activeSession,
            [tabId]: session.id,
          },
        }));
        return session;
      },

      setActiveSession: (tabId, sessionId) => {
        set((state) => ({
          activeSession: {
            ...state.activeSession,
            [tabId]: sessionId,
          },
        }));
      },

      getSessions: (tabId, scope = 'project') => {
        const sessions = get().sessions[tabId];
        if (!sessions || sessions.length === 0) {
          get().createSession(tabId, scope);
          return get().sessions[tabId] || [];
        }
        return sessions;
      },

      getActiveSession: (tabId) => {
        const sessions = get().getSessions(tabId);
        if (sessions.length === 0) {
          return { id: '', chatId: '', title: 'Session 1', createdAt: Date.now() };
        }
        const activeId = get().activeSession[tabId];
        return sessions.find((s) => s.id === activeId) ?? sessions[0];
      },

      getActiveChatId: (tabId) => {
        return get().getActiveSession(tabId).chatId;
      },

      injectServerSession: (tabId, opts) => {
        const existing = get().sessions[tabId] || [];
        if (existing.some((s) => s.chatId === opts.chatId)) return;
        if (existing.length >= MAX_SESSIONS_PER_TAB) return;

        const session: SessionInfo = {
          id: generateId(),
          chatId: opts.chatId,
          title: opts.title,
          createdAt: Date.now(),
        };
        set((state) => ({
          sessions: {
            ...state.sessions,
            [tabId]: [...existing, session],
          },
          // Do NOT change activeSession — keep user's current session
        }));
      },

      updateSessionTitle: (tabId, sessionId, title) => {
        const sessions = get().sessions[tabId];
        if (!sessions) return;
        set((state) => ({
          sessions: {
            ...state.sessions,
            [tabId]: sessions.map((s) => (s.id === sessionId ? { ...s, title } : s)),
          },
        }));
      },
    }),
    {
      name: 'voxyflow_sessions',
      version: 1,
      partialize: (state) => ({
        sessions: state.sessions,
        activeSession: state.activeSession,
      }),
      migrate: (persisted, version) => {
        const state = persisted as { sessions: Record<string, SessionInfo[]>; activeSession: Record<string, string> };
        if (version === 0) {
          // v0 → v1: rewrite "general:" chatId prefixes to "project:" to match backend canonical format
          for (const tabId of Object.keys(state.sessions)) {
            state.sessions[tabId] = state.sessions[tabId].map((s) => ({
              ...s,
              chatId: s.chatId.replace(/^general:/, 'project:'),
            }));
          }
        }
        return state;
      },
    }
  )
);
