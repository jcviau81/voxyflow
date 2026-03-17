import { SttResult } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { sttService } from '../../services/SttService';
import { appState } from '../../state/AppState';

export class VoiceInput {
  private container: HTMLElement;
  private button: HTMLButtonElement | null = null;
  private indicator: HTMLElement | null = null;
  private transcriptEl: HTMLElement | null = null;
  private errorEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];
  private keyHandler: ((e: KeyboardEvent) => void) | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'voice-input', 'data-testid': 'voice-input-btn' });
    this.render();
    this.setupListeners();
    this.setupKeyboardShortcut();
  }

  render(): void {
    this.container.innerHTML = '';

    // PTT Button
    this.button = createElement('button', {
      className: 'voice-btn',
      'data-tooltip': 'Push to Talk (Alt+V)',
    }) as HTMLButtonElement;
    this.button.innerHTML = '🎤';
    this.button.addEventListener('mousedown', () => this.startRecording());
    this.button.addEventListener('mouseup', () => this.stopRecording());
    this.button.addEventListener('mouseleave', () => {
      if (sttService.recording) this.stopRecording();
    });

    // Touch support
    this.button.addEventListener('touchstart', (e) => {
      e.preventDefault();
      this.startRecording();
    });
    this.button.addEventListener('touchend', (e) => {
      e.preventDefault();
      this.stopRecording();
    });

    // Recording indicator
    this.indicator = createElement('div', { className: 'voice-indicator hidden' });
    const dot = createElement('span', { className: 'recording-dot' });
    const label = createElement('span', {}, 'Recording...');
    this.indicator.appendChild(dot);
    this.indicator.appendChild(label);

    // Transcript display
    this.transcriptEl = createElement('div', { className: 'voice-transcript hidden' });

    // Error display
    this.errorEl = createElement('div', { className: 'voice-error hidden' });

    this.container.appendChild(this.button);
    this.container.appendChild(this.indicator);
    this.container.appendChild(this.transcriptEl);
    this.container.appendChild(this.errorEl);

    this.parentElement.appendChild(this.container);
  }

  private setupListeners(): void {
    // Transcript updates
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_TRANSCRIPT, (result: unknown) => {
        const { transcript, isFinal } = result as SttResult;
        if (this.transcriptEl) {
          this.transcriptEl.textContent = transcript;
          this.transcriptEl.classList.remove('hidden');
          this.transcriptEl.classList.toggle('final', isFinal);
        }
        if (isFinal) {
          // Auto-hide after a delay
          setTimeout(() => {
            this.transcriptEl?.classList.add('hidden');
          }, 2000);
        }
      })
    );

    // Voice errors
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_ERROR, (data: unknown) => {
        const { message } = data as { error: string; message: string };
        if (this.errorEl) {
          this.errorEl.textContent = message;
          this.errorEl.classList.remove('hidden');
          setTimeout(() => {
            this.errorEl?.classList.add('hidden');
          }, 5000);
        }
        this.updateButtonState(false);
      })
    );

    // Voice state changes
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_START, () => {
        this.updateButtonState(true);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_STOP, () => {
        this.updateButtonState(false);
      })
    );
  }

  private setupKeyboardShortcut(): void {
    this.keyHandler = (e: KeyboardEvent) => {
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        if (sttService.recording) {
          this.stopRecording();
        } else {
          this.startRecording();
        }
      }
    };
    document.addEventListener('keydown', this.keyHandler);
  }

  private startRecording(): void {
    sttService.startRecording();
    appState.set('voiceActive', true);
  }

  private stopRecording(): void {
    sttService.stopRecording();
    appState.set('voiceActive', false);
  }

  private updateButtonState(recording: boolean): void {
    if (this.button) {
      this.button.classList.toggle('recording', recording);
      this.button.innerHTML = recording ? '⏹️' : '🎤';
    }
    if (this.indicator) {
      this.indicator.classList.toggle('hidden', !recording);
    }
  }

  update(): void {
    // No-op for now
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    if (this.keyHandler) {
      document.removeEventListener('keydown', this.keyHandler);
    }
    sttService.destroy();
    this.container.remove();
  }
}
