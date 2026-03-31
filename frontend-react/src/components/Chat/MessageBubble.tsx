import { memo, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Message } from '../../types';
import { ttsService, cleanTextForSpeech } from '../../services/ttsService';
import { cn } from '../../lib/utils';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function getModelBadge(model: string): string {
  switch (model) {
    case 'fast': return '⚡ fast';
    case 'deep': return '🧠 deep';
    case 'sonnet': return '✨ sonnet';
    case 'analyzer': return '🔍 analyzer';
    case 'worker': return '⚙️ worker';
    default: return model;
  }
}

function replaceEmojiShortcodes(text: string): string {
  // Basic shortcode mapping (mirrors vanilla TS helpers)
  const map: Record<string, string> = {
    ':thumbsup:': '👍', ':thumbsdown:': '👎', ':tada:': '🎉',
    ':rocket:': '🚀', ':fire:': '🔥', ':check:': '✅',
    ':x:': '❌', ':warning:': '⚠️', ':info:': 'ℹ️',
    ':star:': '⭐', ':bulb:': '💡', ':wrench:': '🔧',
  };
  return text.replace(/:[a-z_]+:/g, (code) => map[code] || code);
}

// ---------------------------------------------------------------------------
// Code block component (used inside react-markdown)
// ---------------------------------------------------------------------------

interface CodeBlockProps {
  language: string;
  code: string;
}

function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(code).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="relative group">
      <div className="flex items-center justify-between bg-[#1e1e1e] px-3 py-1 rounded-t text-xs text-gray-400">
        <span>{language || 'code'}</span>
        <button
          onClick={copy}
          className="opacity-0 group-hover:opacity-100 transition-opacity hover:text-white"
          title="Copy code"
        >
          {copied ? '✓ Copied' : 'Copy'}
        </button>
      </div>
      <SyntaxHighlighter
        style={vscDarkPlus}
        language={language || 'text'}
        PreTag="div"
        customStyle={{ margin: 0, borderRadius: '0 0 4px 4px', fontSize: '0.85em' }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Markdown content renderer
// ---------------------------------------------------------------------------

interface MessageContentProps {
  content: string;
  streaming?: boolean;
}

function MessageContent({ content, streaming }: MessageContentProps) {
  const processed = replaceEmojiShortcodes(content);

  // Hide delegate/tool_call blocks from rendered output
  const cleaned = processed
    .replace(/<delegate[\s\S]*?<\/delegate>/gi, '')
    .replace(/<delegate[\s\S]*$/gi, '')
    .replace(/<tool_call[\s\S]*?<\/tool_call>/gi, '')
    .replace(/<tool_result[\s\S]*?<\/tool_result>/gi, '');

  const isEmpty = !cleaned.trim() && !streaming;

  return (
    <div className="message-content prose prose-sm dark:prose-invert max-w-none">
      {isEmpty ? (
        <span className="delegate-placeholder text-muted-foreground text-sm">⚙️ Délégation en cours…</span>
      ) : (
        <>
          <ReactMarkdown
            components={{
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || '');
                const isBlock = className?.includes('language-');
                const code = String(children).replace(/\n$/, '');
                if (isBlock) {
                  return <CodeBlock language={match?.[1] ?? ''} code={code} />;
                }
                return (
                  <code
                    className="bg-muted px-1 py-0.5 rounded text-sm font-mono"
                    {...props}
                  >
                    {children}
                  </code>
                );
              },
              // Open links in new tab
              a({ href, children }) {
                return (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {children}
                  </a>
                );
              },
            }}
          >
            {cleaned}
          </ReactMarkdown>
          {streaming && <span className="streaming-cursor inline-block animate-pulse ml-0.5">▊</span>}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TTS button
// ---------------------------------------------------------------------------

interface TtsButtonProps {
  text: string;
}

function TtsButton({ text }: TtsButtonProps) {
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    const unsub = ttsService.onEnd(() => setSpeaking(false));
    return unsub;
  }, []);

  const handleClick = useCallback(async () => {
    if (speaking && ttsService.isSpeaking) {
      ttsService.stop();
      setSpeaking(false);
      return;
    }
    setSpeaking(true);
    const plain = cleanTextForSpeech(text);
    await ttsService.speak(plain);
    setSpeaking(false);
  }, [speaking, text]);

  return (
    <button
      onClick={handleClick}
      className={cn(
        'tts-speak-btn text-sm opacity-60 hover:opacity-100 transition-opacity',
        speaking && 'tts-speaking opacity-100',
      )}
      title={speaking ? 'Stop' : 'Read aloud'}
      type="button"
    >
      {speaking ? '⏹' : '🔊'}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Reaction buttons
// ---------------------------------------------------------------------------

interface ReactionsProps {
  messageId: string;
}

function Reactions({ messageId }: ReactionsProps) {
  const storageKey = `reaction:${messageId}`;
  const [selected, setSelected] = useState<string | null>(
    () => localStorage.getItem(storageKey),
  );

  const toggle = useCallback((emoji: string) => {
    setSelected((prev) => {
      const next = prev === emoji ? null : emoji;
      if (next) localStorage.setItem(storageKey, next);
      else localStorage.removeItem(storageKey);
      return next;
    });
  }, [storageKey]);

  return (
    <div className="message-reactions flex gap-1 mt-1">
      {(['👍', '👎'] as const).map((emoji) => (
        <button
          key={emoji}
          onClick={() => toggle(emoji)}
          className={cn(
            'reaction-btn text-sm px-1.5 py-0.5 rounded transition-all',
            selected === emoji
              ? 'reaction-selected bg-primary/20 scale-110'
              : 'opacity-50 hover:opacity-80',
          )}
          type="button"
          title={emoji}
        >
          {emoji}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// MessageBubble
// ---------------------------------------------------------------------------

export interface MessageBubbleProps {
  message: Message;
}

export const MessageBubble = memo(function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isEnrichment = message.enrichment;

  const avatar = isUser ? '👤' : isEnrichment ? '💭' : '🛡️';
  const senderName = isUser ? 'JC' : isEnrichment ? 'Deep' : 'Voxy';

  // Plain text for TTS (extracted lazily via ref)
  const contentRef = useRef<HTMLDivElement>(null);
  const getPlainText = useCallback(() => {
    return contentRef.current?.textContent || message.content;
  }, [message.content]);

  return (
    <div
      className={cn(
        'message-bubble',
        `message-${message.role}`,
        isEnrichment && 'message-enrichment',
        isEnrichment && message.enrichmentAction === 'correct' && 'message-correction',
        message.isWorkerResult && 'message-worker-result',
      )}
      data-message-id={message.id}
    >
      {/* Avatar */}
      <div className="message-avatar">{avatar}</div>

      {/* Content wrapper */}
      <div className="message-content-wrapper">
        <div className="message-sender-name">{senderName}</div>

        {/* Content */}
        <div ref={contentRef}>
          {isUser ? (
            <div className="message-content whitespace-pre-wrap">
              {replaceEmojiShortcodes(message.content)}
            </div>
          ) : (
            <MessageContent content={message.content} streaming={message.streaming} />
          )}
        </div>

        {/* Meta row */}
        <div className="message-meta flex items-center gap-2 mt-1 text-xs text-muted-foreground">
          {!isUser && message.model && (
            <span className={cn('model-badge', `model-${message.model}`)}>
              {getModelBadge(message.model)}
            </span>
          )}
          <span className="message-time">{formatTime(message.timestamp)}</span>
          {!isUser && (
            <TtsButton text={getPlainText()} />
          )}
        </div>

        {/* Reactions — assistant only, not enrichments */}
        {!isUser && !isEnrichment && (
          <Reactions messageId={message.id} />
        )}
      </div>
    </div>
  );
});
