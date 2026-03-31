import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useMessageStore } from '../../stores/useMessageStore';
import { useChatService } from '../../contexts/useChatService';
import { ttsService, cleanTextForSpeech } from '../../services/ttsService';
import { MessageBubble } from './MessageBubble';
import { StreamingMessage } from './StreamingMessage';
import type { Message } from '../../types';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MessageListProps {
  /** Filter messages to this session (required for multi-session support) */
  sessionId?: string;
  /** Filter messages to this project */
  projectId?: string;
  /** Filter messages to this card (card-level chat) */
  cardId?: string;
  /** Rendered inside the welcome empty state slot when there are no messages */
  emptySlot?: React.ReactNode;
  /** Loading indicator shown while connecting */
  loading?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MessageList({
  sessionId,
  projectId,
  cardId,
  emptySlot,
  loading = false,
}: MessageListProps) {
  const messages = useMessageStore((s) => {
    let msgs = s.messages;
    if (sessionId) msgs = msgs.filter((m) => m.sessionId === sessionId);
    else if (cardId) msgs = msgs.filter((m) => m.cardId === cardId);
    else if (projectId) msgs = msgs.filter((m) => m.projectId === projectId);
    return msgs;
  });

  const { registerCallbacks } = useChatService();

  // Auto-scroll: true → stick to bottom; false → user scrolled up
  const autoScrollRef = useRef(true);
  const [autoScroll, setAutoScroll] = useState(true);

  // Outer scroll container
  const parentRef = useRef<HTMLDivElement>(null);

  // ---------------------------------------------------------------------------
  // Virtual list
  // ---------------------------------------------------------------------------

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80,
    overscan: 5,
  });

  const virtualItems = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  // ---------------------------------------------------------------------------
  // Scroll helpers
  // ---------------------------------------------------------------------------

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = parentRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // After virtualizer re-renders, scroll to bottom when auto-scroll is on
  useLayoutEffect(() => {
    if (autoScrollRef.current) {
      scrollToBottom('instant');
    }
  }, [messages.length, totalSize, scrollToBottom]);

  // Detect user scroll
  const handleScroll = useCallback(() => {
    const el = parentRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (atBottom !== autoScrollRef.current) {
      autoScrollRef.current = atBottom;
      setAutoScroll(atBottom);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // TTS — trigger on new messages
  // ---------------------------------------------------------------------------

  const speakAssistantMessage = useCallback((msg: Message) => {
    if (msg.role !== 'assistant') return;
    if (msg.enrichment || msg.isWorkerResult) return;
    const cleaned = cleanTextForSpeech(msg.content);
    if (cleaned) ttsService.speakIfAutoPlay(cleaned);
  }, []);

  // Subscribe to ChatProvider callbacks for TTS triggering
  useEffect(() => {
    const unsub = registerCallbacks({
      onMessageReceived(message) {
        // Non-streaming full message — speak immediately
        if (!message.streaming) {
          speakAssistantMessage(message);
        }
        if (autoScrollRef.current) scrollToBottom('smooth');
      },
      onMessageStreaming() {
        if (autoScrollRef.current) scrollToBottom('instant');
      },
      onMessageStreamEnd({ messageId }) {
        // Find the message in the store to speak its final content
        const msg = useMessageStore.getState().messages.find((m) => m.id === messageId);
        if (msg) speakAssistantMessage(msg);
        if (autoScrollRef.current) scrollToBottom('smooth');
      },
    });
    return unsub;
  }, [registerCallbacks, speakAssistantMessage, scrollToBottom]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="chat-messages flex flex-col items-center justify-center h-full gap-3">
        <div className="chat-loading-spinner w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        <div className="chat-loading-text text-muted-foreground text-sm">Connecting to Voxy...</div>
      </div>
    );
  }

  if (messages.length === 0 && emptySlot) {
    return (
      <div className="chat-messages flex flex-col h-full overflow-y-auto" ref={parentRef}>
        {emptySlot}
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      className="chat-messages flex-1 overflow-y-auto relative"
      onScroll={handleScroll}
    >
      {/* Virtual list container */}
      <div style={{ height: totalSize, position: 'relative' }}>
        {virtualItems.map((vItem) => {
          const message = messages[vItem.index];
          if (!message) return null;
          return (
            <div
              key={message.id}
              data-index={vItem.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${vItem.start}px)`,
              }}
            >
              {message.streaming ? (
                <StreamingMessage message={message} />
              ) : (
                <MessageBubble message={message} />
              )}
            </div>
          );
        })}
      </div>

      {/* Scroll-to-bottom button when user has scrolled up */}
      {!autoScroll && (
        <button
          onClick={() => {
            autoScrollRef.current = true;
            setAutoScroll(true);
            scrollToBottom('smooth');
          }}
          className="fixed bottom-24 right-6 z-10 bg-primary text-primary-foreground rounded-full p-2 shadow-lg text-sm hover:bg-primary/90 transition-colors"
          title="Scroll to bottom"
          type="button"
        >
          ↓
        </button>
      )}
    </div>
  );
}
