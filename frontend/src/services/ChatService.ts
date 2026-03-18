import { Message } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, STREAMING_CHAR_DELAY, AGENT_PERSONAS } from '../utils/constants';
import { appState } from '../state/AppState';
import { apiClient } from './ApiClient';
import { generateId, sleep } from '../utils/helpers';

export class ChatService {
  private streamingMessages: Map<string, { content: string; messageId: string }> = new Map();
  private unsubscribers: (() => void)[] = [];

  constructor() {
    this.setupHandlers();
  }

  private setupHandlers(): void {
    // Handle incoming chat responses
    this.unsubscribers.push(
      apiClient.on('chat:response', (payload) => {
        const { messageId, content, streaming, done } = payload as {
          messageId: string;
          content: string;
          streaming: boolean;
          done: boolean;
        };

        if (streaming && !done) {
          // Streaming chunk — accumulate
          this.handleStreamingChunk(messageId, content);
        } else if (done && this.streamingMessages.has(messageId)) {
          // Final chunk of an in-progress stream
          this.handleStreamComplete(messageId, content as string);
        } else {
          // Non-streaming full response (or done without prior stream state)
          this.handleFullResponse(content);
        }
      })
    );

    // Handle enrichment messages (Layer 2 — Opus deep thinking)
    this.unsubscribers.push(
      apiClient.on('chat:enrichment', (payload) => {
        const { messageId, content, model, action } = payload as {
          messageId: string;
          content: string;
          model: string;
          action: string;
          done: boolean;
        };

        const message = appState.addMessage({
          role: 'assistant',
          content,
          enrichment: true,
          enrichmentAction: action as 'enrich' | 'correct',
          model,
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
          this.sendMessage(transcript.trim());
        }
      })
    );
  }

  sendMessage(content: string, projectId?: string, cardId?: string): Message {
    const message = appState.addMessage({
      role: 'user',
      content,
      projectId: projectId || appState.get('currentProjectId') || undefined,
      cardId,
    });

    apiClient.send('chat:message', {
      content,
      projectId: message.projectId,
      cardId: message.cardId,
      messageId: message.id,
    });

    eventBus.emit(EVENTS.MESSAGE_SENT, message);
    return message;
  }

  private handleStreamingChunk(streamId: string, chunk: string): void {
    let stream = this.streamingMessages.get(streamId);

    if (!stream) {
      // Create new streaming message
      const message = appState.addMessage({
        role: 'assistant',
        content: '',
        streaming: true,
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

  private handleFullResponse(content: string): void {
    const message = appState.addMessage({
      role: 'assistant',
      content: content as string,
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

  getHistory(projectId?: string): Message[] {
    return appState.getMessages(projectId);
  }

  clearHistory(): void {
    appState.clearMessages();
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
