type EventHandler = (...args: unknown[]) => void;

export class EventBus {
  private handlers: Map<string, Set<EventHandler>> = new Map();

  on(event: string, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);
    return () => this.off(event, handler);
  }

  off(event: string, handler: EventHandler): void {
    const set = this.handlers.get(event);
    if (set) {
      set.delete(handler);
      if (set.size === 0) this.handlers.delete(event);
    }
  }

  emit(event: string, ...args: unknown[]): void {
    const set = this.handlers.get(event);
    if (set) {
      set.forEach((handler) => {
        try {
          handler(...args);
        } catch (err) {
          console.error(`[EventBus] Error in handler for "${event}":`, err);
        }
      });
    }
  }

  once(event: string, handler: EventHandler): () => void {
    const wrapped: EventHandler = (...args: unknown[]) => {
      this.off(event, wrapped);
      handler(...args);
    };
    return this.on(event, wrapped);
  }
}

export const eventBus = new EventBus();
