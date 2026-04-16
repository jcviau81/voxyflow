import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { MessageRole } from '../../types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SearchResult {
  chat_id: string;
  message_id: string;
  role: MessageRole;
  snippet: string;
  created_at?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function roleIcon(role: MessageRole): string {
  switch (role) {
    case 'user': return '\uD83E\uDDD1'; // 🧑
    case 'assistant': return '\uD83E\uDD16'; // 🤖
    default: return '\u2699\uFE0F'; // ⚙️
  }
}

// XSS-safe by construction: the snippet is HTML-escaped before the highlight
// regex injects <mark> tags, so user-supplied content can only appear as
// entities in the output. The query is also regex-escaped so it can't break
// out of the capture group.
function highlightMatch(text: string, query: string): string {
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const safe = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return safe.replace(regex, '<mark>$1</mark>');
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ChatSearchProps {
  projectId?: string;
  onJump?: (chatId: string, messageId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChatSearch({ projectId, onJump }: ChatSearchProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Global keyboard shortcut: Ctrl+Shift+F
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'F') {
        e.preventDefault();
        setIsOpen((prev) => !prev);
      } else if (e.key === 'Escape' && isOpen) {
        e.stopPropagation();
        setIsOpen(false);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen]);

  // Focus input when opened
  useEffect(() => {
    if (isOpen) {
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // Debounced search
  const runSearch = useCallback(
    async (q: string) => {
      if (!q.trim()) {
        setResults([]);
        return;
      }
      setSearching(true);
      try {
        const params = new URLSearchParams({ q });
        if (projectId) params.set('project_id', projectId);
        const res = await fetch(`/api/messages/search?${params}`);
        if (res.ok) {
          const data = (await res.json()) as SearchResult[];
          setResults(data);
        } else {
          setResults([]);
        }
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    },
    [projectId],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (!value.trim()) {
        setResults([]);
        return;
      }
      debounceRef.current = setTimeout(() => runSearch(value), 300);
    },
    [runSearch],
  );

  const jumpToResult = useCallback(
    (result: SearchResult) => {
      onJump?.(result.chat_id, result.message_id);
      setIsOpen(false);
    },
    [onJump],
  );

  if (!isOpen) return null;

  return (
    <div
      className="chat-search-panel fixed inset-y-0 right-0 w-80 max-w-full bg-background border-l border-border shadow-xl z-30 flex flex-col animate-in slide-in-from-right duration-200"
      role="dialog"
      aria-label="Chat History Search"
    >
      {/* Header */}
      <div className="chat-search-header flex items-center justify-between px-4 py-3 border-b border-border">
        <span className="chat-search-title text-sm font-medium">Search Chat History</span>
        <button
          type="button"
          className="chat-search-close-btn w-6 h-6 flex items-center justify-center rounded hover:bg-accent transition-colors text-muted-foreground"
          title="Close (Escape)"
          aria-label="Close search"
          onClick={() => setIsOpen(false)}
        >
          &times;
        </button>
      </div>

      {/* Search input */}
      <div className="px-4 py-2">
        <input
          ref={inputRef}
          type="text"
          className="chat-search-input w-full px-3 py-2 text-sm border border-border rounded-md bg-muted/50 placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          placeholder="Search messages\u2026"
          aria-label="Search query"
          autoComplete="off"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
        />
      </div>

      {/* Status */}
      {searching && (
        <div className="chat-search-status px-4 py-1 text-xs text-muted-foreground">
          Searching\u2026
        </div>
      )}

      {/* Results */}
      <div className="chat-search-results flex-1 overflow-y-auto px-2 pb-2" role="list">
        {!searching && query.trim() && results.length === 0 && (
          <div className="chat-search-empty px-2 py-4 text-center text-sm text-muted-foreground">
            No messages found.
          </div>
        )}
        {results.map((r) => (
          <div
            key={`${r.chat_id}-${r.message_id}`}
            className="chat-search-result flex items-start gap-2 px-2 py-2 rounded hover:bg-accent/50 cursor-pointer transition-colors text-sm"
            role="listitem"
            onClick={() => jumpToResult(r)}
          >
            <span className="chat-search-role-icon text-base" title={r.role}>
              {roleIcon(r.role)}
            </span>
            <div className="flex-1 min-w-0">
              <span
                className="chat-search-snippet block text-sm line-clamp-2"
                dangerouslySetInnerHTML={{ __html: highlightMatch(r.snippet, query) }}
              />
              {r.created_at && (
                <span className="chat-search-timestamp text-xs text-muted-foreground">
                  {formatTime(new Date(r.created_at).getTime())}
                </span>
              )}
            </div>
            <button
              type="button"
              className="chat-search-goto-btn text-xs text-primary hover:underline whitespace-nowrap mt-0.5"
              title={`Jump to conversation (${r.chat_id})`}
              onClick={(e) => {
                e.stopPropagation();
                jumpToResult(r);
              }}
            >
              Go to &rarr;
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Imperative handle for external toggle (e.g. bottom bar button)
// ---------------------------------------------------------------------------

export interface ChatSearchHandle {
  open: () => void;
  close: () => void;
  toggle: () => void;
}
