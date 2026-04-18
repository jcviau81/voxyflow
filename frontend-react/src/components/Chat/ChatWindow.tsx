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
import { ContextUsagePill } from './ContextUsagePill';
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
  const [historyLoading, setHistoryLoading] = useState(false);
  // Sequence number guards against stale resolutions clobbering a newer load.
  const loadSeq = useRef(0);

  const loadHistoryWithSpinner = useCallback(
    (chatId: string, pid?: string, cid?: string, sid?: string, replace = true) => {
      const seq = ++loadSeq.current;
      setHistoryLoading(true);
      loadHistory(chatId, pid, cid, sid, replace)
        .catch((e) => console.warn('[ChatWindow] loadHistory failed', e))
        .finally(() => {
          if (loadSeq.current === seq) setHistoryLoading(false);
        });
    },
    [loadHistory],
  );
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

  const prevConnState = useRef<string | null>(null);   // null = first mount
  const injectServerSession = useSessionStore((s) => s.injectServerSession);
  const setActiveSession = useSessionStore((s) => s.setActiveSession);

  useEffect(() => {
    const isFirstMount = prevConnState.current === null;
    const justConnected =
      prevConnState.current !== 'connected' && connectionState === 'connected';
    prevConnState.current = connectionState;

    // Run sync on WS transition to connected OR on first mount when already connected
    if (!justConnected && !(isFirstMount && connectionState === 'connected')) return;

    // Fetch active sessions from server — only used to resume the most recent one
    // when the local store is empty. Old sessions are NOT injected as tabs;
    // users can browse them via the session history dropdown in SessionTabBar.
    const prefix = cardId ? `card:${cardId}` : `project:${projectId || tabId}`;
    fetch(`/api/sessions?active=true&max_age_hours=720`)
      .then((r) => (r.ok ? r.json() : []))
      .then((serverSessions: ServerSession[]) => {
        // Filter to sessions matching this tab's project
        const relevant = serverSessions.filter((s) => s.chatId.startsWith(prefix));
        if (relevant.length === 0) return;

        const localSessions = useSessionStore.getState().sessions[tabId] || [];

        // Only resume the most recent server session if local store has no messages
        const hasLocalMessages = localSessions.some((s) => {
          const msgs = useMessageStore.getState().getMessages(undefined, s.chatId);
          return msgs.length > 0;
        });

        const mostRecent = relevant[0];
        if (!hasLocalMessages && mostRecent.messageCount > 0) {
          // Inject only the most recent session and switch to it
          const localChatIds = new Set(localSessions.map((s) => s.chatId));
          if (!localChatIds.has(mostRecent.chatId)) {
            injectServerSession(tabId, {
              chatId: mostRecent.chatId,
              title: mostRecent.title || mostRecent.chatId,
              messageCount: mostRecent.messageCount,
            });
          }
          const updated = useSessionStore.getState().sessions[tabId] || [];
          const match = updated.find((s) => s.chatId === mostRecent.chatId);
          if (match) {
            setActiveSession(tabId, match.id);
            loadHistoryWithSpinner(match.chatId, projectId, cardId, match.chatId, true);
          }
        }
      })
      .catch((e) => console.warn('[ChatWindow] Session sync failed:', e));
  }, [connectionState, tabId, projectId, cardId, injectServerSession, setActiveSession, loadHistoryWithSpinner]);

  // ---------------------------------------------------------------------------
  // Load history when session changes
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!connected || !sessionId) return;
    loadHistoryWithSpinner(sessionId, projectId, cardId, sessionId, true);
  }, [sessionId, connected, projectId, cardId, loadHistoryWithSpinner]);

  // ---------------------------------------------------------------------------
  // Session management callbacks
  // ---------------------------------------------------------------------------

  const handleSessionSwitch = useCallback(
    (_newSessionId: string) => {
      const chatId = useSessionStore.getState().getActiveChatId(tabId);
      if (chatId) {
        loadHistoryWithSpinner(chatId, projectId, cardId, chatId, true);
      }
    },
    [tabId, projectId, cardId, loadHistoryWithSpinner],
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
      loadHistoryWithSpinner(chatId, projectId, cardId, chatId, true);
      setSearchOpen(false);
    },
    [projectId, cardId, loadHistoryWithSpinner],
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
          projectId={projectId}
          cardId={cardId}
          onSessionSwitch={handleSessionSwitch}
        />
      )}

      {/* Message list */}
      <MessageList
        sessionId={sessionId}
        projectId={projectId}
        cardId={cardId}
        emptySlot={welcomeSlot}
        loading={connectionState === 'connecting' || historyLoading}
        loadingLabel={historyLoading ? 'Loading session\u2026' : 'Connecting to Voxy\u2026'}
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

          {/* Context usage indicator */}
          <ContextUsagePill sessionId={sessionId} />

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
