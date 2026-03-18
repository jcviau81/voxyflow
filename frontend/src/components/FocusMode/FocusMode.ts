import { Card } from '../../types';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { apiClient } from '../../services/ApiClient';
import { chatService } from '../../services/ChatService';

interface FocusModeOptions {
  card: Card;
  onExit: () => void;
}

const DEFAULT_DURATION_MINUTES = 25;
const TOTAL_SESSIONS = 4;

export class FocusMode {
  private overlay: HTMLElement;
  private card: Card;
  private onExit: () => void;

  // Timer state
  private timerInterval: ReturnType<typeof setInterval> | null = null;
  private remainingSeconds: number;
  private isRunning = false;
  private currentSession = 1;
  private timerDisplay: HTMLElement | null = null;
  private sessionLabel: HTMLElement | null = null;
  private startPauseBtn: HTMLButtonElement | null = null;
  private boundKeydown: (e: KeyboardEvent) => void;
  private unsubscribers: (() => void)[] = [];

  // Chat state
  private chatOpen = false;
  private chatMessages: { role: 'user' | 'assistant'; content: string }[] = [];
  private chatMessagesEl: HTMLElement | null = null;
  private chatInputEl: HTMLTextAreaElement | null = null;
  private focusChatId: string;
  private focusSessionId: string;

  // Pomodoro tracking state
  private pomodoroStartedAt: Date | null = null;
  private pomodoroElapsedSeconds = 0;  // seconds elapsed before any pause
  private sessionLogged = false;        // prevent double-logging

  constructor(private parentElement: HTMLElement, options: FocusModeOptions) {
    this.card = options.card;
    this.onExit = options.onExit;

    // Get pomodoro duration from settings (fallback to 25 min)
    const savedDuration = parseInt(localStorage.getItem('voxyflow_pomodoro_minutes') || '') || DEFAULT_DURATION_MINUTES;
    this.remainingSeconds = savedDuration * 60;

    // Unique session/chat IDs for focus mode chat
    this.focusSessionId = `focus::${this.card.id}::${Date.now()}`;
    this.focusChatId = this.focusSessionId;

    // Pre-seed chat with card context
    this.chatMessages = [
      {
        role: 'assistant',
        content: `🎯 I'm ready to help you focus on **"${this.card.title}"**. Let me know if you need anything — clarification, brainstorming, or just to think out loud.`,
      },
    ];

    this.overlay = createElement('div', { className: 'focus-overlay' });
    this.render();
    this.parentElement.appendChild(this.overlay);

    // Keyboard: Escape exits, Space starts/pauses
    this.boundKeydown = this.handleKeydown.bind(this);
    document.addEventListener('keydown', this.boundKeydown);

    // Listen for chat responses
    this.unsubscribers.push(
      apiClient.on('chat:response', (payload) => {
        const { content, done, sessionId } = payload as {
          content: string;
          done: boolean;
          sessionId?: string;
        };
        if (sessionId === this.focusSessionId || (!sessionId && this.chatOpen)) {
          if (done) {
            this.appendChatMessage('assistant', content);
          }
        }
      })
    );

    // Request notification permission if not already granted
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission();
    }
  }

  private render(): void {
    this.overlay.innerHTML = '';

    // Exit button
    const exitBtn = createElement('button', { className: 'focus-exit', title: 'Exit Focus Mode (Esc)' }, '✕');
    exitBtn.addEventListener('click', () => this.exit());

    // Main content area
    const main = createElement('div', { className: 'focus-main' });

    // Session tracker
    this.sessionLabel = createElement('div', { className: 'focus-session-label' });
    this.updateSessionLabel();

    // Card title
    const cardTitle = createElement('h1', { className: 'focus-card-title' }, this.card.title);

    // Card description (if any)
    let descEl: HTMLElement | null = null;
    if (this.card.description && this.card.description.trim()) {
      descEl = createElement('p', { className: 'focus-card-description' }, this.card.description);
    }

    // Timer
    this.timerDisplay = createElement('div', { className: 'focus-timer' });
    this.updateTimerDisplay();

    // Timer controls
    const controls = createElement('div', { className: 'focus-timer-controls' });

    this.startPauseBtn = createElement('button', { className: 'focus-btn focus-btn--primary' }, '▶ Start') as HTMLButtonElement;
    this.startPauseBtn.addEventListener('click', () => this.toggleTimer());

    const resetBtn = createElement('button', { className: 'focus-btn' }, '↺ Reset');
    resetBtn.addEventListener('click', () => this.resetTimer());

    controls.appendChild(this.startPauseBtn);
    controls.appendChild(resetBtn);

    // Chat toggle button
    const chatToggleBtn = createElement('button', { className: 'focus-chat-toggle-btn' }, '💬 Chat with Voxy about this task');
    chatToggleBtn.addEventListener('click', () => this.toggleChat());

    main.appendChild(this.sessionLabel);
    main.appendChild(cardTitle);
    if (descEl) main.appendChild(descEl);
    main.appendChild(this.timerDisplay);
    main.appendChild(controls);
    main.appendChild(chatToggleBtn);

    // Chat sidebar
    const chatSidebar = this.buildChatSidebar();

    this.overlay.appendChild(exitBtn);
    this.overlay.appendChild(main);
    this.overlay.appendChild(chatSidebar);
  }

  private buildChatSidebar(): HTMLElement {
    const sidebar = createElement('div', { className: 'focus-chat' });
    sidebar.id = 'focus-chat-sidebar';

    const chatHeader = createElement('div', { className: 'focus-chat-header' });
    const chatTitle = createElement('span', { className: 'focus-chat-title' }, '💬 Voxy');
    const closeChat = createElement('button', { className: 'focus-chat-close' }, '✕');
    closeChat.addEventListener('click', () => this.toggleChat(false));
    chatHeader.appendChild(chatTitle);
    chatHeader.appendChild(closeChat);

    this.chatMessagesEl = createElement('div', { className: 'focus-chat-messages' });
    // Render pre-seeded messages
    this.chatMessages.forEach((m) => this.renderChatMessage(m.role, m.content));

    const inputArea = createElement('div', { className: 'focus-chat-input-area' });
    this.chatInputEl = createElement('textarea', {
      className: 'focus-chat-input',
      placeholder: 'Ask Voxy...',
      rows: '2',
    }) as HTMLTextAreaElement;
    this.chatInputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendChatMessage();
      }
    });

    const sendBtn = createElement('button', { className: 'focus-chat-send' }, '→');
    sendBtn.addEventListener('click', () => this.sendChatMessage());

    inputArea.appendChild(this.chatInputEl);
    inputArea.appendChild(sendBtn);

    sidebar.appendChild(chatHeader);
    sidebar.appendChild(this.chatMessagesEl);
    sidebar.appendChild(inputArea);

    return sidebar;
  }

  // ─── Timer ──────────────────────────────────────────────────────────────────

  private toggleTimer(): void {
    if (this.isRunning) {
      this.pauseTimer();
    } else {
      this.startTimer();
    }
  }

  private startTimer(): void {
    if (this.isRunning) return;
    this.isRunning = true;
    if (this.startPauseBtn) this.startPauseBtn.textContent = '⏸ Pause';

    // Record start time for tracking (only on first start; resumes accumulate)
    if (!this.pomodoroStartedAt) {
      this.pomodoroStartedAt = new Date();
    }

    this.timerInterval = setInterval(() => {
      this.remainingSeconds--;
      this.pomodoroElapsedSeconds++;
      this.updateTimerDisplay();

      if (this.remainingSeconds <= 0) {
        this.timerComplete();
      }
    }, 1000);
  }

  private pauseTimer(): void {
    if (!this.isRunning) return;
    this.isRunning = false;
    if (this.startPauseBtn) this.startPauseBtn.textContent = '▶ Resume';
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  private resetTimer(): void {
    this.pauseTimer();
    const savedDuration = parseInt(localStorage.getItem('voxyflow_pomodoro_minutes') || '') || DEFAULT_DURATION_MINUTES;
    this.remainingSeconds = savedDuration * 60;
    // Reset tracking state for the new session
    this.pomodoroStartedAt = null;
    this.pomodoroElapsedSeconds = 0;
    this.sessionLogged = false;
    this.updateTimerDisplay();
    if (this.startPauseBtn) this.startPauseBtn.textContent = '▶ Start';
  }

  private timerComplete(): void {
    this.pauseTimer();
    this.playAlertSound();
    this.showTimerNotification();

    // Log completed focus session
    this._logFocusSession(true);

    // Flash timer display
    if (this.timerDisplay) {
      this.timerDisplay.classList.add('focus-timer--done');
      setTimeout(() => this.timerDisplay?.classList.remove('focus-timer--done'), 3000);
    }

    // Update session count and reset for next
    if (this.currentSession < TOTAL_SESSIONS) {
      this.currentSession++;
      this.updateSessionLabel();
      this.resetTimer();
    } else {
      // All 4 sessions done
      if (this.sessionLabel) {
        this.sessionLabel.textContent = '🎉 All 4 sessions complete!';
      }
    }
  }

  private _logFocusSession(completed: boolean): void {
    // Only log if we actually started the timer and have >0 elapsed time
    if (this.sessionLogged || !this.pomodoroStartedAt || this.pomodoroElapsedSeconds <= 0) return;
    this.sessionLogged = true;

    const startedAt = this.pomodoroStartedAt;
    const endedAt = new Date();
    const durationMinutes = Math.max(1, Math.round(this.pomodoroElapsedSeconds / 60));

    const payload: Record<string, unknown> = {
      duration_minutes: durationMinutes,
      completed,
      started_at: startedAt.toISOString(),
      ended_at: endedAt.toISOString(),
    };

    if (this.card.id) payload.card_id = this.card.id;
    if (this.card.projectId) payload.project_id = this.card.projectId;

    fetch('/api/focus-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch((err) => {
      console.warn('[FocusMode] Failed to log focus session:', err);
    });
  }

  private updateTimerDisplay(): void {
    if (!this.timerDisplay) return;
    const mins = Math.floor(this.remainingSeconds / 60);
    const secs = this.remainingSeconds % 60;
    this.timerDisplay.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

    // Pulse red in final minute
    if (this.remainingSeconds <= 60 && this.isRunning) {
      this.timerDisplay.classList.add('focus-timer--warning');
    } else {
      this.timerDisplay.classList.remove('focus-timer--warning');
    }
  }

  private updateSessionLabel(): void {
    if (!this.sessionLabel) return;
    this.sessionLabel.textContent = `Session ${this.currentSession} of ${TOTAL_SESSIONS}`;
  }

  private playAlertSound(): void {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(660, ctx.currentTime + 0.2);
      osc.frequency.setValueAtTime(880, ctx.currentTime + 0.4);
      gain.gain.setValueAtTime(0.4, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.8);
    } catch (e) {
      console.warn('[FocusMode] Audio not available:', e);
    }
  }

  private showTimerNotification(): void {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('🎯 Pomodoro Complete!', {
        body: `Session ${this.currentSession} of ${TOTAL_SESSIONS} done — "${this.card.title}"`,
        icon: '/icons/icon-192x192.png',
      });
    }

    // Always show in-app toast
    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `⏰ Session ${this.currentSession} complete! Take a break.`,
      type: 'success',
      duration: 6000,
    });
  }

  // ─── Chat ────────────────────────────────────────────────────────────────────

  private toggleChat(forceOpen?: boolean): void {
    const sidebar = document.getElementById('focus-chat-sidebar');
    if (!sidebar) return;

    this.chatOpen = forceOpen !== undefined ? forceOpen : !this.chatOpen;
    sidebar.classList.toggle('focus-chat--open', this.chatOpen);

    if (this.chatOpen && this.chatInputEl) {
      setTimeout(() => this.chatInputEl?.focus(), 100);
    }
  }

  private sendChatMessage(): void {
    if (!this.chatInputEl) return;
    const content = this.chatInputEl.value.trim();
    if (!content) return;

    this.chatInputEl.value = '';
    this.appendChatMessage('user', content);

    // Send via chatService with focus session context
    const projectId = this.card.projectId;
    const cardId = this.card.id;

    // First message: include card context
    const contextPrefix = this.chatMessages.length <= 1
      ? `I'm working on: "${this.card.title}". Help me focus on this task.\n\n`
      : '';

    apiClient.send('chat:message', {
      content: contextPrefix + content,
      projectId,
      cardId,
      messageId: `focus-${Date.now()}`,
      chatLevel: 'card',
      sessionId: this.focusSessionId,
      layers: { layer1: true, layer2: false, layer3: false },
    });

    // Show typing indicator
    const typingId = 'focus-typing';
    this.renderChatMessage('assistant', '...', typingId);
  }

  private appendChatMessage(role: 'user' | 'assistant', content: string): void {
    // Remove typing indicator if present
    const typing = document.getElementById('focus-typing');
    if (typing) typing.remove();

    this.chatMessages.push({ role, content });
    this.renderChatMessage(role, content);
  }

  private renderChatMessage(role: 'user' | 'assistant', content: string, id?: string): void {
    if (!this.chatMessagesEl) return;
    const bubble = createElement('div', {
      className: `focus-chat-bubble focus-chat-bubble--${role}`,
    }, content);
    if (id) bubble.id = id;
    this.chatMessagesEl.appendChild(bubble);
    this.chatMessagesEl.scrollTop = this.chatMessagesEl.scrollHeight;
  }

  // ─── Keyboard ────────────────────────────────────────────────────────────────

  private handleKeydown(e: KeyboardEvent): void {
    // Don't intercept when user is typing in chat input
    const target = e.target as HTMLElement;
    const inInput = target.tagName === 'TEXTAREA' || target.tagName === 'INPUT';

    if (e.key === 'Escape') {
      e.preventDefault();
      this.exit();
    } else if (e.key === ' ' && !inInput) {
      e.preventDefault();
      this.toggleTimer();
    }
  }

  // ─── Lifecycle ───────────────────────────────────────────────────────────────

  exit(): void {
    // Log interrupted session (completed=false) if timer was running and had progress
    this._logFocusSession(false);
    this.pauseTimer();
    document.removeEventListener('keydown', this.boundKeydown);
    this.unsubscribers.forEach((fn) => fn());
    this.overlay.remove();
    this.onExit();
  }

  destroy(): void {
    this.exit();
  }
}
