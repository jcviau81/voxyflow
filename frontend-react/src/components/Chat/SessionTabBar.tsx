import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSessionStore } from '../../stores/useSessionStore';
import { useWS } from '../../providers/WebSocketProvider';
import { cn } from '../../lib/utils';
import type { ServerSession } from '../../hooks/api/useSessions';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_SESSIONS = 5;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface SessionTabBarProps {
  tabId: string;
  scope?: 'general' | 'project' | 'card';
  projectId?: string;
  cardId?: string;
  onSessionSwitch?: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionTabBar({
  tabId,
  scope = 'project',
  projectId,
  cardId,
  onSessionSwitch,
}: SessionTabBarProps) {
  const allSessions = useSessionStore((s) => s.sessions);
  const sessions = useMemo(
    () => useSessionStore.getState().getSessions(tabId, scope),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [allSessions, tabId, scope],
  );
  const activeSessionId = useSessionStore((s) => s.activeSession[tabId] ?? '');
  const setActiveSession = useSessionStore((s) => s.setActiveSession);
  const closeSession = useSessionStore((s) => s.closeSession);
  const createSession = useSessionStore((s) => s.createSession);
  const injectServerSession = useSessionStore((s) => s.injectServerSession);
  const resetLastSession = useSessionStore((s) => s.resetLastSession);
  const { send } = useWS();

  // Session history dropdown state
  const [historyOpen, setHistoryOpen] = useState(false);
  const [serverSessions, setServerSessions] = useState<ServerSession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const historyRef = useRef<HTMLDivElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    if (!historyOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setHistoryOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [historyOpen]);

  const fetchSessionHistory = useCallback(() => {
    const prefix = cardId ? `card:${cardId}` : `project:${projectId || tabId}`;
    setHistoryLoading(true);
    fetch(`/api/sessions?active=true&max_age_hours=720`)
      .then((r) => (r.ok ? r.json() : []))
      .then((all: ServerSession[]) => {
        const localChatIds = new Set(sessions.map((s) => s.chatId));
        // Show only sessions not already open as tabs
        const available = all
          .filter((s) => s.chatId.startsWith(prefix) && !localChatIds.has(s.chatId) && s.messageCount > 0);
        setServerSessions(available);
      })
      .catch(() => setServerSessions([]))
      .finally(() => setHistoryLoading(false));
  }, [tabId, projectId, cardId, sessions]);

  const handleToggleHistory = useCallback(() => {
    if (!historyOpen) fetchSessionHistory();
    setHistoryOpen((o) => !o);
  }, [historyOpen, fetchSessionHistory]);

  const handleRestoreSession = useCallback(
    (ss: ServerSession) => {
      injectServerSession(tabId, {
        chatId: ss.chatId,
        title: ss.title || ss.chatId,
        messageCount: ss.messageCount,
      });
      // Switch to the restored session
      const updated = useSessionStore.getState().sessions[tabId] || [];
      const match = updated.find((s) => s.chatId === ss.chatId);
      if (match) {
        setActiveSession(tabId, match.id);
        onSessionSwitch?.(match.id);
      }
      setHistoryOpen(false);
    },
    [tabId, injectServerSession, setActiveSession, onSessionSwitch],
  );

  const handleSwitch = useCallback(
    (sessionId: string) => {
      setActiveSession(tabId, sessionId);
      onSessionSwitch?.(sessionId);
    },
    [tabId, setActiveSession, onSessionSwitch],
  );

  const handleClose = useCallback(
    (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId);
      if (session) {
        send('session:reset', { sessionId: session.chatId, chatId: session.chatId, tabId });
      }

      if (sessions.length > 1) {
        closeSession(tabId, sessionId);
        if (sessionId === activeSessionId) {
          const remaining = sessions.filter((s) => s.id !== sessionId);
          if (remaining.length > 0) {
            onSessionSwitch?.(remaining[0].id);
          }
        }
      } else {
        // Last session — wipe all and start fresh as Session 1
        const newSession = resetLastSession(tabId, scope);
        onSessionSwitch?.(newSession.id);
      }
    },
    [sessions, tabId, activeSessionId, send, closeSession, resetLastSession, scope, onSessionSwitch],
  );

  const handleNew = useCallback(() => {
    if (sessions.length >= MAX_SESSIONS) return;
    const session = createSession(tabId, scope);
    onSessionSwitch?.(session.id);
  }, [sessions.length, tabId, scope, createSession, onSessionSwitch]);

  const atMax = sessions.length >= MAX_SESSIONS;

  return (
    <div className="session-tab-bar flex items-center gap-1 px-2 py-1 border-b border-border bg-muted/30" data-testid="session-tab-bar">
      <div className="session-tab-bar-tabs flex items-center gap-1 flex-1 overflow-x-auto">
        {sessions.map((session, index) => {
          const isActive = session.id === activeSessionId;
          const isFirst = index === 0;
          return (
            <div
              key={session.id}
              className={cn(
                'session-tab flex items-center gap-1 px-2.5 py-1 text-xs rounded cursor-pointer select-none transition-colors',
                isActive
                  ? 'bg-background text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:bg-accent/50',
              )}
              title={`Session ${index + 1}`}
              onClick={() => !isActive && handleSwitch(session.id)}
            >
              <span className="session-tab-label">
                Session {index + 1}
              </span>
              {!isFirst && (
                <button
                  type="button"
                  className="session-tab-close ml-0.5 w-4 h-4 flex items-center justify-center rounded-sm text-muted-foreground hover:text-foreground hover:bg-destructive/20 transition-colors text-[10px] leading-none"
                  title="Close session"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleClose(session.id);
                  }}
                >
                  &times;
                </button>
              )}
            </div>
          );
        })}
      </div>

      <button
        type="button"
        className={cn(
          'session-tab-new w-7 h-7 flex items-center justify-center rounded-md text-base font-medium transition-colors border',
          atMax
            ? 'text-muted-foreground/40 border-transparent cursor-not-allowed'
            : 'text-muted-foreground border-border hover:bg-accent hover:text-accent-foreground hover:border-accent',
        )}
        title={atMax ? `Max ${MAX_SESSIONS} sessions` : 'New session'}
        disabled={atMax}
        onClick={handleNew}
        data-testid="session-tab-new"
      >
        +
      </button>

      {/* Session history dropdown */}
      <div className="relative" ref={historyRef}>
        <button
          type="button"
          className="w-7 h-7 flex items-center justify-center rounded-md text-xs text-muted-foreground border border-border hover:bg-accent hover:text-accent-foreground hover:border-accent transition-colors"
          title="Previous sessions"
          onClick={handleToggleHistory}
          data-testid="session-history-btn"
        >
          {'\u29D6'}
        </button>

        {historyOpen && (
          <div className="absolute top-full right-0 mt-1 z-50 min-w-[220px] max-w-[320px] py-1 rounded-md border border-border bg-popover shadow-lg">
            <div className="px-2 py-1 text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
              Previous sessions
            </div>
            {historyLoading ? (
              <div className="px-2 py-2 text-xs text-muted-foreground">Loading...</div>
            ) : serverSessions.length === 0 ? (
              <div className="px-2 py-2 text-xs text-muted-foreground">No previous sessions</div>
            ) : (
              serverSessions.map((ss) => (
                <button
                  key={ss.chatId}
                  type="button"
                  className="flex flex-col gap-0.5 w-full px-2 py-1.5 text-left text-sm hover:bg-accent transition-colors"
                  onClick={() => handleRestoreSession(ss)}
                >
                  <span className="truncate font-medium">
                    {ss.title || 'Untitled session'}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    {ss.messageCount} messages &middot; {new Date(ss.updatedAt).toLocaleDateString()}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
