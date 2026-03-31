import { useCallback, useEffect, useState } from 'react';
import { useChatService } from '../../contexts/useChatService';
import { useWS } from '../../providers/WebSocketProvider';
import { useSessionStore } from '../../stores/useSessionStore';
import { useMessageStore } from '../../stores/useMessageStore';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';
import { SessionTabBar } from './SessionTabBar';
import { ChatSearch } from './ChatSearch';
import type { ChatLevel } from './SmartSuggestions';
import { cn } from '../../lib/utils';

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
  const { loadHistory } = useChatService();
  const getActiveChatId = useSessionStore((s) => s.getActiveChatId);
  const createSession = useSessionStore((s) => s.createSession);
  const replaceSessionMessages = useMessageStore((s) => s.replaceSessionMessages);

  const [searchOpen, setSearchOpen] = useState(false);
  const sessionId = useSessionStore((s) => s.getActiveChatId(tabId));

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
      const chatId = getActiveChatId(tabId);
      if (chatId) {
        loadHistory(chatId, projectId, cardId, chatId, true).catch(() => {});
      }
    },
    [tabId, projectId, cardId, getActiveChatId, loadHistory],
  );

  const handleNewSession = useCallback(() => {
    const session = createSession(tabId, chatLevel);
    // Clear messages for new session context
    replaceSessionMessages([], session.chatId, projectId, cardId);
  }, [tabId, chatLevel, createSession, replaceSessionMessages, projectId, cardId]);

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

          <div className="flex-1" />

          {/* Search toggle button */}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Search chat history (Ctrl+Shift+F)"
            onClick={() => setSearchOpen((prev) => !prev)}
          >
            Search
          </button>

          {/* Clear button */}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="Clear chat"
            onClick={handleClearChat}
          >
            Clear
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
