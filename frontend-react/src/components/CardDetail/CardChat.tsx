/**
 * CardChatSection — embedded card-scoped chat panel.
 * Uses ChatProvider context to send/receive messages scoped to a card.
 *
 * Port of the vanilla embedded ChatWindow({ embedded: true, cardId }).
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useChatService } from '../../contexts/useChatService';
import type { Message } from '../../types';

// ── Component ────────────────────────────────────────────────────────────────

export function CardChatSection({ cardId }: { cardId: string }) {
  const chat = useChatService();
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef<string>(`card-${cardId}`);

  // Load history on mount / card change
  useEffect(() => {
    sessionIdRef.current = `card-${cardId}`;
    chat.setActiveSessionId(sessionIdRef.current);

    chat
      .loadHistory(`card-${cardId}`, undefined, cardId, sessionIdRef.current, true)
      .then((history) => setMessages(history))
      .catch(() => {});

    // Send system init so the backend knows the chat context
    chat.sendSystemInit('card-detail', undefined, cardId, sessionIdRef.current);

    return () => {
      chat.setActiveSessionId(undefined);
    };
  }, [cardId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Subscribe to streaming updates
  useEffect(() => {
    const unsubscribe = chat.registerCallbacks({
      onMessageReceived: (msg) => {
        if (msg.cardId === cardId || msg.sessionId === sessionIdRef.current) {
          setMessages((prev) => {
            if (prev.some((m) => m.id === msg.id)) return prev;
            return [...prev, msg];
          });
        }
      },
      onMessageStreaming: ({ messageId, content }) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === messageId ? { ...m, content, streaming: true } : m)),
        );
      },
      onMessageStreamEnd: ({ messageId, content }) => {
        setMessages((prev) =>
          prev.map((m) => (m.id === messageId ? { ...m, content, streaming: false } : m)),
        );
      },
    });
    return unsubscribe;
  }, [cardId, chat]);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const msg = chat.sendMessage(trimmed, undefined, cardId, sessionIdRef.current);
    setMessages((prev) => [...prev, msg]);
    setInput('');
  }, [input, cardId, chat]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="border-b border-border px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">Card Chat</span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {messages.length === 0 && (
          <p className="py-8 text-center text-xs text-muted-foreground/60">
            Send a message to chat about this card…
          </p>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              'rounded-lg px-3 py-2 text-sm',
              msg.role === 'user'
                ? 'ml-auto max-w-[80%] bg-accent/20 text-foreground'
                : msg.role === 'system'
                  ? 'text-center text-xs text-muted-foreground/60'
                  : 'mr-auto max-w-[80%] bg-muted text-foreground',
            )}
          >
            <div className="whitespace-pre-wrap break-words">{msg.content}</div>
            {msg.streaming && (
              <span className="inline-block h-3 w-1 animate-pulse bg-foreground/50" />
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-2">
        <div className="flex gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder="Message…"
            className="flex-1 resize-none rounded-md border border-border bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground/50 focus:border-accent"
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!input.trim()}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground transition-colors hover:bg-accent/80 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
