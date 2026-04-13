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
import { useProjectStore } from '../stores/useProjectStore';
import { useCardStore } from '../stores/useCardStore';
import { useToastStore } from '../stores/useToastStore';
import { generateId } from '../lib/utils';
import {
  SYSTEM_PROJECT_ID,
  STREAMING_SAFETY_TIMEOUT,
  STREAMING_CHAR_DELAY,
  AGENT_PERSONAS,
} from '../lib/constants';
import { useQueryClient } from '@tanstack/react-query';
import type { Message } from '../types';
import { cardKeys, mapRawCard } from '../hooks/api/useCards';

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
    projectId?: string,
    cardId?: string,
    sessionId?: string,
  ) => Message;
  /** Send a hidden system-init message (no user bubble) */
  sendSystemInit: (
    contextHint: string,
    projectId?: string,
    cardId?: string,
    sessionId?: string,
  ) => void;
  /** Load chat history from backend API */
  loadHistory: (
    chatId: string,
    projectId?: string,
    cardId?: string,
    sessionId?: string,
    replaceSession?: boolean,
  ) => Promise<Message[]>;
  /** Get messages from the local store */
  getHistory: (projectId?: string, sessionId?: string) => Message[];
  /** Clear all local messages */
  clearHistory: () => void;
  /** Simulate character-by-character streaming for a message */
  simulateStreaming: (messageId: string, fullContent: string) => Promise<void>;
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
  executeCard: (cardId: string, projectId?: string) => void;
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
  const messageStore = useMessageStore();
  const projectStore = useProjectStore();
  const cardStore = useCardStore();
  const showToast = useToastStore((s) => s.showToast);

  // Refs for mutable state that must not trigger re-renders
  const activeSessionIdRef = useRef<string | undefined>(undefined);
  const streamingMessagesRef = useRef<Map<string, StreamState>>(new Map());
  const streamingTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  const voiceAutoSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceAutoSendBufferRef = useRef('');
  const callbacksRef = useRef<Set<ChatCallbacks>>(new Set());

  // Stable ref for sendMessage — lets flushVoiceAutoSend use the same code path
  // as manual send, without creating a dependency cycle.
  const sendMessageRef = useRef<ChatContextValue['sendMessage'] | null>(null);

  // Stable refs for store methods (avoid stale closures)
  const messageStoreRef = useRef(messageStore);
  messageStoreRef.current = messageStore;
  const projectStoreRef = useRef(projectStore);
  projectStoreRef.current = projectStore;

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

  const projectIdFromSession = useCallback((sessionId?: string): string => {
    if (sessionId?.startsWith('project:')) {
      const projectId = sessionId.split(':')[1];
      if (projectId) return projectId;
    }
    return SYSTEM_PROJECT_ID;
  }, []);

  const getProjectIdFromSession = useCallback((sessionId?: string): string => {
    if (!sessionId) return SYSTEM_PROJECT_ID;
    if (sessionId.startsWith('project:')) return sessionId.slice('project:'.length);
    return SYSTEM_PROJECT_ID;
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
        clearStreamingTimer(streamId);

        emitCallbacks('onMessageStreamEnd', { messageId: stream.messageId, content });
      }
    },
    [clearStreamingTimer, emitCallbacks],
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
      clearStreamingTimer(streamId);
    }
    streamingMessagesRef.current.clear();
  }, [clearStreamingTimer, emitCallbacks]);

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
          projectId: getProjectIdFromSession(sessionId),
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
    [getProjectIdFromSession, resetStreamingTimer, emitCallbacks],
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
        projectId: getProjectIdFromSession(sessionId),
      });
      emitCallbacks('onMessageReceived', message);
    },
    [getProjectIdFromSession, emitCallbacks],
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
        const { messageId, content, streaming, done, sessionId, model } = payload as {
          messageId: string;
          content: string;
          streaming: boolean;
          done: boolean;
          sessionId?: string;
          model?: string;
        };
        // Final streaming chunk may arrive without sessionId — allow it
        // through when we already track the messageId in streamingMessagesRef.
        if (!sessionId && !(done && streamingMessagesRef.current.has(messageId))) {
          console.warn('[ChatProvider] chat:response without sessionId — dropping', { messageId });
          return;
        }

        if (streaming && !done) {
          handleStreamingChunk(messageId, content, sessionId!, model);
        } else if (done && streamingMessagesRef.current.has(messageId)) {
          handleStreamComplete(messageId, content);
        } else {
          handleFullResponse(content, sessionId!);
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
          projectId: projectIdFromSession(sessionId),
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
        const { intent, summary, result, success, sessionId, projectId, cardId } = payload as {
          intent: string;
          summary: string;
          result: string;
          success: boolean;
          taskId: string;
          sessionId?: string;
          projectId?: string;
          cardId?: string;
        };
        emitCallbacks('onTaskCompleted', payload);

        // Inject worker result as a chat message
        if (result && result.trim()) {
          const resultContent = success
            ? result
            : `\u26A0\uFE0F Task failed (${intent}): ${result}`;

          const message = messageStoreRef.current.addMessage({
            role: 'assistant',
            content: resultContent,
            model: 'worker',
            projectId: projectId || getProjectIdFromSession(sessionId),
            sessionId: sessionId || activeSessionIdRef.current,
            cardId: cardId || undefined,
            isWorkerResult: true,
          });
          emitCallbacks('onMessageReceived', message);
        }

        if (success) {
          showToast(`\u2705 ${intent}: ${summary.substring(0, 50)}`, 'success', 4000);
        } else {
          showToast(`\u274C ${intent} failed`, 'error', 5000);
        }
      }),
    );
    unsubs.push(
      subscribe('task:cancelled', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskCancelled', payload);
        showToast('Task cancelled', 'info', 3000);
      }),
    );
    unsubs.push(
      subscribe('task:timeout', (payload) => {
        normalizeTaskId(payload);
        emitCallbacks('onTaskTimeout', payload);
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
        const { projectId, cardId } = payload as { projectId?: string; cardId?: string };
        if (cardId) {
          void queryClient.invalidateQueries({ queryKey: cardKeys.detail(cardId) });
          // Fetch updated card and upsert into Zustand so open modals update in real-time
          fetch(`/api/cards/${cardId}`)
            .then((r) => (r.ok ? r.json() : null))
            .then((raw) => {
              if (raw) useCardStore.getState().upsertCard(mapRawCard(raw as Record<string, unknown>));
            })
            .catch(() => {});
        }
        if (projectId) {
          void queryClient.invalidateQueries({ queryKey: cardKeys.byProject(projectId) });
        }
      }),
    );

    // --- reminder:fired — show toast when a reminder job fires ---
    unsubs.push(
      subscribe('reminder:fired', (payload) => {
        const { jobName, message } = payload as { jobName?: string; message?: string };
        showToast(`${jobName || 'Reminder'}: ${message || ''}`, 'info', 5000);
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
                  role: string;
                  content: string;
                  timestamp?: string;
                  model?: string;
                  type?: string;
                }> = data.messages;

                const converted: Message[] = backendMessages
                  .filter((m) => m.role === 'user' || m.role === 'assistant')
                  .filter((m) => m.type !== 'enrichment')
                  .map((m) => ({
                    id: generateId(),
                    role: m.role as 'user' | 'assistant',
                    content: m.content || '',
                    timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
                    sessionId,
                    streaming: false,
                    model: m.model,
                    isWorkerResult: m.type === 'worker_result' ? true : undefined,
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
    projectIdFromSession,
    getProjectIdFromSession,
    getAgentEmoji,
    emitCallbacks,
    queryClient,
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
      projectId?: string,
      cardId?: string,
      sessionId?: string,
    ): Message => {
      const store = messageStoreRef.current;
      const pStore = projectStoreRef.current;

      const message = store.addMessage({
        role: 'user',
        content,
        projectId: projectId || undefined,
        cardId,
        sessionId,
      });

      const layers = getLayerState();
      const currentProjectId = message.projectId || SYSTEM_PROJECT_ID;
      const currentCardId = message.cardId || pStore.selectedCardId;
      let chatLevel: 'general' | 'project' | 'card' = 'general';
      if (currentCardId) {
        chatLevel = 'card';
      } else if (currentProjectId && currentProjectId !== SYSTEM_PROJECT_ID) {
        chatLevel = 'project';
      }

      send('chat:message', {
        content,
        projectId: currentProjectId,
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

  // Keep sendMessageRef in sync so flushVoiceAutoSend can use it
  sendMessageRef.current = sendMessage;

  const sendSystemInit = useCallback(
    (
      contextHint: string,
      projectId?: string,
      cardId?: string,
      sessionId?: string,
    ) => {
      const layers = getLayerState();
      const currentProjectId = projectId || SYSTEM_PROJECT_ID;
      const currentCardId = cardId || undefined;
      let chatLevel: 'general' | 'project' | 'card' = 'general';
      if (currentCardId) chatLevel = 'card';
      else if (currentProjectId && currentProjectId !== SYSTEM_PROJECT_ID) chatLevel = 'project';

      const resolvedSessionId = sessionId || activeSessionIdRef.current || undefined;
      send('chat:message', {
        content: contextHint,
        projectId: currentProjectId,
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
      projectId?: string,
      cardId?: string,
      sessionId?: string,
      replaceSession = false,
    ): Promise<Message[]> => {
      try {
        const resp = await fetch(`/api/sessions/${chatId}?limit=50`);
        if (!resp.ok) return [];
        const data = await resp.json();
        const backendMessages: Array<{
          role: string;
          content: string;
          timestamp?: string;
          model?: string;
          type?: string;
        }> = data.messages || [];

        const converted: Message[] = backendMessages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .filter((m) => m.type !== 'enrichment')
          .map((m) => ({
            id: generateId(),
            role: m.role as 'user' | 'assistant',
            content: m.content || '',
            timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
            projectId: projectId || undefined,
            cardId: cardId || undefined,
            sessionId: sessionId || undefined,
            streaming: false,
            model: m.model,
            isWorkerResult: m.type === 'worker_result' ? true : undefined,
          }));

        if (converted.length > 0) {
          const store = messageStoreRef.current;
          if (replaceSession) {
            store.replaceSessionMessages(converted, sessionId, projectId, cardId);
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
    [],
  );

  const getHistory = useCallback(
    (projectId?: string, sessionId?: string): Message[] => {
      return messageStoreRef.current.getMessages(projectId, sessionId);
    },
    [],
  );

  const clearHistory = useCallback(() => {
    messageStoreRef.current.clearMessages();
  }, []);

  const simulateStreaming = useCallback(
    async (messageId: string, fullContent: string): Promise<void> => {
      let displayed = '';
      for (const char of fullContent) {
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
      const pStore = projectStoreRef.current;
      cardStore.addCard({
        title: data.title,
        description: data.description || '',
        status: 'todo',
        projectId: pStore.currentProjectId || '',
        dependencies: [],
        tags: [],
        priority: 0,
      });
      showToast(`\u2705 Card created: "${data.title}"`, 'success', 3000);
    },
    [cardStore, showToast],
  );

  const executeCard = useCallback(
    (cardId: string, projectId?: string) => {
      const sessionId = activeSessionIdRef.current;
      send('card:execute', { cardId, projectId, sessionId });
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
