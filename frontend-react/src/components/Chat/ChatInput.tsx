import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useChatService } from '../../contexts/useChatService';
import { useSessionStore } from '../../stores/useSessionStore';
import { useWS } from '../../providers/WebSocketProvider';
import { useSlashMenu, type SlashCommand } from './SlashCommandMenu';
import { EmojiPicker } from './EmojiPicker';
import { SmartSuggestions, type ChatLevel } from './SmartSuggestions';
import { cn } from '../../lib/utils';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_TEXTAREA_HEIGHT = 150;
const CODE_PASTE_MIN_LENGTH = 20;
const DICTATION_AUTO_SEND_DELAY = 3000;

// Very basic "looks like code" heuristic (mirrors vanilla)
function looksLikeCode(text: string): boolean {
  const codePatterns = [
    /^(import|export|const|let|var|function|class|if|for|while|return|def|fn|pub)\b/m,
    /[{}\[\]();]=>/,
    /^\s*(\/\/|#|\/\*|\*)/m,
    /\b(async|await|yield|throw|catch|try)\b/,
  ];
  return codePatterns.some((p) => p.test(text));
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ChatInputProps {
  /** Current chat context level */
  chatLevel: ChatLevel;
  /** Tab ID for session management */
  tabId: string;
  /** Current project ID */
  projectId?: string;
  /** Card ID when in card-level chat */
  cardId?: string;
  /** Whether embedded in CardDetailModal (hides some controls) */
  embedded?: boolean;
  /** Callback when a new session is created via /new command */
  onNewSession?: () => void;
  /** Callback to clear the chat display */
  onClearChat?: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChatInput({
  chatLevel,
  tabId,
  projectId,
  cardId,
  embedded = false,
  onNewSession,
  onClearChat,
}: ChatInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dictationTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [pendingPaste, setPendingPaste] = useState<string | null>(null);

  const { sendMessage, sendSystemInit, registerCallbacks } = useChatService();
  const { connected } = useWS();
  const updateSessionTitle = useSessionStore((s) => s.updateSessionTitle);

  // Voice settings from localStorage
  const [sttAutoSend, setSttAutoSend] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
      return s?.voice?.stt_auto_send ?? false;
    } catch { return false; }
  });
  const [ttsAutoPlay, setTtsAutoPlay] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
      return s?.voice?.tts_auto_play ?? false;
    } catch { return false; }
  });

  // Smart suggestions hook
  const suggestions = SmartSuggestions({
    chatLevel,
    projectId,
    onSelect: (text) => {
      if (textareaRef.current) {
        textareaRef.current.value = text;
        autoResize();
      }
    },
  });

  // ---------------------------------------------------------------------------
  // Slash command handling
  // ---------------------------------------------------------------------------

  const executeSlashCommand = useCallback(
    (cmd: SlashCommand) => {
      if (!textareaRef.current) return;
      const input = textareaRef.current.value.trim();

      switch (cmd.name) {
        case '/new':
          onNewSession?.();
          break;
        case '/clear':
          onClearChat?.();
          break;
        case '/help': {
          // Inject help as a local system message (no server call)
          const helpText = [
            '**Available commands:**',
            '- `/new` — Start a new session',
            '- `/clear` — Clear chat messages',
            '- `/help` — Show this help',
            '- `/agent [name]` — Switch agent persona',
            '- `/meeting` — Import meeting notes',
            '',
            '**Keyboard shortcuts:**',
            '- `Enter` — Send message',
            '- `Shift+Enter` — New line',
            '- `Ctrl+Shift+N` — New session',
            '- `Ctrl+Shift+F` — Search chat history',
          ].join('\n');
          sendSystemInit(helpText, projectId, cardId, useSessionStore.getState().getActiveChatId(tabId));
          break;
        }
        case '/agent': {
          const agentName = input.replace('/agent', '').trim();
          if (agentName) {
            sendMessage(
              `/agent ${agentName}`,
              projectId,
              cardId,
              useSessionStore.getState().getActiveChatId(tabId),
            );
          }
          break;
        }
        case '/meeting':
          sendMessage('/meeting', projectId, cardId, useSessionStore.getState().getActiveChatId(tabId));
          break;
      }

      // Clear textarea
      textareaRef.current.value = '';
      autoResize();
    },
    [projectId, cardId, tabId, sendMessage, sendSystemInit, onNewSession, onClearChat],
  );

  const slashMenu = useSlashMenu(executeSlashCommand);

  // ---------------------------------------------------------------------------
  // Textarea auto-resize
  // ---------------------------------------------------------------------------

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, []);

  // ---------------------------------------------------------------------------
  // Send message
  // ---------------------------------------------------------------------------

  const sendCurrentMessage = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const content = el.value.trim();
    if (!content) return;

    // Clear dictation timer
    if (dictationTimerRef.current) {
      clearTimeout(dictationTimerRef.current);
      dictationTimerRef.current = undefined;
    }

    // Update session title from first message if still default
    const session = useSessionStore.getState().getActiveSession(tabId);
    if (session && /^Session \d+$/.test(session.title)) {
      const title = content.slice(0, 25).trim() || 'Session';
      updateSessionTitle(tabId, session.id, title);
    }

    const sessionId = useSessionStore.getState().getActiveChatId(tabId);
    sendMessage(content, projectId, cardId, sessionId);

    // Clear + reset textarea
    el.value = '';
    autoResize();
    el.focus();
    suggestions.onUserTyping('');
  }, [tabId, projectId, cardId, sendMessage, updateSessionTitle, autoResize, suggestions]);

  // ---------------------------------------------------------------------------
  // Keyboard handlers
  // ---------------------------------------------------------------------------

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      // Slash menu consumes keys first
      if (slashMenu.handleKey(e)) return;

      // Enter (without Shift) sends the message
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendCurrentMessage();
        return;
      }

      // Ctrl+Shift+N → new session
      if (e.ctrlKey && e.shiftKey && e.key === 'N') {
        e.preventDefault();
        onNewSession?.();
      }
    },
    [slashMenu, sendCurrentMessage, onNewSession],
  );

  const handleInputChange = useCallback(() => {
    autoResize();
    const value = textareaRef.current?.value ?? '';

    // Smart suggestions visibility
    suggestions.onUserTyping(value);

    // Slash menu
    if (value.startsWith('/')) {
      slashMenu.update(value);
    } else if (slashMenu.visible) {
      slashMenu.hide();
    }

    // Dictation auto-send (mode 2): if stt_auto_send is on, auto-send after 3s idle
    if (sttAutoSend && value.trim()) {
      if (dictationTimerRef.current) clearTimeout(dictationTimerRef.current);
      dictationTimerRef.current = setTimeout(() => {
        if (textareaRef.current?.value.trim()) {
          sendCurrentMessage();
        }
      }, DICTATION_AUTO_SEND_DELAY);
    }
  }, [autoResize, suggestions, slashMenu, sttAutoSend, sendCurrentMessage]);

  // ---------------------------------------------------------------------------
  // Paste → code detection
  // ---------------------------------------------------------------------------

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const text = e.clipboardData.getData('text');
    if (text.length < CODE_PASTE_MIN_LENGTH) return;
    if (looksLikeCode(text)) {
      setPendingPaste(text);
      // Auto-dismiss after 10 seconds
      setTimeout(() => setPendingPaste(null), 10_000);
    }
  }, []);

  const handleCodeReview = useCallback(() => {
    if (!pendingPaste) return;
    sendMessage(
      `Please review this code:\n\`\`\`\n${pendingPaste}\n\`\`\``,
      projectId,
      cardId,
      useSessionStore.getState().getActiveChatId(tabId),
    );
    setPendingPaste(null);
  }, [pendingPaste, projectId, cardId, tabId, sendMessage]);

  // ---------------------------------------------------------------------------
  // Emoji insertion
  // ---------------------------------------------------------------------------

  const handleEmojiSelect = useCallback((emoji: string) => {
    const el = textareaRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    el.value = el.value.slice(0, start) + emoji + el.value.slice(end);
    el.selectionStart = el.selectionEnd = start + emoji.length;
    autoResize();
    el.focus();
  }, [autoResize]);

  // ---------------------------------------------------------------------------
  // Voice fill-input callback
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const unsub = registerCallbacks({
      onVoiceFillInput: ({ text }) => {
        if (textareaRef.current) {
          textareaRef.current.value = text;
          autoResize();
          suggestions.onUserTyping(text);
        }
      },
      onVoiceRecordingStop: () => {
        if (textareaRef.current) {
          textareaRef.current.value = '';
          autoResize();
          suggestions.onUserTyping('');
        }
      },
      onMessageStreamEnd: ({ content }) => {
        suggestions.onAiResponse(content);
      },
      onMessageReceived: (msg) => {
        if (msg.role === 'assistant' && !msg.streaming) {
          suggestions.onAiResponse(msg.content);
        }
      },
    });
    return unsub;
  }, [registerCallbacks, autoResize, suggestions]);

  // ---------------------------------------------------------------------------
  // Voice toggle helpers
  // ---------------------------------------------------------------------------

  const toggleVoiceSetting = useCallback((key: 'stt_auto_send' | 'tts_auto_play') => {
    try {
      const settings = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
      if (!settings.voice) settings.voice = {};
      const newValue = !settings.voice[key];
      settings.voice[key] = newValue;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
      if (key === 'stt_auto_send') setSttAutoSend(newValue);
      else setTtsAutoPlay(newValue);
      // Sync to backend
      fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      }).catch(() => {});
    } catch { /* ignore */ }
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isMobile = typeof window !== 'undefined' && window.innerWidth < 768;

  return (
    <div className="chat-input-area relative border-t border-border bg-background px-3 py-2">
      {/* Smart suggestions */}
      {suggestions.element}

      {/* Code paste banner */}
      {pendingPaste && (
        <div className="code-paste-banner flex items-center gap-2 px-3 py-1.5 mb-2 text-sm bg-muted rounded border border-border">
          <span className="code-paste-banner-label flex-1 text-muted-foreground truncate">
            Code detected in clipboard
          </span>
          <button
            type="button"
            className="code-paste-banner-review text-xs px-2 py-1 rounded bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            onClick={handleCodeReview}
          >
            Review
          </button>
          <button
            type="button"
            className="code-paste-banner-dismiss text-xs px-2 py-1 rounded hover:bg-accent transition-colors text-muted-foreground"
            onClick={() => setPendingPaste(null)}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Slash command menu */}
      {slashMenu.element}

      {/* Input row */}
      <div className="chat-input-row flex items-end gap-2">
        {/* Emoji picker */}
        {!embedded && (
          <div className="emoji-picker-container flex-shrink-0">
            <EmojiPicker onSelect={handleEmojiSelect} />
          </div>
        )}

        {/* Textarea */}
        <textarea
          ref={textareaRef}
          className="chat-input flex-1 resize-none bg-muted/50 border border-border rounded-lg px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring min-h-[40px] max-h-[150px]"
          placeholder={isMobile ? 'Message...' : 'Type a message or press Alt+V for voice...'}
          rows={1}
          onKeyDown={handleKeyDown}
          onInput={handleInputChange}
          onPaste={handlePaste}
          disabled={!connected}
        />

        {/* Voice toggles */}
        {!embedded && (
          <div className="voice-toggles flex items-center gap-1 flex-shrink-0">
            <button
              type="button"
              className={cn(
                'voice-toggle-btn w-8 h-8 flex items-center justify-center rounded text-sm transition-colors',
                sttAutoSend ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-accent',
              )}
              title={sttAutoSend ? 'Auto-send voice: ON' : 'Auto-send voice: OFF'}
              onClick={() => toggleVoiceSetting('stt_auto_send')}
            >
              {'\uD83D\uDCE4'}
            </button>
            <button
              type="button"
              className={cn(
                'voice-toggle-btn w-8 h-8 flex items-center justify-center rounded text-sm transition-colors',
                ttsAutoPlay ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:bg-accent',
              )}
              title={ttsAutoPlay ? 'Auto-play TTS: ON' : 'Auto-play TTS: OFF'}
              onClick={() => toggleVoiceSetting('tts_auto_play')}
            >
              {'\uD83D\uDD0A'}
            </button>
          </div>
        )}

        {/* Send button */}
        <button
          type="button"
          className={cn(
            'chat-send-btn flex-shrink-0 w-9 h-9 flex items-center justify-center rounded-lg text-sm font-medium transition-colors',
            connected
              ? 'bg-primary text-primary-foreground hover:bg-primary/90 cursor-pointer'
              : 'bg-muted text-muted-foreground cursor-not-allowed',
          )}
          title="Send message"
          disabled={!connected}
          onClick={sendCurrentMessage}
        >
          &rarr;
        </button>
      </div>
    </div>
  );
}
