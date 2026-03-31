import { useCallback } from 'react';
import { useSessionStore } from '../../stores/useSessionStore';
import { useWS } from '../../providers/WebSocketProvider';
import { cn } from '../../lib/utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_SESSIONS = 5;
const MAX_TITLE_LENGTH = 25;

function truncateTitle(title: string): string {
  if (title.length <= MAX_TITLE_LENGTH) return title;
  return title.slice(0, MAX_TITLE_LENGTH - 1) + '\u2026';
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface SessionTabBarProps {
  tabId: string;
  scope?: 'general' | 'project' | 'card';
  onSessionSwitch?: (sessionId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionTabBar({
  tabId,
  scope = 'project',
  onSessionSwitch,
}: SessionTabBarProps) {
  const sessions = useSessionStore((s) => s.getSessions(tabId, scope));
  const activeSessionId = useSessionStore((s) => s.activeSession[tabId] ?? '');
  const setActiveSession = useSessionStore((s) => s.setActiveSession);
  const closeSession = useSessionStore((s) => s.closeSession);
  const createSession = useSessionStore((s) => s.createSession);
  const { send } = useWS();

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
        send('session:reset', { sessionId: session.chatId, tabId });
      }

      if (sessions.length > 1) {
        closeSession(tabId, sessionId);
        // If we just closed the active session, the store auto-switches
        if (sessionId === activeSessionId) {
          const remaining = sessions.filter((s) => s.id !== sessionId);
          if (remaining.length > 0) {
            onSessionSwitch?.(remaining[0].id);
          }
        }
      } else {
        // Last session — reset it (clear history, create fresh)
        closeSession(tabId, sessionId);
        const newSession = createSession(tabId, scope);
        onSessionSwitch?.(newSession.id);
      }
    },
    [sessions, tabId, activeSessionId, send, closeSession, createSession, scope, onSessionSwitch],
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
        {sessions.map((session) => {
          const isActive = session.id === activeSessionId;
          return (
            <div
              key={session.id}
              className={cn(
                'session-tab flex items-center gap-1 px-2.5 py-1 text-xs rounded cursor-pointer select-none transition-colors',
                isActive
                  ? 'bg-background text-foreground shadow-sm font-medium'
                  : 'text-muted-foreground hover:bg-accent/50',
              )}
              title={session.title}
              onClick={() => !isActive && handleSwitch(session.id)}
            >
              <span className="session-tab-label truncate max-w-[120px]">
                {truncateTitle(session.title)}
              </span>
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
            </div>
          );
        })}
      </div>

      <button
        type="button"
        className={cn(
          'session-tab-new w-6 h-6 flex items-center justify-center rounded text-sm transition-colors',
          atMax
            ? 'text-muted-foreground/40 cursor-not-allowed'
            : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
        )}
        title={atMax ? `Max ${MAX_SESSIONS} sessions` : 'New session'}
        disabled={atMax}
        onClick={handleNew}
        data-testid="session-tab-new"
      >
        +
      </button>
    </div>
  );
}
