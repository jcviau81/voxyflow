import { Message } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, STREAMING_SAFETY_TIMEOUT, AGENT_PERSONAS, SYSTEM_PROJECT_ID } from '../utils/constants';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { sttService } from './SttService';
import { generateId, sleep } from '../utils/helpers';
import { ModelStatusBar } from '../components/Navigation/ModelStatusBar';
// TTS auto-play is handled centrally by ChatWindow (via MESSAGE_RECEIVED / MESSAGE_STREAM_END events)

export class ChatService {
  private streamingMessages: Map<string, { content: string; messageId: string }> = new Map();
  /** Safety timers that force-end streaming after STREAMING_SAFETY_TIMEOUT */
  private streamingTimers: Map<string, ReturnType<typeof setTimeout>> = new Map();
  private unsubscribers: (() => void)[] = [];
  /** Active session ID for general chat, set by ChatWindow */
  activeSessionId: string | undefined;
  /** Debounce timer for voice auto-send — waits for silence before sending */
  private voiceAutoSendTimer: ReturnType<typeof setTimeout> | null = null;
  private voiceAutoSendBuffer = '';

  constructor() {
    this.setupHandlers();
  }

  private setupHandlers(): void {
    // Handle incoming chat responses
    this.unsubscribers.push(
      apiClient.on('chat:response', (payload) => {
        const { messageId, content, streaming, done, sessionId } = payload as {
          messageId: string;
          content: string;
          streaming: boolean;
          done: boolean;
          sessionId?: string;
        };
        if (!sessionId) {
          console.warn('[ChatService] chat:response arrived without sessionId — dropping message', { messageId });
          return;
        }

        if (streaming && !done) {
          // Streaming chunk — accumulate
          this.handleStreamingChunk(messageId, content, sessionId);
        } else if (done && this.streamingMessages.has(messageId)) {
          // Final chunk of an in-progress stream
          this.handleStreamComplete(messageId, content as string);
        } else {
          // Non-streaming full response (or done without prior stream state)
          this.handleFullResponse(content, sessionId);
        }
      })
    );

    // Handle enrichment messages (Layer 2 — Deep thinking)
    this.unsubscribers.push(
      apiClient.on('chat:enrichment', (payload) => {
        const { messageId, content, model, action, sessionId } = payload as {
          messageId: string;
          content: string;
          model: string;
          action: string;
          done: boolean;
          sessionId?: string;
        };

        if (!sessionId) {
          console.warn('[ChatService] chat:enrichment arrived without sessionId — dropping message', { messageId });
          return;
        }

        const message = appState.addMessage({
          role: 'assistant',
          content,
          enrichment: true,
          enrichmentAction: action as 'enrich' | 'correct',
          model,
          sessionId,
          projectId: appState.get('currentProjectId') || SYSTEM_PROJECT_ID,
        });
        eventBus.emit(EVENTS.MESSAGE_ENRICHMENT, message);
      })
    );

    // Handle model status updates
    this.unsubscribers.push(
      apiClient.on('model:status', (payload) => {
        const { model, state } = payload as { model: string; state: string };
        eventBus.emit(EVENTS.MODEL_STATUS, { model, state });
      })
    );

    // Handle tool execution results from AI
    this.unsubscribers.push(
      apiClient.on('tool:result', (payload) => {
        const { tool, success, data, error, ui_action } = payload as {
          tool: string;
          success: boolean;
          data: Record<string, unknown> | null;
          error: string | null;
          ui_action: string | null;
        };

        if (success && ui_action) {
          this.handleToolUiAction(ui_action, data);
        }

        if (success) {
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: `🔧 ${tool}: Done`,
            type: 'success',
            duration: 3000,
          });
        } else {
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: `🔧 ${tool} failed: ${error}`,
            type: 'error',
            duration: 5000,
          });
        }
      })
    );

    // Handle Deep Worker task events (event bus architecture)
    this.unsubscribers.push(
      apiClient.on('task:started', (payload) => {
        eventBus.emit(EVENTS.TASK_STARTED, payload);
      })
    );
    this.unsubscribers.push(
      apiClient.on('task:progress', (payload) => {
        eventBus.emit(EVENTS.TASK_PROGRESS, payload);
      })
    );
    this.unsubscribers.push(
      apiClient.on('task:completed', (payload) => {
        const { intent, summary, result, success, taskId, sessionId } = payload as {
          intent: string;
          summary: string;
          result: string;
          success: boolean;
          taskId: string;
          sessionId?: string;
        };
        eventBus.emit(EVENTS.TASK_COMPLETED, payload);

        // Inject worker result as a chat message so the user sees it
        if (result && result.trim()) {
          const resultContent = success
            ? result
            : `⚠️ Task failed (${intent}): ${result}`;

          const message = appState.addMessage({
            role: 'assistant',
            content: resultContent,
            model: 'worker',
            sessionId: sessionId || this.activeSessionId,
            isWorkerResult: true,
          });
          eventBus.emit(EVENTS.MESSAGE_RECEIVED, message);
          // TTS handled by ChatWindow via MESSAGE_RECEIVED listener
        }

        // Toast as secondary notification
        if (success) {
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: `✅ ${intent}: ${summary.substring(0, 50)}`,
            type: 'success',
            duration: 4000,
          });
        } else {
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: `❌ ${intent} failed`,
            type: 'error',
            duration: 5000,
          });
        }
      })
    );

    // Handle Board Execution WS events → forward to EventBus for KanbanBoard
    this.unsubscribers.push(
      apiClient.on('kanban:execute:card:start', (payload) => {
        eventBus.emit(EVENTS.BOARD_EXECUTE_CARD_START, payload);
      })
    );
    this.unsubscribers.push(
      apiClient.on('kanban:execute:card:done', (payload) => {
        eventBus.emit(EVENTS.BOARD_EXECUTE_CARD_DONE, payload);
        // Refresh kanban to show card moved to done
        eventBus.emit(EVENTS.CARD_UPDATED, payload);
      })
    );
    this.unsubscribers.push(
      apiClient.on('kanban:execute:complete', (payload) => {
        eventBus.emit(EVENTS.BOARD_EXECUTE_COMPLETE, payload);
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `Board execution complete — ${(payload as Record<string, unknown>).completed} cards done`,
          type: 'success',
          duration: 5000,
        });
      })
    );
    this.unsubscribers.push(
      apiClient.on('kanban:execute:cancelled', (payload) => {
        eventBus.emit(EVENTS.BOARD_EXECUTE_CANCELLED, payload);
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: 'Board execution cancelled',
          type: 'warning',
          duration: 3000,
        });
      })
    );
    this.unsubscribers.push(
      apiClient.on('kanban:execute:error', (payload) => {
        eventBus.emit(EVENTS.BOARD_EXECUTE_ERROR, payload);
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `Board execution error: ${(payload as Record<string, unknown>).error}`,
          type: 'error',
          duration: 5000,
        });
      })
    );

    // Handle card suggestions (Layer 3 — Analyzer) → route to Opportunities Panel
    this.unsubscribers.push(
      apiClient.on('card:suggestion', (payload) => {
        const { title, description, projectId, agentType, agentName } = payload as {
          title: string;
          description: string;
          projectId: string;
          agentType: string;
          agentName: string;
        };

        const suggestion = {
          id: generateId(),
          title,
          description,
          agentType,
          agentName,
          agentEmoji: this.getAgentEmoji(agentType),
          timestamp: Date.now(),
        };
        eventBus.emit(EVENTS.CARD_SUGGESTION, suggestion);

        // Brief toast notification as secondary alert
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `💡 New suggestion: "${title}"`,
          type: 'info',
          duration: 3000,
        });
      })
    );

    // Handle CREATE_CARD_FROM_SUGGESTION from Opportunities Panel
    this.unsubscribers.push(
      eventBus.on(EVENTS.CREATE_CARD_FROM_SUGGESTION, (data: unknown) => {
        const { title, description } = data as {
          title: string;
          description?: string;
          agentType?: string;
          agentName?: string;
        };
        appState.addCard({
          title,
          description: description || '',
          status: 'idea',
          projectId: appState.get('currentProjectId') || '',
          dependencies: [],
          tags: [],
          priority: 0,
          assignedAgent: undefined,
        });
        eventBus.emit(EVENTS.TOAST_SHOW, {
          message: `✅ Card created: "${title}"`,
          type: 'success',
          duration: 3000,
        });
      })
    );

    // Handle voice transcripts — SttService now sends the full accumulated text.
    // On isFinal: start/reset a 3s silence timer. When it fires, auto-send the message.
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_TRANSCRIPT, (result: unknown) => {
        const { transcript, isFinal } = result as { transcript: string; isFinal: boolean };
        const autoSend = this.getVoiceSetting('stt_auto_send', false);

        // Always fill the textarea with the current combined text
        eventBus.emit('voice:fill-input', { text: transcript.trim() });

        if (isFinal && transcript.trim()) {
          if (autoSend) {
            // Store the full accumulated transcript from SttService
            this.voiceAutoSendBuffer = transcript.trim();
            if (this.voiceAutoSendTimer) clearTimeout(this.voiceAutoSendTimer);
            this.voiceAutoSendTimer = setTimeout(() => {
              this.flushVoiceAutoSend();
            }, 3000);
          }
        }
      })
    );

    // When the user manually stops recording (tap-to-stop), flush buffer immediately
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_STOP, () => {
        if (this.voiceAutoSendBuffer) {
          // Small delay to catch any last isFinal event that arrives right after stop
          setTimeout(() => this.flushVoiceAutoSend(), 300);
        }
      })
    );

    // FIX: When WebSocket disconnects, force-end all streaming messages.
    // Without this, a disconnect during streaming leaves the blinking cursor forever.
    this.unsubscribers.push(
      eventBus.on(EVENTS.WS_DISCONNECTED, () => {
        this.forceEndAllStreaming();
      })
    );
  }

  sendMessage(content: string, projectId?: string, cardId?: string, sessionId?: string): Message {
    const message = appState.addMessage({
      role: 'user',
      content,
      projectId: projectId || appState.get('currentProjectId') || undefined,
      cardId,
      sessionId,
    });

    // Include layer toggle state so backend can skip disabled layers
    const layers = ModelStatusBar.getStoredLayerState();

    // Determine chat context level for backend isolation
    // Main chat now maps to the system project (system-main)
    const currentProjectId = message.projectId || appState.get('currentProjectId') || SYSTEM_PROJECT_ID;
    const currentCardId = message.cardId || appState.get('selectedCardId');
    let chatLevel: 'general' | 'project' | 'card' = 'general';
    if (currentCardId) {
      chatLevel = 'card';
    } else if (currentProjectId && currentProjectId !== SYSTEM_PROJECT_ID) {
      chatLevel = 'project';
    }
    // Note: chatLevel 'general' is kept for backward compat — backend maps it to system-main

    apiClient.send('chat:message', {
      content,
      projectId: currentProjectId,
      cardId: currentCardId,
      messageId: message.id,
      chatLevel,
      layers,
      sessionId: sessionId || undefined,
    });

    eventBus.emit(EVENTS.MESSAGE_SENT, message);
    return message;
  }

  /**
   * Send a hidden system context message — triggers Voxy response but shows NO user bubble.
   * Used by Welcome Flow quick actions.
   */
  sendSystemInit(contextHint: string, projectId?: string, cardId?: string, sessionId?: string): void {
    const layers = ModelStatusBar.getStoredLayerState();
    const currentProjectId = projectId || appState.get('currentProjectId') || SYSTEM_PROJECT_ID;
    const currentCardId = cardId || appState.get('selectedCardId') || undefined;
    let chatLevel: 'general' | 'project' | 'card' = 'general';
    if (currentCardId) chatLevel = 'card';
    else if (currentProjectId && currentProjectId !== SYSTEM_PROJECT_ID) chatLevel = 'project';

    apiClient.send('chat:message', {
      content: contextHint,
      projectId: currentProjectId,
      cardId: currentCardId,
      chatLevel,
      layers,
      sessionId: sessionId || this.activeSessionId || undefined,
      systemInit: true,  // Backend knows not to persist this as a user message
    });
  }

  private handleStreamingChunk(streamId: string, chunk: string, sessionId?: string): void {
    let stream = this.streamingMessages.get(streamId);

    if (!stream) {
      // Create new streaming message — include projectId so messages survive reload filtering
      const message = appState.addMessage({
        role: 'assistant',
        content: '',
        streaming: true,
        sessionId,
        projectId: appState.get('currentProjectId') || SYSTEM_PROJECT_ID,
      });
      stream = { content: '', messageId: message.id };
      this.streamingMessages.set(streamId, stream);
    }

    stream.content += chunk;
    appState.updateMessage(stream.messageId, {
      content: stream.content,
      streaming: true,
    });

    eventBus.emit(EVENTS.MESSAGE_STREAMING, {
      messageId: stream.messageId,
      content: stream.content,
      chunk,
    });

    // FIX: Reset safety timeout on each chunk — if no chunk arrives for
    // STREAMING_SAFETY_TIMEOUT, force-end this stream to prevent stuck indicators.
    this.resetStreamingTimer(streamId);
  }

  private handleStreamComplete(streamId: string, finalContent: string): void {
    const stream = this.streamingMessages.get(streamId);
    if (stream) {
      const content = finalContent || stream.content;
      appState.updateMessage(stream.messageId, {
        content,
        streaming: false,
      });
      this.streamingMessages.delete(streamId);
      this.clearStreamingTimer(streamId);

      eventBus.emit(EVENTS.MESSAGE_STREAM_END, {
        messageId: stream.messageId,
        content,
      });
      // TTS handled by ChatWindow via MESSAGE_STREAM_END listener
    }
  }

  private handleFullResponse(content: string, sessionId?: string): void {
    const message = appState.addMessage({
      role: 'assistant',
      content: content as string,
      sessionId,
      projectId: appState.get('currentProjectId') || SYSTEM_PROJECT_ID,
    });
    eventBus.emit(EVENTS.MESSAGE_RECEIVED, message);
    // TTS handled by ChatWindow via MESSAGE_RECEIVED listener
  }

  /**
   * Simulate streaming effect for a complete message (character by character)
   */
  async simulateStreaming(messageId: string, fullContent: string): Promise<void> {
    let displayed = '';
    for (const char of fullContent) {
      displayed += char;
      appState.updateMessage(messageId, { content: displayed, streaming: true });
      eventBus.emit(EVENTS.MESSAGE_STREAMING, {
        messageId,
        content: displayed,
        chunk: char,
      });
      await sleep(STREAMING_CHAR_DELAY);
    }
    appState.updateMessage(messageId, { content: fullContent, streaming: false });
    eventBus.emit(EVENTS.MESSAGE_STREAM_END, { messageId, content: fullContent });
  }

  /**
   * Load chat history from the backend API and inject into AppState.
   * Returns the loaded messages (empty array on failure).
   */
  async loadHistory(
    chatId: string,
    projectId?: string,
    cardId?: string,
    sessionId?: string,
    replaceSession = false,
  ): Promise<Message[]> {
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

      // Convert backend format → frontend Message format
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
        }));

      if (converted.length > 0) {
        if (replaceSession) {
          // Replace stale in-memory messages for this specific session so a page
          // refresh always shows the authoritative backend state.
          appState.replaceSessionMessages(converted, sessionId, projectId, cardId);
        } else {
          appState.setMessages(converted);
        }
      }
      return converted;
    } catch (e) {
      console.warn('[ChatService] Failed to load history:', e);
      return [];
    }
  }

  getHistory(projectId?: string, sessionId?: string): Message[] {
    return appState.getMessages(projectId, sessionId);
  }

  clearHistory(): void {
    appState.clearMessages();
  }

  private handleToolUiAction(uiAction: string, data: Record<string, unknown> | null): void {
    switch (uiAction) {
      case 'open_project_tab':
        if (data?.id || data?.project_id) {
          eventBus.emit(EVENTS.TAB_OPEN, { projectId: data.id || data.project_id });
        }
        break;
      case 'refresh_project':
        eventBus.emit(EVENTS.PROJECT_UPDATED, data);
        break;
      case 'close_project_tab':
        if (data?.deleted_id) {
          eventBus.emit(EVENTS.TAB_CLOSE, { projectId: data.deleted_id });
          eventBus.emit(EVENTS.PROJECT_DELETED, data);
        }
        break;
      case 'refresh_kanban':
        eventBus.emit(EVENTS.CARD_UPDATED, data);
        break;
      case 'open_card':
        if (data?.card_id) {
          eventBus.emit(EVENTS.CARD_SELECTED, { cardId: data.card_id });
        }
        break;
      case 'show_kanban':
        eventBus.emit(EVENTS.VIEW_CHANGE, { view: 'kanban' });
        break;
      case 'show_chat':
        eventBus.emit(EVENTS.VIEW_CHANGE, { view: 'chat' });
        break;
    }
  }

  /** Flush the accumulated voice auto-send buffer and send the message */
  private flushVoiceAutoSend(): void {
    if (this.voiceAutoSendTimer) {
      clearTimeout(this.voiceAutoSendTimer);
      this.voiceAutoSendTimer = null;
    }
    if (this.voiceAutoSendBuffer) {
      this.sendMessage(this.voiceAutoSendBuffer, undefined, undefined, this.activeSessionId);
      this.voiceAutoSendBuffer = '';
      // Clear SttService's finalized buffer so next recording starts fresh
      sttService.clearBuffer();
      // Clear the textarea and transcript display
      eventBus.emit('voice:fill-input', { text: '' });
      eventBus.emit('voice:buffer-update', { text: '' });
      // Stop recording for a clean cycle: tap → speak → auto-send → mic stops → tap again
      eventBus.emit('voice:recording-stop');
    }
  }

  /** Read a single voice setting from localStorage */
  private getVoiceSetting<T>(key: string, defaultValue: T): T {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const val = settings?.voice?.[key];
        if (val !== undefined) return val as T;
      }
    } catch { /* ignore */ }
    return defaultValue;
  }

  private getAgentEmoji(agentType?: string): string {
    if (!agentType) return '🤖';
    const persona = AGENT_PERSONAS[agentType.toLowerCase()];
    return persona?.emoji || '🤖';
  }

  /**
   * FIX: Force-end all in-progress streaming messages.
   * Called on WS disconnect to prevent stuck blinking cursors.
   */
  private forceEndAllStreaming(): void {
    if (this.streamingMessages.size === 0) return;
    console.log(`[ChatService] Force-ending ${this.streamingMessages.size} streaming message(s)`);

    for (const [streamId, stream] of this.streamingMessages) {
      appState.updateMessage(stream.messageId, { streaming: false });
      eventBus.emit(EVENTS.MESSAGE_STREAM_END, {
        messageId: stream.messageId,
        content: stream.content,
      });
      this.clearStreamingTimer(streamId);
    }
    this.streamingMessages.clear();
  }

  /** Reset the safety timeout for a streaming message */
  private resetStreamingTimer(streamId: string): void {
    this.clearStreamingTimer(streamId);
    this.streamingTimers.set(streamId, setTimeout(() => {
      console.warn(`[ChatService] Streaming safety timeout for ${streamId}`);
      this.handleStreamComplete(streamId, '');
    }, STREAMING_SAFETY_TIMEOUT));
  }

  private clearStreamingTimer(streamId: string): void {
    const timer = this.streamingTimers.get(streamId);
    if (timer) {
      clearTimeout(timer);
      this.streamingTimers.delete(streamId);
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.forceEndAllStreaming();
    this.streamingMessages.clear();
  }
}

export const chatService = new ChatService();
