import { Message } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, AGENT_PERSONAS } from '../utils/constants';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { generateId, sleep } from '../utils/helpers';
import { ModelStatusBar } from '../components/Navigation/ModelStatusBar';

export class ChatService {
  private streamingMessages: Map<string, { content: string; messageId: string }> = new Map();
  private unsubscribers: (() => void)[] = [];
  /** Active session ID for general chat, set by ChatWindow */
  activeSessionId: string | undefined;

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
        const responseSessionId = sessionId || this.activeSessionId;

        if (streaming && !done) {
          // Streaming chunk — accumulate
          this.handleStreamingChunk(messageId, content, responseSessionId);
        } else if (done && this.streamingMessages.has(messageId)) {
          // Final chunk of an in-progress stream
          this.handleStreamComplete(messageId, content as string);
        } else {
          // Non-streaming full response (or done without prior stream state)
          this.handleFullResponse(content, responseSessionId);
        }
      })
    );

    // Handle enrichment messages (Layer 2 — Opus deep thinking)
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

        const message = appState.addMessage({
          role: 'assistant',
          content,
          enrichment: true,
          enrichmentAction: action as 'enrich' | 'correct',
          model,
          sessionId: sessionId || this.activeSessionId,
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
          data: any;
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
          id: crypto.randomUUID(),
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

    // Handle voice transcripts
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_TRANSCRIPT, (result: unknown) => {
        const { transcript, isFinal } = result as { transcript: string; isFinal: boolean };
        if (isFinal && transcript.trim()) {
          this.sendMessage(transcript.trim(), undefined, undefined, this.activeSessionId);
        }
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
    const currentProjectId = message.projectId || appState.get('currentProjectId');
    const currentCardId = message.cardId || appState.get('selectedCardId');
    let chatLevel: 'general' | 'project' | 'card' = 'general';
    if (currentCardId) {
      chatLevel = 'card';
    } else if (currentProjectId) {
      chatLevel = 'project';
    }

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

  private handleStreamingChunk(streamId: string, chunk: string, sessionId?: string): void {
    let stream = this.streamingMessages.get(streamId);

    if (!stream) {
      // Create new streaming message
      const message = appState.addMessage({
        role: 'assistant',
        content: '',
        streaming: true,
        sessionId: sessionId || this.activeSessionId,
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

      eventBus.emit(EVENTS.MESSAGE_STREAM_END, {
        messageId: stream.messageId,
        content,
      });
    }
  }

  private handleFullResponse(content: string, sessionId?: string): void {
    const message = appState.addMessage({
      role: 'assistant',
      content: content as string,
      sessionId: sessionId || this.activeSessionId,
    });
    eventBus.emit(EVENTS.MESSAGE_RECEIVED, message);
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

  getHistory(projectId?: string, sessionId?: string): Message[] {
    return appState.getMessages(projectId, sessionId);
  }

  clearHistory(): void {
    appState.clearMessages();
  }

  private handleToolUiAction(uiAction: string, data: any): void {
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

  private getAgentEmoji(agentType?: string): string {
    if (!agentType) return '🤖';
    const persona = AGENT_PERSONAS[agentType.toLowerCase()];
    return persona?.emoji || '🤖';
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.streamingMessages.clear();
  }
}

export const chatService = new ChatService();
