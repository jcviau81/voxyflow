import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
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
  /** Label shown next to the loading spinner */
  loadingLabel?: string;
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
  loadingLabel = 'Connecting to Voxy\u2026',
}: MessageListProps) {
  const allMessages = useMessageStore((s) => s.messages);
  const messages = useMemo(() => {
    if (sessionId) return allMessages.filter((m) => m.sessionId === sessionId);
    if (cardId) return allMessages.filter((m) => m.cardId === cardId);
    if (projectId) return allMessages.filter((m) => m.projectId === projectId);
    return allMessages;
  }, [allMessages, sessionId, cardId, projectId]);

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
  // TTS — progressive streaming: speak sentences as they arrive from LLM stream
  // ---------------------------------------------------------------------------

  // Track how many characters of each streaming message have already been queued for TTS
  const streamingTtsBufferRef = useRef<Map<string, number>>(new Map());

  /** Return true if TTS auto-play is on and enabled */
  const isTtsAutoPlay = useCallback((): boolean => {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const s = JSON.parse(stored);
        return (s?.voice?.tts_enabled ?? true) && (s?.voice?.tts_auto_play ?? false);
      }
    } catch { /* ignore */ }
    return false;
  }, []);

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
      onMessageStreaming({ messageId, content }) {
        if (autoScrollRef.current) scrollToBottom('instant');

        // Progressive TTS: detect complete sentences and speak them as they arrive.
        // IMPORTANT: clean the full accumulated content first, then track position in
        // cleaned space. This prevents text inside <delegate>/<tool_call> blocks from
        // leaking into TTS when spokenLen lands mid-block in the raw content.
        if (!isTtsAutoPlay()) return;

        const cleanedFull = cleanTextForSpeech(content);
        const spokenLen = streamingTtsBufferRef.current.get(messageId) ?? 0;
        const newCleanContent = cleanedFull.slice(spokenLen);

        // Find the last sentence-ending boundary in the new cleaned content
        const sentenceEndMatch = newCleanContent.match(/^([\s\S]*[.!?])(\s|$)/);
        if (!sentenceEndMatch) return;

        const toSpeak = sentenceEndMatch[1].trim();
        if (!toSpeak) return;

        ttsService.speak(toSpeak);
        // Advance the spoken pointer in cleaned content space
        streamingTtsBufferRef.current.set(messageId, spokenLen + sentenceEndMatch[0].length);
      },
      onMessageStreamEnd({ messageId, content }) {
        const spokenLen = streamingTtsBufferRef.current.get(messageId);
        streamingTtsBufferRef.current.delete(messageId);

        // Check message metadata (enrichment/worker result should not be spoken)
        const msg = useMessageStore.getState().messages.find((m) => m.id === messageId);
        const isSpecialMessage = msg && (msg.enrichment || msg.isWorkerResult);

        if (isSpecialMessage) {
          // Never speak enrichment or worker result messages
        } else if (spokenLen !== undefined) {
          // Progressive mode was active — speak any trailing text not yet queued.
          // spokenLen is in cleaned content space (same as onMessageStreaming above).
          const cleanedFull = cleanTextForSpeech(content);
          const remaining = cleanedFull.slice(spokenLen).trim();
          if (remaining && isTtsAutoPlay()) {
            ttsService.speak(remaining);
          }
        } else {
          // No progressive TTS happened (stream was too short or auto-play was off)
          // Fall back to speaking the full final message
          if (msg) speakAssistantMessage(msg);
        }
        if (autoScrollRef.current) scrollToBottom('smooth');
      },
    });
    return unsub;
  }, [registerCallbacks, speakAssistantMessage, scrollToBottom, isTtsAutoPlay]);

  // ---------------------------------------------------------------------------
  // Typing indicator — show when last message is from user and no streaming yet
  // ---------------------------------------------------------------------------

  const lastMessage = messages[messages.length - 1];
  const isStreaming = messages.some((m) => m.streaming);
  const showTypingIndicator =
    messages.length > 0 && lastMessage?.role === 'user' && !isStreaming;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div
        className="chat-messages flex flex-col items-center justify-center h-full gap-3"
        role="status"
        aria-live="polite"
      >
        <div className="chat-loading-spinner w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
        <div className="chat-loading-text text-muted-foreground text-sm">{loadingLabel}</div>
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

      {/* Typing indicator */}
      {showTypingIndicator && (
        <div className="flex items-center gap-2 px-4 py-3">
          <div className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-muted/50 text-muted-foreground">
            <span className="flex gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-current animate-bounce [animation-delay:300ms]" />
            </span>
          </div>
        </div>
      )}

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
