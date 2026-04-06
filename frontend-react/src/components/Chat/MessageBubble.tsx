import { memo, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Volume2, Square } from 'lucide-react';
import type { Message } from '../../types';
import { ttsService, cleanTextForSpeech } from '../../services/ttsService';
import { cn } from '../../lib/utils';
import { eventBus } from '../../utils/eventBus';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Returns [label, badgeColorClass] for each known model. */
function getModelBadge(model: string): [string, string] {
  const m = model.toLowerCase();
  if (m.includes('opus'))   return ['opus', 'bg-purple-500/15 text-purple-400'];
  if (m.includes('sonnet')) return ['sonnet', 'bg-blue-500/15 text-blue-400'];
  if (m.includes('haiku'))  return ['haiku', 'bg-green-500/15 text-green-400'];
  switch (m) {
    case 'fast':     return ['sonnet', 'bg-blue-500/15 text-blue-400'];
    case 'deep':     return ['opus', 'bg-purple-500/15 text-purple-400'];
    case 'analyzer': return ['haiku', 'bg-green-500/15 text-green-400'];
    case 'worker':   return ['worker', 'bg-amber-500/15 text-amber-400'];
    default:         return [model, 'bg-muted'];
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
  // Guard: ensure content is always a string (stale localStorage or malformed WS payload)
  const safeContent = typeof content === 'string' ? content : JSON.stringify(content ?? '');
  const processed = replaceEmojiShortcodes(safeContent);

  // Hide delegate/tool_call blocks from rendered output
  const cleaned = processed
    .replace(/<delegate[\s\S]*?<\/delegate>/gi, '')
    .replace(/<delegate[\s\S]*$/gi, '')
    .replace(/<tool_call[\s\S]*?<\/tool_call>/gi, '')
    .replace(/<tool_result[\s\S]*?<\/tool_result>/gi, '');

  const isEmpty = !cleaned.trim() && !streaming;

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      {isEmpty ? (
        <span className="text-muted-foreground text-sm">⚙️ Délégation en cours…</span>
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
          {streaming && <span className="inline-block animate-pulse ml-0.5">▊</span>}
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

function readTtsEnabled(): boolean {
  try {
    const s = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
    return s?.voice?.tts_enabled ?? true;
  } catch { return true; }
}

function TtsButton({ text }: TtsButtonProps) {
  const [speaking, setSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(readTtsEnabled);

  useEffect(() => {
    const unsub = ttsService.onEnd(() => setSpeaking(false));
    return unsub;
  }, []);

  useEffect(() => {
    return eventBus.on('settings:changed', () => setTtsEnabled(readTtsEnabled()));
  }, []);

  if (!ttsEnabled) return null;

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
        'opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity',
        speaking && 'opacity-100 text-primary',
      )}
      title={speaking ? 'Stop' : 'Read aloud'}
      type="button"
    >
      {speaking
        ? <Square size={13} className="text-muted-foreground" />
        : <Volume2 size={13} className="text-muted-foreground" />}
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
    <div className="flex gap-1 mt-1 opacity-0 group-hover:opacity-40 hover:opacity-100 transition-opacity">
      {(['👍', '👎'] as const).map((emoji) => (
        <button
          key={emoji}
          onClick={() => toggle(emoji)}
          className={cn(
            'text-base px-1.5 py-0.5 rounded transition-all',
            selected === emoji
              ? 'bg-primary/20 scale-110'
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

  // Auto-play TTS when streaming finishes, if setting is enabled
  const prevStreamingRef = useRef(message.streaming);
  useEffect(() => {
    if (prevStreamingRef.current === true && !message.streaming && !isUser) {
      try {
        const settings = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
        if (settings?.voice?.tts_auto_play) {
          ttsService.speak(cleanTextForSpeech(message.content));
        }
      } catch { /* ignore */ }
    }
    prevStreamingRef.current = message.streaming;
  }, [message.streaming, message.content, isUser]);

  return (
    <div
      className={cn(
        'group flex gap-2.5 py-2 px-4 md:px-8 animate-in fade-in duration-200',
        isUser ? 'self-end flex-row-reverse md:ml-40' : 'self-start md:mr-40',
        isEnrichment && 'opacity-0 animate-in fade-in slide-in-from-bottom-2 duration-500 delay-300 fill-mode-forwards',
      )}
      data-message-id={message.id}
    >
      {/* Avatar */}
      <div
        className={cn(
          'w-[30px] h-[30px] rounded-full flex items-center justify-center shrink-0 text-sm',
          isEnrichment
            ? 'bg-transparent text-lg border-none'
            : 'bg-muted border border-border',
        )}
      >
        {avatar}
      </div>

      {/* Content wrapper */}
      <div className="flex flex-col gap-0.5">
        <div
          className={cn(
            'text-xs font-semibold pl-0.5',
            isUser ? 'text-blue-400' : 'text-muted-foreground',
          )}
        >
          {senderName}
        </div>

        {/* Content */}
        <div ref={contentRef}>
          {isUser ? (
            <div className="bg-primary border border-transparent text-primary-foreground rounded-xl rounded-br-sm px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
              {replaceEmojiShortcodes(typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? ''))}
            </div>
          ) : (
            <div
              className={cn(
                'bg-muted border border-border rounded-xl rounded-bl-sm px-3.5 py-2.5 text-sm leading-relaxed',
                isEnrichment && 'border-l-[3px] border-l-primary italic',
                isEnrichment && message.enrichmentAction === 'correct' && 'border-l-yellow-500',
                message.isWorkerResult && 'border-l-[3px] border-l-primary italic',
              )}
            >
              <MessageContent content={message.content} streaming={message.streaming} />
            </div>
          )}
        </div>

        {/* Meta row */}
        <div className="flex items-center gap-1.5 px-1">
          {!isUser && message.model && (() => {
            const [label, colorClass] = getModelBadge(message.model);
            return (
              <span className={cn('text-xs px-1.5 py-px rounded font-mono opacity-60 tracking-wide', colorClass)}>
                {label}
              </span>
            );
          })()}
          <span className={cn('text-xs text-muted-foreground px-1', isUser && 'text-right')}>
            {formatTime(message.timestamp)}
          </span>
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
