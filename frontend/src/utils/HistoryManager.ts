/**
 * HistoryManager — intercepts the browser back button for in-app navigation.
 *
 * When a modal/overlay opens, call `push(key, closeFn)` to add a history entry.
 * If the user presses the hardware/browser back button, popstate fires and
 * we call the closeFn instead of navigating away from the app.
 *
 * Rules:
 *  - Each key is unique in the stack (re-pushing the same key is a no-op).
 *  - `remove(key)` is called when the overlay closes programmatically (ESC, ✕, etc.)
 *    so the stack stays in sync without triggering an extra back navigation.
 */

interface HistoryEntry {
  key: string;
  close: () => void;
}

class HistoryManager {
  private stack: HistoryEntry[] = [];
  private ignoreNextPop = false;

  constructor() {
    window.addEventListener('popstate', this.onPopState);
  }

  /** Push a history entry for an overlay. No-op if `key` is already in the stack. */
  push(key: string, closeFn: () => void): void {
    if (this.stack.some((e) => e.key === key)) return;
    this.stack.push({ key, close: closeFn });
    window.history.pushState({ overlay: key }, '');
  }

  /**
   * Remove an entry by key (called when the overlay is closed by the app, not by back button).
   * Goes back in history to keep the browser history length in sync.
   */
  remove(key: string): void {
    const idx = this.stack.findIndex((e) => e.key === key);
    if (idx === -1) return;
    this.stack.splice(idx, 1);
    // Go back to consume the history entry we pushed, but ignore the resulting popstate
    this.ignoreNextPop = true;
    window.history.back();
  }

  /** Check if a key is currently in the stack. */
  has(key: string): boolean {
    return this.stack.some((e) => e.key === key);
  }

  private onPopState = (_e: PopStateEvent): void => {
    if (this.ignoreNextPop) {
      this.ignoreNextPop = false;
      return;
    }
    // Pop the most recent overlay and close it
    const entry = this.stack.pop();
    if (entry) {
      entry.close();
    }
  };
}

export const historyManager = new HistoryManager();
