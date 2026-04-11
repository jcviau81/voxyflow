import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useChatService } from '../../contexts/useChatService';
import { useWS } from '../../providers/WebSocketProvider';
import { useSessionStore } from '../../stores/useSessionStore';
import { useMessageStore } from '../../stores/useMessageStore';
import { useToastStore } from '../../stores/useToastStore';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { SessionTabBar } from './SessionTabBar';
import { ChatSearch } from './ChatSearch';
import { ModePill } from './ModePill';
import type { ChatLevel } from './SmartSuggestions';
import { cn } from '../../lib/utils';
import { Search, Eraser, RotateCcw } from 'lucide-react';
import type { ServerSession } from '../../hooks/api/useSessions';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ChatWindowProps {
  /** Tab identifier (project ID, 'main', etc.) */
  tabId: string;
  /** Chat context level */
  chatLevel?: ChatLevel;
  /** Project ID for project/card-level chat */
  projectId?: string;
  /** Card ID for card-level embedded chat */
  cardId?: string;
  /** Compact embedded mode (inside CardDetailModal) */
  embedded?: boolean;
  /** Additional CSS class */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChatWindow({
  tabId,
  chatLevel = 'general',
  projectId,
  cardId,
  embedded = false,
  className,
}: ChatWindowProps) {
  const { connectionState, connected } = useWS();
  const { send } = useWS();
  const { loadHistory, setActiveSessionId, sendSystemInit } = useChatService();
  const resetLastSession = useSessionStore((s) => s.resetLastSession);
  const replaceSessionMessages = useMessageStore((s) => s.replaceSessionMessages);
  const showToast = useToastStore((s) => s.showToast);

  const [searchOpen, setSearchOpen] = useState(false);
  const activeSession = useSessionStore((s) => s.activeSession);
  const allSessions = useSessionStore((s) => s.sessions);
  const sessionId = useMemo(
    () => useSessionStore.getState().getActiveChatId(tabId),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [activeSession, allSessions, tabId],
  );

  // Keep ChatProvider's activeSessionIdRef in sync — used by flushVoiceAutoSend
  useEffect(() => {
    setActiveSessionId(sessionId);
  }, [sessionId, setActiveSessionId]);

  // ---------------------------------------------------------------------------
  // Cross-device session sync — fetch server sessions on WS connect
  // ---------------------------------------------------------------------------

  const prevConnState = useRef(connectionState);
  const injectServerSession = useSessionStore((s) => s.injectServerSession);
  const setActiveSession = useSessionStore((s) => s.setActiveSession);

  useEffect(() => {
    const justConnected =
      prevConnState.current !== 'connected' && connectionState === 'connected';
    prevConnState.current = connectionState;
    if (!justConnected) return;

    // Fetch active sessions from server and merge into local store
    // For Main (no projectId), filter to system-main sessions only
    const prefix = projectId ? `project:${projectId}` : `${chatLevel}:${tabId}`;
    fetch(`/api/sessions?active=true&max_age_hours=720`)
      .then((r) => (r.ok ? r.json() : []))
      .then((serverSessions: ServerSession[]) => {
        // Filter to sessions matching this tab's project
        const relevant = serverSessions.filter((s) => s.chatId.startsWith(prefix));
        if (relevant.length === 0) return;

        const localSessions = useSessionStore.getState().sessions[tabId] || [];
        const localChatIds = new Set(localSessions.map((s) => s.chatId));

        // Find the most recent server session (first in list, sorted by updatedAt desc)
        const mostRecent = relevant[0];

        // Inject any server sessions not already in local store (without changing active session)
        for (const ss of relevant) {
          if (!localChatIds.has(ss.chatId)) {
            injectServerSession(tabId, {
              chatId: ss.chatId,
              title: ss.title || ss.chatId,
              messageCount: ss.messageCount,
            });
          }
        }

        // If local store had no sessions or only an empty session, switch to the most recent server session
        const hasLocalMessages = localSessions.some((s) => {
          const msgs = useMessageStore.getState().getMessages(undefined, s.chatId);
          return msgs.length > 0;
        });

        if (!hasLocalMessages && mostRecent.messageCount > 0) {
          // Resume the most recent server session
          const updated = useSessionStore.getState().sessions[tabId] || [];
          const match = updated.find((s) => s.chatId === mostRecent.chatId);
          if (match) {
            setActiveSession(tabId, match.id);
            loadHistory(match.chatId, projectId, cardId, match.chatId, true).catch(() => {});
          }
        }
      })
      .catch((e) => console.warn('[ChatWindow] Session sync failed:', e));
  }, [connectionState, tabId, projectId, cardId, chatLevel, injectServerSession, setActiveSession, loadHistory]);

  // ---------------------------------------------------------------------------
  // Load history when session changes
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!connected || !sessionId) return;
    loadHistory(sessionId, projectId, cardId, sessionId, true).catch(() => {});
  }, [sessionId, connected, projectId, cardId, loadHistory]);

  // ---------------------------------------------------------------------------
  // Session management callbacks
  // ---------------------------------------------------------------------------

  const handleSessionSwitch = useCallback(
    (_newSessionId: string) => {
      const chatId = useSessionStore.getState().getActiveChatId(tabId);
      if (chatId) {
        loadHistory(chatId, projectId, cardId, chatId, true).catch(() => {});
      }
    },
    [tabId, projectId, cardId, loadHistory],
  );

  const handleNewSession = useCallback(() => {
    // Reset the current session on the backend
    if (sessionId) {
      send('session:reset', { sessionId, chatId: sessionId, tabId });
    }

    // Wipe all sessions for this tab and start fresh as Session 1
    const session = resetLastSession(tabId, chatLevel);
    replaceSessionMessages([], session.chatId, projectId, cardId);
    showToast('New session started', 'info', 2000);

    // Send a silent init so Voxy greets the user in the new session
    setTimeout(() => {
      sendSystemInit(
        '[New session started. Run your startup routine: check memory for recent context, check worker status, scan project state. Then greet the user naturally with a brief status if anything notable was found. Keep it concise — 3-5 lines max.]',
        projectId,
        cardId,
        session.chatId,
      );
    }, 300);
  }, [tabId, chatLevel, sessionId, resetLastSession, replaceSessionMessages, projectId, cardId, showToast, sendSystemInit, send]);

  const handleClearChat = useCallback(() => {
    replaceSessionMessages([], sessionId, projectId, cardId);
  }, [sessionId, projectId, cardId, replaceSessionMessages]);

  // ---------------------------------------------------------------------------
  // Search jump handler
  // ---------------------------------------------------------------------------

  const handleSearchJump = useCallback(
    (chatId: string, _messageId: string) => {
      // Load the conversation containing that message
      loadHistory(chatId, projectId, cardId, chatId, true).catch(() => {});
      setSearchOpen(false);
    },
    [projectId, cardId, loadHistory],
  );

  // ---------------------------------------------------------------------------
  // Connection status indicator
  // ---------------------------------------------------------------------------

  const connectionLabel = (() => {
    switch (connectionState) {
      case 'connected': return 'Connected';
      case 'connecting': return 'Connecting\u2026';
      case 'reconnecting': return 'Reconnecting\u2026';
      case 'disconnected': return 'Disconnected';
    }
  })();

  const connectionDotColor = (() => {
    switch (connectionState) {
      case 'connected': return 'bg-green-500';
      case 'connecting':
      case 'reconnecting': return 'bg-yellow-500 animate-pulse';
      case 'disconnected': return 'bg-red-500';
    }
  })();

  // ---------------------------------------------------------------------------
  // Welcome / empty state
  // ---------------------------------------------------------------------------

  const welcomeSlot = (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8 text-center">
      <div className="text-4xl">{'🛡\uFE0F'}</div>
      <h2 className="text-lg font-semibold text-foreground">
        {chatLevel === 'card'
          ? 'Card Chat'
          : chatLevel === 'project'
            ? 'Project Chat'
            : 'Welcome to Voxy'}
      </h2>
      <p className="text-sm text-muted-foreground max-w-sm">
        {chatLevel === 'card'
          ? 'Ask questions about this card, request implementation help, or discuss next steps.'
          : chatLevel === 'project'
            ? 'Ask about your project, create cards, or get a status overview.'
            : 'Your AI-powered project assistant. Type a message to get started.'}
      </p>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div
      className={cn(
        'chat-window flex flex-col h-full',
        embedded && 'chat-window--embedded',
        className,
      )}
    >
      {/* Session tab bar (not in embedded mode) */}
      {!embedded && (
        <SessionTabBar
          tabId={tabId}
          scope={chatLevel}
          onSessionSwitch={handleSessionSwitch}
        />
      )}

      {/* Message list */}
      <MessageList
        sessionId={sessionId}
        projectId={projectId}
        cardId={cardId}
        emptySlot={welcomeSlot}
        loading={connectionState === 'connecting'}
      />

      {/* Bottom bar (not in embedded mode) */}
      {!embedded && (
        <div className="chat-bottom-bar flex items-center gap-3 px-3 py-1.5 border-t border-border bg-muted/20 text-xs">
          {/* Connection status */}
          <div className="chat-conn-status flex items-center gap-1.5">
            <span className={cn('chat-conn-dot w-2 h-2 rounded-full', connectionDotColor)} />
            <span className="chat-conn-label text-muted-foreground">{connectionLabel}</span>
          </div>

          {/* Mode pill */}
          <ModePill />

          <div className="flex-1" />

          {/* Search toggle button */}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted/50"
            title="Search chat history (Ctrl+Shift+F)"
            onClick={() => setSearchOpen((prev) => !prev)}
          >
            <Search size={14} />
          </button>

          {/* Clear button */}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted/50"
            title="Clear chat"
            onClick={handleClearChat}
          >
            <Eraser size={14} />
          </button>

          {/* New session button */}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded hover:bg-muted/50"
            title="New session (Ctrl+Shift+N)"
            onClick={handleNewSession}
          >
            <RotateCcw size={14} />
          </button>
        </div>
      )}

      {/* Chat input */}
      <ChatInput
        chatLevel={chatLevel}
        tabId={tabId}
        projectId={projectId}
        cardId={cardId}
        embedded={embedded}
        onNewSession={handleNewSession}
        onClearChat={handleClearChat}
      />

      {/* Search panel */}
      {!embedded && searchOpen && (
        <ChatSearch
          projectId={projectId}
          onJump={handleSearchJump}
        />
      )}
    </div>
  );
}
