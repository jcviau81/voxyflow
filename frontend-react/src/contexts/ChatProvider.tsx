import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from 'react';
import { useWS } from '../providers/WebSocketProvider';
import { eventBus } from '../utils/eventBus';
import { VOICE_EVENTS } from '../utils/voiceEvents';
import { useMessageStore } from '../stores/useMessageStore';
import { useWorkspaceStore } from '../stores/useWorkspaceStore';
import { useCardStore } from '../stores/useCardStore';
import { useToastStore } from '../stores/useToastStore';
import { useNotificationStore } from '../stores/useNotificationStore';
import { useUsageStore } from '../stores/useUsageStore';
import { generateId } from '../lib/utils';
import {
  SYSTEM_WORKSPACE_ID,
  STREAMING_SAFETY_TIMEOUT,
  STREAMING_CHAR_DELAY,
  AGENT_PERSONAS,
} from '../lib/constants';
import { useQueryClient } from '@tanstack/react-query';
import type { Message } from '../types';
import { cardKeys, mapRawCard } from '../hooks/api/useCards';
import { showInPageNotification } from '../services/inPageNotifier';

// ---------------------------------------------------------------------------
// Chat event callback types — components subscribe to these via context
// ---------------------------------------------------------------------------

export type ChatEventCallback = (data: Record<string, unknown>) => void;

export interface ChatCallbacks {
  onMessageReceived?: (message: Message) => void;
  onMessageStreaming?: (data: { messageId: string; content: string; chunk: string }) => void;
  onMessageStreamEnd?: (data: { messageId: string; content: string }) => void;
  onMessageEnrichment?: (message: Message) => void;
  onModelStatus?: (data: { model: string; state: string }) => void;
  onTaskStarted?: ChatEventCallback;
  onTaskProgress?: ChatEventCallback;
  onTaskCompleted?: ChatEventCallback;
  onTaskCancelled?: ChatEventCallback;
  onTaskTimeout?: ChatEventCallback;
  onBoardExecuteCardStart?: ChatEventCallback;
  onBoardExecuteCardDone?: ChatEventCallback;
  onBoardExecuteComplete?: ChatEventCallback;
  onBoardExecuteCancelled?: ChatEventCallback;
  onBoardExecuteError?: ChatEventCallback;
  onVoiceFillInput?: (data: { text: string }) => void;
  onVoiceBufferUpdate?: (data: { text: string }) => void;
  onVoiceRecordingStop?: () => void;
  onActionConfirmRequired?: (data: {
    taskId: string;
    action: string;
    message: string;
    sessionId?: string;
  }) => Promise<boolean>;
}


// ---------------------------------------------------------------------------
// Context value
// ---------------------------------------------------------------------------

export interface ChatContextValue {
  /** Send a user message to the backend */
  sendMessage: (
    content: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
  ) => Message;
  /** Send a hidden system-init message (no user bubble) */
  sendSystemInit: (
    contextHint: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
  ) => void;
  /** Load chat history from backend API */
  loadHistory: (
    chatId: string,
    workspaceId?: string,
    cardId?: string,
    sessionId?: string,
    replaceSession?: boolean,
  ) => Promise<Message[]>;
  /** Get messages from the local store */
  getHistory: (workspaceId?: string, sessionId?: string) => Message[];
  /** Clear all local messages */
  clearHistory: () => void;
  /** Simulate character-by-character streaming for a message. Pass an AbortSignal to stop early. */
  simulateStreaming: (messageId: string, fullContent: string, signal?: AbortSignal) => Promise<void>;
  /** Set the active session ID (called by ChatWindow) */
  setActiveSessionId: (sessionId: string | undefined) => void;
  /** Register event callbacks (returns unsubscribe fn) */
  registerCallbacks: (callbacks: ChatCallbacks) => () => void;
  /** Get layer state from localStorage */
  getLayerState: () => Record<string, boolean>;
  /** Handle incoming voice transcript (called by VoiceInput component) */
  handleVoiceTranscript: (transcript: string, isFinal: boolean) => void;
  /** Handle voice recording stop (called by VoiceInput component) */
  handleVoiceStop: () => void;
  /** Create a card from a suggestion (called by Opportunities panel) */
  createCardFromSuggestion: (data: { title: string; description?: string }) => void;
  /** Directly spawn a worker to execute a card (bypasses chat layer) */
  executeCard: (cardId: string, workspaceId?: string) => void;
}

export const ChatContext = createContext<ChatContextValue | null>(null);

// ---------------------------------------------------------------------------
// Internal streaming state (not reactive — managed via refs)
// ---------------------------------------------------------------------------

interface StreamState {
  content: string;
  messageId: string;
}

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function ChatProvider({ children }: { children: ReactNode }) {
  const { send, subscribe, connectionState } = useWS();
  const queryClient = useQueryClient();
  // The message + workspace stores are only ever read via refs/getState (never
  // via reactive render) — subscribing to the whole state here would re-render
  // the provider (and the entire tree below it) on every streamed token.
  // messageStore actions are accessed through messageStoreRef (snapshot below);
  // workspace state is read fresh via useWorkspaceStore.getState() at call time.
  const messageStore = useMessageStore.getState();
  // Zustand action refs are stable across renders, so this selector never
  // re-renders the provider.
  const addCard = useCardStore((s) => s.addCard);
  const showToast = useToastStore((s) => s.showToast);
  const addNotification = useNotificationStore((s) => s.addNotification);
  const addNotificationRef = useRef(addNotification);
  addNotificationRef.current = addNotification;

  // Refs for mutable state that must not trigger re-renders
  const activeSessionIdRef = useRef<string | undefined>(undefined);
  const streamingMessagesRef = useRef<Map<string, StreamState>>(new Map());
  const streamingTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Maps a finished streamId -> the bubble messageId it wrote to. Lets a late
  // 'done' (e.g. multi-device fan-out arriving after forceEndAllStreaming
  // already cleared streamingMessagesRef) update the existing bubble instead of
  // spawning a duplicate assistant bubble. Entries auto-expire.
  const recentlyFinishedRef = useRef<Map<string, string>>(new Map());
  const recentlyFinishedTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const RECENTLY_FINISHED_TTL_MS = 30000;
  const voiceAutoSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceAutoSendBufferRef = useRef('');
  const callbacksRef = useRef<Set<ChatCallbacks>>(new Set());

  // Stable ref for sendMessage — lets flushVoiceAutoSend use the same code path
  // as manual send, without creating a dependency cycle.
  const sendMessageRef = useRef<ChatContextValue['sendMessage'] | null>(null);

  // Per-session safety timers for the "worker done, Voxy about to reply" flag.
  // Auto-clears the pending flag if the dispatcher never streams a response.
  const pendingAssistantTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const PENDING_ASSISTANT_TIMEOUT_MS = 30000;

  // Conversation lock: queue of user messages typed mid-stream. They render as
  // `queued: true` (dimmed) and are flushed in order when the current stream ends.
  const pendingQueueRef = useRef<Array<{
    messageId: string;
    content: string;
    workspaceId: string;
    cardId?: string;
    sessionId?: string;
    chatLevel: 'general' | 'workspace' | 'card';
  }>>([]);
  // Populated below; called from stream-end handlers. Ref avoids hoist issues.
  const flushNextQueuedRef = useRef<() => void>(() => {});

  // Stable refs for store methods (avoid stale closures). These hold getState()
  // snapshots; store actions are stable so method calls are always valid. For
  // reactive state *values* (e.g. currentWorkspaceId) read getState() fresh at
  // call time, since the provider no longer re-renders on store changes.
  const messageStoreRef = useRef(messageStore);
  messageStoreRef.current = messageStore;

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  /** Fire a named callback on all registered listeners */
  const emitCallbacks = useCallback(
    (key: keyof ChatCallbacks, ...args: unknown[]) => {
      callbacksRef.current.forEach((cb) => {
        const fn = cb[key] as ((...a: unknown[]) => unknown) | undefined;
        if (fn) {
          try {
            fn(...args);
          } catch (err) {
            console.error(`[ChatProvider] callback error (${String(key)}):`, err);
          }
        }
      });
    },
    [],
  );

  const getWorkspaceIdFromSession = useCallback((sessionId?: string): string => {
    if (!sessionId) return SYSTEM_WORKSPACE_ID;
    if (sessionId.startsWith('workspace:')) return sessionId.slice('workspace:'.length);
    return SYSTEM_WORKSPACE_ID;
  }, []);

  const getAgentEmoji = useCallback((agentType?: string): string => {
    if (!agentType) return '\u{1F916}';
    const persona = AGENT_PERSONAS[agentType.toLowerCase()];
    return persona?.emoji || '\u{1F916}';
  }, []);

  const getVoiceSetting = useCallback(<T,>(key: string, defaultValue: T): T => {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const val = settings?.voice?.[key];
        if (val !== undefined) return val as T;
      }
    } catch { /* ignore */ }
    return defaultValue;
  }, []);

  const getLayerState = useCallback((): Record<string, boolean> => {
    try {
      const stored = localStorage.getItem('voxyflow_layer_toggles');
      if (stored) return JSON.parse(stored);
    } catch { /* ignore */ }
    return { deep: true };
  }, []);

  // ---------------------------------------------------------------------------
  // Streaming timer management
  // ---------------------------------------------------------------------------

  const clearStreamingTimer = useCallback((streamId: string) => {
    const timer = streamingTimersRef.current.get(streamId);
    if (timer) {
      clearTimeout(timer);
      streamingTimersRef.current.delete(streamId);
    }
  }, []);

  const clearPendingAssistant = useCallback((sessionId?: string) => {
    if (!sessionId) return;
    const timer = pendingAssistantTimersRef.current.get(sessionId);
    if (timer) {
      clearTimeout(timer);
      pendingAssistantTimersRef.current.delete(sessionId);
    }
    messageStoreRef.current.setPendingAssistant(sessionId, false);
  }, []);

  const markPendingAssistant = useCallback((sessionId?: string) => {
    if (!sessionId) return;
    messageStoreRef.current.setPendingAssistant(sessionId, true);
    const existing = pendingAssistantTimersRef.current.get(sessionId);
    if (existing) clearTimeout(existing);
    pendingAssistantTimersRef.current.set(
      sessionId,
      setTimeout(() => {
        pendingAssistantTimersRef.current.delete(sessionId);
        messageStoreRef.current.setPendingAssistant(sessionId, false);
      }, PENDING_ASSISTANT_TIMEOUT_MS),
    );
  }, []);

  // Remember which bubble a just-finished stream wrote to, so a late duplicate
  // 'done' can update it instead of adding a new bubble. Entry self-expires.
  const markRecentlyFinished = useCallback((streamId: string, messageId: string) => {
    recentlyFinishedRef.current.set(streamId, messageId);
    const existing = recentlyFinishedTimersRef.current.get(streamId);
    if (existing) clearTimeout(existing);
    recentlyFinishedTimersRef.current.set(
      streamId,
      setTimeout(() => {
        recentlyFinishedRef.current.delete(streamId);
        recentlyFinishedTimersRef.current.delete(streamId);
      }, RECENTLY_FINISHED_TTL_MS),
    );
  }, []);

  const handleStreamComplete = useCallback(
    (streamId: string, finalContent: string) => {
      const stream = streamingMessagesRef.current.get(streamId);
      if (stream) {
        const content = finalContent || stream.content;
        messageStoreRef.current.updateMessage(stream.messageId, {
          content,
          streaming: false,
        });
        streamingMessagesRef.current.delete(streamId);
        markRecentlyFinished(streamId, stream.messageId);
        clearStreamingTimer(streamId);

        emitCallbacks('onMessageStreamEnd', { messageId: stream.messageId, content });
        flushNextQueuedRef.current();
      }
    },
    [clearStreamingTimer, emitCallbacks, markRecentlyFinished],
  );

  const resetStreamingTimer = useCallback(
    (streamId: string) => {
      clearStreamingTimer(streamId);
      streamingTimersRef.current.set(
        streamId,
        setTimeout(() => {
          console.warn(`[ChatProvider] Streaming safety timeout for ${streamId}`);
          handleStreamComplete(streamId, '');
        }, STREAMING_SAFETY_TIMEOUT),
      );
    },
    [clearStreamingTimer, handleStreamComplete],
  );

  const forceEndAllStreaming = useCallback(() => {
    if (streamingMessagesRef.current.size === 0) return;
    console.log(
      `[ChatProvider] Force-ending ${streamingMessagesRef.current.size} streaming message(s)`,
    );

    for (const [streamId, stream] of streamingMessagesRef.current) {
      const truncatedContent = stream.content
        ? stream.content + '\n\n---\n*Connection lost — response may be incomplete. Reconnecting…*'
        : '';
      messageStoreRef.current.updateMessage(stream.messageId, {
        streaming: false,
        content: truncatedContent,
        truncated: true,
      });
      emitCallbacks('onMessageStreamEnd', {
        messageId: stream.messageId,
        content: truncatedContent,
      });
      markRecentlyFinished(streamId, stream.messageId);
      clearStreamingTimer(streamId);
    }
    streamingMessagesRef.current.clear();
    flushNextQueuedRef.current();
  }, [clearStreamingTimer, emitCallbacks, markRecentlyFinished]);

  // ---------------------------------------------------------------------------
  // Streaming chunk handler
  // ---------------------------------------------------------------------------

  const handleStreamingChunk = useCallback(
    (streamId: string, chunk: string, sessionId?: string, model?: string) => {
      let stream = streamingMessagesRef.current.get(streamId);

      if (!stream) {
        const message = messageStoreRef.current.addMessage({
          role: 'assistant',
          content: '',
          streaming: true,
          sessionId,
          model,
          workspaceId: getWorkspaceIdFromSession(sessionId),
        });
        stream = { content: '', messageId: message.id };
        streamingMessagesRef.current.set(streamId, stream);
      }

      stream.content += chunk;
      messageStoreRef.current.updateMessage(stream.messageId, {
        content: stream.content,
        streaming: true,
      });

      emitCallbacks('onMessageStreaming', {
        messageId: stream.messageId,
        content: stream.content,
        chunk,
      });

      resetStreamingTimer(streamId);
    },
    [getWorkspaceIdFromSession, resetStreamingTimer, emitCallbacks],
  );

  // ---------------------------------------------------------------------------
  // Full (non-streaming) response handler
  // ---------------------------------------------------------------------------

  const handleFullResponse = useCallback(
    (content: string, sessionId?: string) => {
      const message = messageStoreRef.current.addMessage({
        role: 'assistant',
        content,
        sessionId,
        workspaceId: getWorkspaceIdFromSession(sessionId),
      });
      emitCallbacks('onMessageReceived', message);
    },
    [getWorkspaceIdFromSession, emitCallbacks],
  );

  // ---------------------------------------------------------------------------
  // Tool UI action handler
  // ---------------------------------------------------------------------------

  const handleToolUiAction = useCallback(
    (uiAction: string, _data: Record<string, unknown> | null) => {
      switch (uiAction) {
        case 'refresh_kanban':
          // Components can listen via onCardUpdated or react to store changes
          break;
        case 'show_kanban':
        case 'show_chat':
          // Navigation handled by React Router in consuming components
          break;
        default:
          break;
      }
      // All tool UI actions are forwarded as generic callbacks;
      // components subscribe to what they need.
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Voice auto-send
  // ---------------------------------------------------------------------------

  const flushVoiceAutoSend = useCallback(() => {
    if (voiceAutoSendTimerRef.current) {
      clearTimeout(voiceAutoSendTimerRef.current);
      voiceAutoSendTimerRef.current = null;
    }
    const buffer = voiceAutoSendBufferRef.current;
    if (buffer) {
      voiceAutoSendBufferRef.current = '';

      // Stop mic immediately before sending to prevent TTS audio loop
      eventBus.emit(VOICE_EVENTS.VOICE_RECORDING_STOP);

      if (sendMessageRef.current) {
        sendMessageRef.current(buffer, undefined, undefined, activeSessionIdRef.current);
      }

      // Clear the textarea after send
      emitCallbacks('onVoiceFillInput', { text: '' });
    }
  }, [emitCallbacks]);

  // ---------------------------------------------------------------------------
  // WebSocket subscriptions
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const unsubs: Array<() => void> = [];

    // --- chat:response ---
    unsubs.push(
      subscribe('chat:response', (payload) => {
        const { messageId, content, streaming, done, sessionId, model, usage, chatId } = payload as {
          messageId: string;
          content: string;
          streaming: boolean;
          done: boolean;
          sessionId?: string;
          model?: string;
          chatId?: string;
          usage?: {
            inputTokens: number;
            outputTokens: number;
            cacheReadTokens?: number;
            cacheCreationTokens?: number;
            contextWindow: number;
            model?: string;
            contextBreakdown?: import('../stores/useUsageStore').ContextBreakdown | null;
          };
        };
        // Final streaming chunk may arrive without sessionId — allow it
        // through when we already track the messageId in streamingMessagesRef,
        // or when it is a late 'done' for a recently-finished stream (so it can
        // update the existing bubble rather than be dropped or duplicated).
        if (
          !sessionId &&
          !(done && streamingMessagesRef.current.has(messageId)) &&
          !(done && recentlyFinishedRef.current.has(messageId))
        ) {
          console.warn('[ChatProvider] chat:response without sessionId — dropping', { messageId });
          return;
        }

        // Cross-device live sync: if this event arrived via broadcast (fan-out
        // from another device), the originator's sessionId is unknown here and
        // `getWorkspaceIdFromSession` would mis-route the bubble to SYSTEM. Use
        // the chatId (server-canonical) to derive the correct workspaceId so
        // message:new and streaming bubbles land in the right workspace store.
        const effectiveSessionId =
          sessionId ||
          (chatId?.startsWith('workspace:') ? chatId : undefined) ||
          (chatId?.startsWith('card:') ? chatId : undefined);

        // Voxy is actually speaking — drop the "worker-done, about to reply" flag.
        clearPendingAssistant(effectiveSessionId);

        if (streaming && !done) {
          handleStreamingChunk(messageId, content, effectiveSessionId, model);
        } else if (done && streamingMessagesRef.current.has(messageId)) {
          handleStreamComplete(messageId, content);
        } else if (done && recentlyFinishedRef.current.has(messageId)) {
          // Late 'done' for a stream we already finished (e.g. multi-device
          // fan-out arriving after forceEndAllStreaming cleared the stream).
          // Update the existing bubble instead of spawning a duplicate.
          const finishedMessageId = recentlyFinishedRef.current.get(messageId)!;
          messageStoreRef.current.updateMessage(finishedMessageId, {
            content,
            streaming: false,
            truncated: false,
          });
          emitCallbacks('onMessageStreamEnd', { messageId: finishedMessageId, content });
        } else {
          handleFullResponse(content, effectiveSessionId);
        }

        if (done && sessionId && usage && typeof usage.contextWindow === 'number') {
          useUsageStore.getState().setUsage(sessionId, {
            inputTokens: usage.inputTokens ?? 0,
            outputTokens: usage.outputTokens ?? 0,
            cacheReadTokens: usage.cacheReadTokens,
            cacheCreationTokens: usage.cacheCreationTokens,
            contextWindow: usage.contextWindow,
            model: usage.model,
            contextBreakdown: usage.contextBreakdown,
          });
        }
      }),
    );

    // --- chat:enrichment ---
    unsubs.push(
      subscribe('chat:enrichment', (payload) => {
        const { messageId, content, model, action, sessionId } = payload as {
          messageId: string;
          content: string;
          model: string;
          action: string;
          done: boolean;
          sessionId?: string;
        };
        if (!sessionId) {
          console.warn('[ChatProvider] chat:enrichment without sessionId — dropping', { messageId });
          return;
        }

        const message = messageStoreRef.current.addMessage({
          role: 'assistant',
          content,
          enrichment: true,
          enrichmentAction: action as 'enrich' | 'correct',
          model,
          sessionId,
          workspaceId: getWorkspaceIdFromSession(sessionId),
        });
        emitCallbacks('onMessageEnrichment', message);
      }),
    );

    // --- model:status ---
    unsubs.push(
      subscribe('model:status', (payload) => {
        const { model, state } = payload as { model: string; state: string };
        emitCallbacks('onModelStatus', { model, state });
        // Forward to eventBus so any component (e.g. ModePill) can react without
        // needing to register callbacks through the ChatProvider context.
        eventBus.emit('model:status', { model, state });
      }),
    );

    // --- tool:result ---
    unsubs.push(
      subscribe('tool:result', (payload) => {
        const { tool, success, data, error, ui_action } = payload as {
          tool: string;
          success: boolean;
          data: Record<string, unknown> | null;
          error: string | null;
          ui_action: string | null;
        };

        if (success && ui_action) {
          handleToolUiAction(ui_action, data);
        }

        if (success) {
          showToast(`\u{1F527} ${tool}: Done`, 'success', 3000);
        } else {
          showToast(`\u{1F527} ${tool} failed: ${error}`, 'error', 5000);
        }
      }),
    );

    // --- task events ---
    const normalizeTaskId = (p: Record<string, unknown>) => {
      if (p.task_id && !p.taskId) (p as Record<string, unknown>).taskId = p.task_id;
    };

    unsubs.push(
      subscribe('task:started', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskStarted', payload);
      }),
    );
    unsubs.push(
      subscribe('task:progress', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskProgress', payload);
      }),
    );
    unsubs.push(
      subscribe('task:completed', (payload) => {
        normalizeTaskId(payload);
        const { intent, summary, success, cardId, sessionId: taskSessionId } = payload as {
          intent: string;
          summary: string;
          success: boolean;
          taskId: string;
          sessionId?: string;
          workspaceId?: string;
          cardId?: string;
        };
        emitCallbacks('onTaskCompleted', payload);

        // Successful workers trigger a dispatcher re-entry — show typing dots in
        // the originating chat until Voxy starts streaming the follow-up reply.
        if (success && taskSessionId) {
          markPendingAssistant(taskSessionId);
        }

        if (success) {
          showToast(`\u2705 ${intent}: ${summary.substring(0, 50)}`, 'success', 4000);
        } else {
          showToast(`\u274C ${intent} failed`, 'error', 5000);
        }

        // Persist to notification panel for activity history
        addNotificationRef.current({
          type: 'worker_completed',
          message: success
            ? `Worker completed: ${intent}`
            : `Worker failed: ${intent}`,
          taskId: (payload as Record<string, unknown>).taskId as string | undefined,
          success,
          link: cardId || undefined,
        });

        // In-page browser notification — complements Web Push so browsers
        // without working GCM (e.g. Brave on Linux) still get a native OS
        // notification while the tab is open. Matching tag de-dupes if Web
        // Push also fires.
        try {
          type PushCfg = {
            enabled?: boolean;
            events?: { worker_done?: boolean; autonomy_result?: boolean };
          };
          type CachedSettings = { push?: PushCfg } | undefined;
          const cached = queryClient.getQueryData(['settings']) as CachedSettings;
          const taskId = (payload as Record<string, unknown>).taskId as string | undefined;
          const workspaceId = (payload as Record<string, unknown>).workspaceId as string | undefined;
          const apply = (push?: PushCfg) => {
            if (!push?.enabled) return;
            if (push.events?.worker_done === false) return;
            const intentLabel = intent || 'task';
            const result = (payload as { result?: string }).result;
            const url = cardId && workspaceId
              ? `/workspace/${workspaceId}?card=${cardId}`
              : workspaceId ? `/workspace/${workspaceId}` : '/';
            void showInPageNotification({
              title: success
                ? `Worker finished: ${intentLabel}`
                : `Worker failed: ${intentLabel}`,
              body: ((summary || result || '') as string).slice(0, 140),
              url,
              tag: `worker-${taskId || Date.now()}`,
            });
          };
          if (cached?.push) {
            apply(cached.push);
          } else {
            // Fallback: fetch once and cache for subsequent completions.
            void fetch('/api/settings')
              .then((r) => (r.ok ? r.json() : null))
              .then((data: CachedSettings) => {
                if (data) queryClient.setQueryData(['settings'], data);
                apply(data?.push);
              })
              .catch(() => { /* ignore */ });
          }
        } catch {
          /* never let notification logic break the handler */
        }
      }),
    );
    unsubs.push(
      subscribe('task:cancelled', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskCancelled', payload);
        clearPendingAssistant((payload as { sessionId?: string }).sessionId);
        showToast('Task cancelled', 'info', 3000);
      }),
    );
    unsubs.push(
      subscribe('task:timeout', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskTimeout', payload);
        clearPendingAssistant((payload as { sessionId?: string }).sessionId);
        const { intent, timeout_seconds } = payload as {
          intent: string;
          timeout_seconds: number;
        };
        showToast(
          `Worker timed out after ${Math.floor((timeout_seconds || 300) / 60)}m: ${intent || 'task'}`,
          'error',
          5000,
        );
      }),
    );

    // --- action:confirm_required ---
    unsubs.push(
      subscribe('action:confirm_required', (payload) => {
        const { taskId, action, message, sessionId } = payload as {
          taskId: string;
          action: string;
          message: string;
          sessionId?: string;
        };

        // Attempt async confirm via registered callback
        const confirmPromises: Promise<boolean>[] = [];
        callbacksRef.current.forEach((cb) => {
          if (cb.onActionConfirmRequired) {
            confirmPromises.push(
              cb.onActionConfirmRequired({ taskId, action, message, sessionId }),
            );
          }
        });

        if (confirmPromises.length > 0) {
          // Use first callback's result
          confirmPromises[0].then((confirmed) => {
            send('action:confirm', {
              taskId,
              confirmed,
              sessionId: sessionId || activeSessionIdRef.current || undefined,
            });
          });
        } else {
          // No handler registered — auto-deny
          send('action:confirm', {
            taskId,
            confirmed: false,
            sessionId: sessionId || activeSessionIdRef.current || undefined,
          });
        }
      }),
    );

    // --- Board execution events ---
    unsubs.push(
      subscribe('kanban:execute:card:start', (payload) => {
        emitCallbacks('onBoardExecuteCardStart', payload);
      }),
    );
    unsubs.push(
      subscribe('kanban:execute:card:done', (payload) => {
        emitCallbacks('onBoardExecuteCardDone', payload);
      }),
    );
    unsubs.push(
      subscribe('kanban:execute:complete', (payload) => {
        emitCallbacks('onBoardExecuteComplete', payload);
        showToast(
          `Board execution complete \u2014 ${(payload as Record<string, unknown>).completed} cards done`,
          'success',
          5000,
        );
      }),
    );
    unsubs.push(
      subscribe('kanban:execute:cancelled', (payload) => {
        emitCallbacks('onBoardExecuteCancelled', payload);
        showToast('Board execution cancelled', 'info', 3000);
      }),
    );
    unsubs.push(
      subscribe('kanban:execute:error', (payload) => {
        emitCallbacks('onBoardExecuteError', payload);
        showToast(
          `Board execution error: ${(payload as Record<string, unknown>).error}`,
          'error',
          5000,
        );
      }),
    );

    // --- voice:transcript (from SttService / voice input components) ---
    // Note: In React, voice transcripts will come via component props/callbacks,
    // but we keep the WS handler for backend-initiated transcripts.

    // --- cards:changed — invalidate card queries when workers or tools update cards ---
    unsubs.push(
      subscribe('cards:changed', (payload) => {
        const { workspaceId, cardId } = payload as { workspaceId?: string; cardId?: string };
        if (cardId) {
          void queryClient.invalidateQueries({ queryKey: cardKeys.detail(cardId) });
          // Fetch updated card and upsert into Zustand so open modals update in real-time
          fetch(`/api/cards/${cardId}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((raw) => {
              if (raw) useCardStore.getState().upsertCard(mapRawCard(raw as Record<string, unknown>));
            })
            .catch((e) => console.warn('[ChatProvider] card refresh failed', cardId, e));
        }
        if (workspaceId) {
          void queryClient.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
        }
      }),
    );

    // --- reminder:fired — show toast when a reminder job fires ---
    unsubs.push(
      subscribe('reminder:fired', (payload) => {
        const { jobName, message } = payload as { jobName?: string; message?: string };
        showToast(`${jobName || 'Reminder'}: ${message || ''}`, 'info', 5000);
        addNotificationRef.current({
          type: 'system_job',
          message: `${jobName || 'Reminder'}: ${message || ''}`,
          jobId: (payload as Record<string, unknown>).jobId as string | undefined,
          success: true,
        });
      }),
    );

    // --- system:job:completed — scheduler / cron job finished ---
    unsubs.push(
      subscribe('system:job:completed', (payload) => {
        const { jobId, jobName, status, message } = payload as {
          jobId: string;
          jobName: string;
          status: string;
          message: string;
        };
        addNotificationRef.current({
          type: 'system_job',
          message: `${jobName}: ${message}`,
          jobId,
          success: status === 'ok' || status === 'skipped',
          details: message,
        });
      }),
    );

    // --- chat:message:new — live cross-device sync ---
    // Backend broadcasts a finalized user or assistant message to every OTHER
    // connected client whenever a chat turn is processed. This lets a phone
    // and a desktop see each other's messages without a manual refresh.
    // The originating client does NOT receive its own broadcast (emit_to_others),
    // so we don't need to dedup against the local sender path — only against
    // prior broadcasts (e.g. two tabs both receiving the same event).
    unsubs.push(
      subscribe('chat:message:new', (payload) => {
        const { sessionId, message } = payload as {
          chatId?: string;
          sessionId?: string;
          message?: {
            role?: 'user' | 'assistant';
            content?: string;
            timestamp?: number; // seconds since epoch
            model?: string;
          };
        };
        if (!message || !message.role || typeof message.content !== 'string') return;
        if (message.role !== 'user' && message.role !== 'assistant') return;

        // Timestamp from backend is seconds (time.time()) — convert to ms.
        const tsMs = typeof message.timestamp === 'number'
          ? Math.round(message.timestamp * 1000)
          : Date.now();

        const converted: Message = {
          id: generateId(),
          role: message.role,
          content: message.content,
          timestamp: tsMs,
          sessionId,
          workspaceId: getWorkspaceIdFromSession(sessionId),
          streaming: false,
          model: message.model,
        };

        // setMessages dedups by role+timestamp+content-prefix — safe to call
        // even when another tab already injected the same broadcast.
        messageStoreRef.current.setMessages([converted]);
      }),
    );

    // --- message.deleted — cross-tab/device sync of manual message deletes ---
    // Originating tab does the optimistic remove inline; this handler keeps
    // every other connected client in sync. removeMessage is a no-op when
    // the id is already gone, so it's safe to receive our own broadcast too.
    unsubs.push(
      subscribe('message.deleted', (payload) => {
        const messageId = (payload as { message_id?: string }).message_id;
        if (messageId) messageStoreRef.current.removeMessage(messageId);
      }),
    );

    // --- ws:connected — sync session on connect/reconnect ---
    // 1. Sends session:sync so the backend delivers any pending worker results
    //    that accumulated while the client was disconnected.
    // 2. If any messages were truncated mid-stream, reloads history from
    //    the backend to replace them with the complete server-side version.
    unsubs.push(
      subscribe('ws:connected', () => {
        const sessionId = activeSessionIdRef.current;
        if (sessionId) {
          send('session:sync', { sessionId });

          // Check if any messages in this session were truncated
          const msgs = messageStoreRef.current.getMessages(undefined, sessionId);
          const hasTruncated = msgs.some((m) => m.truncated);
          if (hasTruncated) {
            // Reload full history from backend to replace truncated messages
            void fetch(`/api/sessions/${sessionId}?limit=50`)
              .then((r) => (r.ok ? r.json() : null))
              .then((data) => {
                if (!data?.messages) return;
                const backendMessages: Array<{
                  id?: string;
                  role: string;
                  content: string;
                  timestamp?: string;
                  model?: string;
                  type?: string;
                }> = data.messages;

                const converted: Message[] = backendMessages
                  .filter((m) => m.role === 'user' || m.role === 'assistant')
                  .filter((m) => m.type !== 'enrichment' && m.type !== 'worker_result')
                  .map((m) => ({
                    id: m.id || generateId(),
                    role: m.role as 'user' | 'assistant',
                    content: m.content || '',
                    timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
                    sessionId,
                    streaming: false,
                    model: m.model,
                  }));

                if (converted.length > 0) {
                  messageStoreRef.current.replaceSessionMessages(converted, sessionId);
                }
              })
              .catch((e) => console.warn('[ChatProvider] Failed to recover truncated messages:', e));
          }
        }
      }),
    );

    return () => {
      unsubs.forEach((unsub) => unsub());
    };
  }, [
    subscribe,
    send,
    showToast,
    handleStreamingChunk,
    handleStreamComplete,
    handleFullResponse,
    handleToolUiAction,
    getWorkspaceIdFromSession,
    getAgentEmoji,
    emitCallbacks,
    queryClient,
    markPendingAssistant,
    clearPendingAssistant,
  ]);

  // --- Force-end streaming on WS disconnect ---
  const prevConnected = useRef(connectionState);
  useEffect(() => {
    if (
      prevConnected.current === 'connected' &&
      (connectionState === 'disconnected' || connectionState === 'reconnecting')
    ) {
      forceEndAllStreaming();
    }
    prevConnected.current = connectionState;
  }, [connectionState, forceEndAllStreaming]);

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  const sendMessage = useCallback(
    (
      content: string,
      workspaceId?: string,
      cardId?: string,
      sessionId?: string,
    ): Message => {
      const store = messageStoreRef.current;

      // Conversation lock: if any assistant stream is active OR there are
      // already queued messages ahead, mark this one as `queued` and hold it.
      const isBusy =
        streamingMessagesRef.current.size > 0 || pendingQueueRef.current.length > 0;

      const message = store.addMessage({
        role: 'user',
        content,
        workspaceId: workspaceId || undefined,
        cardId,
        sessionId,
        queued: isBusy || undefined,
      });

      const layers = getLayerState();
      const currentWorkspaceId = message.workspaceId || SYSTEM_WORKSPACE_ID;
      const currentCardId = message.cardId || useWorkspaceStore.getState().selectedCardId;
      let chatLevel: 'general' | 'workspace' | 'card' = 'general';
      if (currentCardId) {
        chatLevel = 'card';
      } else if (currentWorkspaceId && currentWorkspaceId !== SYSTEM_WORKSPACE_ID) {
        chatLevel = 'workspace';
      }

      if (isBusy) {
        pendingQueueRef.current.push({
          messageId: message.id,
          content,
          workspaceId: currentWorkspaceId,
          cardId: currentCardId || undefined,
          sessionId: sessionId || undefined,
          chatLevel,
        });
        return message;
      }

      send('chat:message', {
        content,
        workspaceId: currentWorkspaceId,
        cardId: currentCardId || undefined,
        messageId: message.id,
        chatLevel,
        layers,
        sessionId: sessionId || undefined,
        chatId: sessionId || undefined,
      });

      return message;
    },
    [send, getLayerState],
  );

  // Flush one queued user message after the current stream ends.
  // Runs on every onMessageStreamEnd; chains naturally if more than one is queued.
  const flushNextQueued = useCallback(() => {
    if (streamingMessagesRef.current.size > 0) return;
    const next = pendingQueueRef.current.shift();
    if (!next) return;

    messageStoreRef.current.updateMessage(next.messageId, { queued: false });

    send('chat:message', {
      content: next.content,
      workspaceId: next.workspaceId,
      cardId: next.cardId,
      messageId: next.messageId,
      chatLevel: next.chatLevel,
      layers: getLayerState(),
      sessionId: next.sessionId,
      chatId: next.sessionId,
    });
  }, [send, getLayerState]);
  flushNextQueuedRef.current = flushNextQueued;

  // Keep sendMessageRef in sync so flushVoiceAutoSend can use it
  sendMessageRef.current = sendMessage;

  const sendSystemInit = useCallback(
    (
      contextHint: string,
      workspaceId?: string,
      cardId?: string,
      sessionId?: string,
    ) => {
      const layers = getLayerState();
      const currentWorkspaceId = workspaceId || SYSTEM_WORKSPACE_ID;
      const currentCardId = cardId || undefined;
      let chatLevel: 'general' | 'workspace' | 'card' = 'general';
      if (currentCardId) chatLevel = 'card';
      else if (currentWorkspaceId && currentWorkspaceId !== SYSTEM_WORKSPACE_ID) chatLevel = 'workspace';

      const resolvedSessionId = sessionId || activeSessionIdRef.current || undefined;
      send('chat:message', {
        content: contextHint,
        workspaceId: currentWorkspaceId,
        cardId: currentCardId,
        chatLevel,
        layers,
        sessionId: resolvedSessionId,
        chatId: resolvedSessionId,
        systemInit: true,
      });
    },
    [send, getLayerState],
  );

  const loadHistory = useCallback(
    async (
      chatId: string,
      workspaceId?: string,
      cardId?: string,
      sessionId?: string,
      replaceSession = false,
    ): Promise<Message[]> => {
      // Live cross-device sync: announce that this tab is now viewing
      // `chatId` so the backend fans out streaming tokens + completion
      // events from other devices on the same canonical chat. Safe to
      // send even if disconnected — useWebSocket queues it.
      try {
        send('chat:subscribe', {
          chatId,
          workspaceId: workspaceId || undefined,
          cardId: cardId || undefined,
        });
      } catch {
        /* best effort — offline queue retries on reconnect */
      }
      try {
        const resp = await fetch(`/api/sessions/${chatId}?limit=50`);
        if (!resp.ok) return [];
        const data = await resp.json();
        const backendMessages: Array<{
          id?: string;
          role: string;
          content: string;
          timestamp?: string;
          model?: string;
          type?: string;
        }> = data.messages || [];

        const converted: Message[] = backendMessages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .filter((m) => m.type !== 'enrichment' && m.type !== 'worker_result')
          .map((m) => ({
            // Prefer the server-assigned id so the manual delete endpoint
            // can target this message; fall back for ancient sessions
            // where backfill hasn't run yet.
            id: m.id || generateId(),
            role: m.role as 'user' | 'assistant',
            content: m.content || '',
            timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
            workspaceId: workspaceId || undefined,
            cardId: cardId || undefined,
            sessionId: sessionId || undefined,
            streaming: false,
            model: m.model,
          }));

        if (converted.length > 0) {
          const store = messageStoreRef.current;
          if (replaceSession) {
            store.replaceSessionMessages(converted, sessionId, workspaceId, cardId);
          } else {
            store.setMessages(converted);
          }
        }
        return converted;
      } catch (e) {
        console.warn('[ChatProvider] Failed to load history:', e);
        return [];
      }
    },
    [send],
  );

  const getHistory = useCallback(
    (workspaceId?: string, sessionId?: string): Message[] => {
      return messageStoreRef.current.getMessages(workspaceId, sessionId);
    },
    [],
  );

  const clearHistory = useCallback(() => {
    messageStoreRef.current.clearMessages();
  }, []);

  const simulateStreaming = useCallback(
    async (messageId: string, fullContent: string, signal?: AbortSignal): Promise<void> => {
      let displayed = '';
      for (const char of fullContent) {
        if (signal?.aborted) {
          // Flush whatever was rendered so the message isn't left in a streaming state.
          messageStoreRef.current.updateMessage(messageId, {
            content: displayed,
            streaming: false,
          });
          emitCallbacks('onMessageStreamEnd', { messageId, content: displayed });
          return;
        }
        displayed += char;
        messageStoreRef.current.updateMessage(messageId, {
          content: displayed,
          streaming: true,
        });
        emitCallbacks('onMessageStreaming', {
          messageId,
          content: displayed,
          chunk: char,
        });
        await new Promise((r) => setTimeout(r, STREAMING_CHAR_DELAY));
      }
      messageStoreRef.current.updateMessage(messageId, {
        content: fullContent,
        streaming: false,
      });
      emitCallbacks('onMessageStreamEnd', { messageId, content: fullContent });
    },
    [emitCallbacks],
  );

  const setActiveSessionId = useCallback((sessionId: string | undefined) => {
    activeSessionIdRef.current = sessionId;
  }, []);

  const registerCallbacks = useCallback((callbacks: ChatCallbacks): (() => void) => {
    callbacksRef.current.add(callbacks);
    return () => {
      callbacksRef.current.delete(callbacks);
    };
  }, []);

  // --- Voice transcript handling (called by voice input components) ---
  const handleVoiceTranscript = useCallback(
    (transcript: string, isFinal: boolean) => {
      const autoSend = getVoiceSetting('stt_auto_send', false);

      emitCallbacks('onVoiceFillInput', { text: transcript.trim() });

      if (isFinal && transcript.trim()) {
        if (autoSend) {
          voiceAutoSendBufferRef.current = transcript.trim();
          if (voiceAutoSendTimerRef.current) clearTimeout(voiceAutoSendTimerRef.current);
          voiceAutoSendTimerRef.current = setTimeout(() => {
            flushVoiceAutoSend();
          }, 3000);
        }
      }
    },
    [getVoiceSetting, flushVoiceAutoSend, emitCallbacks],
  );

  const handleVoiceStop = useCallback(() => {
    if (voiceAutoSendBufferRef.current) {
      setTimeout(() => flushVoiceAutoSend(), 300);
    }
  }, [flushVoiceAutoSend]);

  // --- Create card from suggestion ---
  const createCardFromSuggestion = useCallback(
    (data: { title: string; description?: string }) => {
      addCard({
        title: data.title,
        description: data.description || '',
        status: 'todo',
        workspaceId: useWorkspaceStore.getState().currentWorkspaceId || '',
        dependencies: [],
        tags: [],
        priority: 0,
      });
      showToast(`\u2705 Card created: "${data.title}"`, 'success', 3000);
    },
    [addCard, showToast],
  );

  const executeCard = useCallback(
    (cardId: string, workspaceId?: string) => {
      const sessionId = activeSessionIdRef.current;
      send('card:execute', { cardId, workspaceId, sessionId });
    },
    [send],
  );

  // ---------------------------------------------------------------------------
  // Context value (stable object via ref pattern to avoid needless re-renders)
  // ---------------------------------------------------------------------------

  const contextValue = useMemo<ChatContextValue>(
    () => ({
      sendMessage,
      sendSystemInit,
      loadHistory,
      getHistory,
      clearHistory,
      simulateStreaming,
      setActiveSessionId,
      registerCallbacks,
      getLayerState,
      handleVoiceTranscript,
      handleVoiceStop,
      createCardFromSuggestion,
      executeCard,
    }),
    [
      sendMessage,
      sendSystemInit,
      loadHistory,
      getHistory,
      clearHistory,
      simulateStreaming,
      setActiveSessionId,
      registerCallbacks,
      getLayerState,
      handleVoiceTranscript,
      handleVoiceStop,
      createCardFromSuggestion,
      executeCard,
    ],
  );

  return <ChatContext.Provider value={contextValue}>{children}</ChatContext.Provider>;
}
