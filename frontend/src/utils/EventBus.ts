import { EventHandler } from '../types';

export class EventBus {
  private handlers: Map<string, Set<EventHandler>> = new Map();

  on(event: string, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);

    // Return unsubscribe function
    return () => this.off(event, handler);
  }

  off(event: string, handler: EventHandler): void {
    const eventHandlers = this.handlers.get(event);
    if (eventHandlers) {
      eventHandlers.delete(handler);
      if (eventHandlers.size === 0) {
        this.handlers.delete(event);
      }
    }
  }

  emit(event: string, ...args: unknown[]): void {
    const eventHandlers = this.handlers.get(event);
    if (eventHandlers) {
      eventHandlers.forEach((handler) => {
        try {
          handler(...args);
        } catch (error) {
          console.error(`[EventBus] Error in handler for "${event}":`, error);
        }
      });
    }
  }

  once(event: string, handler: EventHandler): () => void {
    const wrappedHandler: EventHandler = (...args: unknown[]) => {
      this.off(event, wrappedHandler);
      handler(...args);
    };
    return this.on(event, wrappedHandler);
  }

  removeAllListeners(event?: string): void {
    if (event) {
      this.handlers.delete(event);
    } else {
      this.handlers.clear();
    }
  }

  listenerCount(event: string): number {
    return this.handlers.get(event)?.size ?? 0;
  }

  eventNames(): string[] {
    return Array.from(this.handlers.keys());
  }
}

// Global singleton
export const eventBus = new EventBus();
