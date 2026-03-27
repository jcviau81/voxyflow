import { SttResult } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { sttService, STT_EVENTS } from '../../services/SttService';
import { ttsService } from '../../services/TtsService';
import { wakeWordService } from '../../services/WakeWordService';
import { chatService } from '../../services/ChatService';
import { appState } from '../../state/AppState';

export class VoiceInput {
  private container: HTMLElement;
  private button: HTMLButtonElement | null = null;
  private wakeWordButton: HTMLButtonElement | null = null;
  private indicator: HTMLElement | null = null;
  private transcriptEl: HTMLElement | null = null;
  private errorEl: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];
  private keyHandler: ((e: KeyboardEvent) => void) | null = null;
  private boundMouseDown: (() => void) | null = null;
  private boundMouseUp: (() => void) | null = null;
  private boundMouseLeave: (() => void) | null = null;
  private boundTouchStart: ((e: Event) => void) | null = null;
  private boundTouchEnd: ((e: Event) => void) | null = null;
  private wakeWordEnabled = false;
  private wakeLock: WakeLockSentinel | null = null;
  private autoSendBuffer = '';

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'voice-input', 'data-testid': 'voice-input-btn' });
    this.render();
    this.setupListeners();
    this.setupKeyboardShortcut();
    this.showEngineHint();
    
    // Load wake word preference
    const settings = localStorage.getItem('voxyflow_settings');
    if (settings) {
      try {
        const parsed = JSON.parse(settings);
        this.wakeWordEnabled = parsed?.voice?.wake_word_enabled || false;
        if (this.wakeWordEnabled) {
          this.toggleWakeWord();
        }
      } catch {}
    }
  }

  render(): void {
    this.container.innerHTML = '';

    // Container for both buttons
    const buttonsContainer = createElement('div', { className: 'voice-buttons' });

    // PTT Button
    this.button = createElement('button', {
      className: 'voice-btn',
      'data-tooltip': 'Push to Talk (Alt+V)',
    }) as HTMLButtonElement;
    this.button.innerHTML = '🎤';
    const isMobile = window.innerWidth <= 768 || 'ontouchstart' in window;

    if (isMobile) {
      // Mobile: toggle mode (tap to start, tap to stop)
      this.boundTouchStart = (e: Event) => {
        e.preventDefault();
        if (sttService.recording) {
          this.stopRecording();
        } else {
          this.startRecording();
        }
      };
      this.button.addEventListener('touchstart', this.boundTouchStart);
      // Also handle click for non-touch mobile browsers
      this.button.addEventListener('click', (e) => {
        e.preventDefault();
        if (sttService.recording) {
          this.stopRecording();
        } else {
          this.startRecording();
        }
      });
    } else {
      // Desktop: push-to-talk (hold to record)
      this.boundMouseDown = () => this.startRecording();
      this.boundMouseUp = () => this.stopRecording();
      this.boundMouseLeave = () => { if (sttService.recording) this.stopRecording(); };
      this.button.addEventListener('mousedown', this.boundMouseDown);
      this.button.addEventListener('mouseup', this.boundMouseUp);
      this.button.addEventListener('mouseleave', this.boundMouseLeave);
    }

    // Wake Word Button
    this.wakeWordButton = createElement('button', {
      className: 'wake-word-btn',
      'data-tooltip': 'Wake Word Mode',
    }) as HTMLButtonElement;
    this.wakeWordButton.innerHTML = '🎙️';
    this.wakeWordButton.addEventListener('click', () => this.toggleWakeWord());

    buttonsContainer.appendChild(this.button);
    buttonsContainer.appendChild(this.wakeWordButton);

    // Recording indicator
    this.indicator = createElement('div', { className: 'voice-indicator hidden' });
    const dot = createElement('span', { className: 'recording-dot' });
    const label = createElement('span', { className: 'voice-indicator-label' }, 'Recording...');
    this.indicator.appendChild(dot);
    this.indicator.appendChild(label);

    // Transcript display
    this.transcriptEl = createElement('div', { className: 'voice-transcript hidden' });

    // Error display
    this.errorEl = createElement('div', { className: 'voice-error hidden' });

    this.container.appendChild(buttonsContainer);
    this.container.appendChild(this.indicator);
    this.container.appendChild(this.transcriptEl);
    this.container.appendChild(this.errorEl);

    this.parentElement.appendChild(this.container);
  }

  private async toggleWakeWord(): Promise<void> {
    this.wakeWordEnabled = !this.wakeWordEnabled;
    
    if (this.wakeWordEnabled) {
      // Enable wake word mode
      await wakeWordService.start();
      this.wakeWordButton?.classList.add('active');
      this.wakeWordButton?.setAttribute('data-tooltip', 'Wake Word Mode ON');
      
      // Request screen wake lock
      if ('wakeLock' in navigator) {
        try {
          this.wakeLock = await navigator.wakeLock.request('screen');
        } catch (err) {
          console.warn('[VoiceInput] Failed to acquire wake lock:', err);
        }
      }
      
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: '🎙️ Wake word mode enabled - say "Porcupine" to start',
        type: 'info',
      });
    } else {
      // Disable wake word mode
      await wakeWordService.stop();
      this.wakeWordButton?.classList.remove('active');
      this.wakeWordButton?.setAttribute('data-tooltip', 'Wake Word Mode OFF');
      
      // Release wake lock
      if (this.wakeLock) {
        await this.wakeLock.release();
        this.wakeLock = null;
      }
      
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: '🎙️ Wake word mode disabled',
        type: 'info',
      });
    }
    
    // Save preference
    const settings = localStorage.getItem('voxyflow_settings');
    let parsed: any = {};
    if (settings) {
      try {
        parsed = JSON.parse(settings);
      } catch {}
    }
    if (!parsed.voice) parsed.voice = {};
    parsed.voice.wake_word_enabled = this.wakeWordEnabled;
    localStorage.setItem('voxyflow_settings', JSON.stringify(parsed));
  }

  private setupListeners(): void {
    // Wake word detected
    this.unsubscribers.push(
      eventBus.on(EVENTS.WAKEWORD_DETECTED, () => {
        if (this.wakeWordEnabled && !sttService.recording) {
          // Visual feedback
          eventBus.emit(EVENTS.TOAST_SHOW, {
            message: '✨ Wake word detected!',
            type: 'success',
            duration: 2000,
          });
          
          // Pulsing animation on wake word button
          this.wakeWordButton?.classList.add('pulsing');
          setTimeout(() => {
            this.wakeWordButton?.classList.remove('pulsing');
          }, 2000);
          
          // Auto-start recording
          this.startRecording();
        }
      })
    );
    
    // Wake word error
    this.unsubscribers.push(
      eventBus.on(EVENTS.WAKEWORD_ERROR, (data: unknown) => {
        const { message } = data as { message: string };
        if (this.errorEl) {
          this.errorEl.textContent = message;
          this.errorEl.classList.remove('hidden');
          setTimeout(() => {
            this.errorEl?.classList.add('hidden');
          }, 5000);
        }
      })
    );

    // Transcript updates — SttService now sends the full combined text (finalized + interim)
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_TRANSCRIPT, (result: unknown) => {
        const { transcript, isFinal } = result as SttResult;
        if (this.transcriptEl) {
          this.transcriptEl.textContent = transcript;
          this.transcriptEl.classList.remove('hidden');
          this.transcriptEl.classList.toggle('final', isFinal);
        }
        
        // In wake word mode, auto-send on final transcript
        if (this.wakeWordEnabled && isFinal && transcript.trim()) {
          this.autoSendBuffer = transcript;
          this.autoSendMessage();
        }
      })
    );

    // Buffer flushed after auto-send — hide transcript display
    this.unsubscribers.push(
      eventBus.on('voice:buffer-update', (data: unknown) => {
        const { text } = data as { text: string };
        if (this.transcriptEl && !text) {
          this.transcriptEl.classList.add('hidden');
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
        this.setTranscribingState(false);
      })
    );

    // Voice state changes
    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_START, () => {
        this.updateButtonState(true);
        this.setTranscribingState(false);
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.VOICE_STOP, () => {
        this.updateButtonState(false);
        // Show transcribing indicator for non-webspeech engines
        if (sttService.currentEngine === 'whisper' || sttService.currentEngine === 'whisper_local') {
          this.setTranscribingState(true);
        }
      })
    );

    // Transcribing in progress
    this.unsubscribers.push(
      eventBus.on(STT_EVENTS.TRANSCRIBING, () => {
        this.setTranscribingState(true);
      })
    );

    // Transcription complete
    this.unsubscribers.push(
      eventBus.on(STT_EVENTS.TRANSCRIBE_DONE, () => {
        this.setTranscribingState(false);
      })
    );

    // Auto-send completed — stop recording for a clean cycle
    this.unsubscribers.push(
      eventBus.on('voice:recording-stop', () => {
        if (sttService.recording) {
          this.stopRecording();
        }
      })
    );

    // Whisper local model status
    this.unsubscribers.push(
      eventBus.on(STT_EVENTS.MODEL_STATUS, (data: unknown) => {
        const { status, message } = data as { status: string; message?: string };
        if (status === 'loading') {
          this.setModelLoadingState(true, message);
        } else if (status === 'ready') {
          this.setModelLoadingState(false);
        } else if (status === 'error') {
          this.setModelLoadingState(false);
          if (this.errorEl) {
            this.errorEl.textContent = `Model error: ${message || 'unknown'}`;
            this.errorEl.classList.remove('hidden');
            setTimeout(() => this.errorEl?.classList.add('hidden'), 8000);
          }
        }
      })
    );

    // Model download progress
    this.unsubscribers.push(
      eventBus.on(STT_EVENTS.MODEL_PROGRESS, (data: unknown) => {
        const { progress } = data as { progress: number };
        if (this.indicator) {
          const label = this.indicator.querySelector('.voice-indicator-label') as HTMLElement | null;
          if (label && !this.isRecording()) {
            label.textContent = `Loading model… ${Math.round(progress)}%`;
          }
        }
      })
    );
  }

  private autoSendMessage(): void {
    if (!this.autoSendBuffer.trim()) return;
    
    // Send the message
    chatService.sendMessage(this.autoSendBuffer);
    
    // Clear everything
    this.autoSendBuffer = '';
    sttService.clearBuffer();
    if (this.transcriptEl) {
      this.transcriptEl.classList.add('hidden');
      this.transcriptEl.textContent = '';
    }
    
    // Stop recording
    if (sttService.recording) {
      this.stopRecording();
    }
    
    // Resume wake word listening after a short delay
    if (this.wakeWordEnabled) {
      setTimeout(async () => {
        if (!wakeWordService.isListening() && this.wakeWordEnabled) {
          await wakeWordService.start();
        }
      }, 500);
    }
  }

  private setTranscribingState(transcribing: boolean): void {
    if (this.indicator) {
      const label = this.indicator.querySelector('.voice-indicator-label') as HTMLElement | null;
      if (label && transcribing) {
        this.indicator.classList.remove('model-loading');
        this.indicator.classList.remove('hidden');
        label.textContent = 'Transcribing…';
      } else if (!this.isRecording() && !this.indicator.classList.contains('model-loading')) {
        this.indicator.classList.add('hidden');
      }
    }
  }

  private isRecording(): boolean {
    return sttService.recording;
  }

  private setModelLoadingState(loading: boolean, message?: string): void {
    if (!this.indicator) return;

    const label = this.indicator.querySelector('.voice-indicator-label') as HTMLElement | null;
    if (!label) return;

    if (loading) {
      this.indicator.classList.add('model-loading');
      this.indicator.classList.remove('hidden');
      label.textContent = message || 'Loading model…';
    } else {
      this.indicator.classList.remove('model-loading');
      this.indicator.classList.add('hidden');
      label.textContent = 'Recording...';
    }
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
    // Stop any ongoing TTS so mic doesn't pick up the speaker
    ttsService.stop();
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

      // Show engine indicator on the button
      if (!recording && sttService.currentEngine === 'whisper_local') {
        this.button.setAttribute('data-tooltip', 'Push to Talk (Alt+V) · Whisper Local 🔒');
      } else if (!recording) {
        this.button.setAttribute('data-tooltip', 'Push to Talk (Alt+V)');
      }
    }
    if (this.indicator) {
      this.indicator.classList.toggle('hidden', !recording);
    }
  }

  /** Show a one-time hint if using Web Speech API without a local model configured */
  private showEngineHint(): void {
    if (sttService.currentEngine !== 'webspeech') return;

    // Only show once
    const hintShown = localStorage.getItem('voxyflow_stt_hint_shown');
    if (hintShown) return;

    // Check if whisper_local model is configured
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        if (settings?.whisper_model_id) return; // Model is configured, no need for hint
      } catch { /* ignore */ }
    }

    // Show non-intrusive hint after a brief delay
    setTimeout(() => {
      eventBus.emit('ui:toast:show', {
        message: '💡 Configure a local Whisper model in Settings for private, offline transcription.',
        type: 'info',
        duration: 8000,
      });
      localStorage.setItem('voxyflow_stt_hint_shown', '1');
    }, 3000);
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
    if (this.button) {
      if (this.boundMouseDown) this.button.removeEventListener('mousedown', this.boundMouseDown);
      if (this.boundMouseUp) this.button.removeEventListener('mouseup', this.boundMouseUp);
      if (this.boundMouseLeave) this.button.removeEventListener('mouseleave', this.boundMouseLeave);
      if (this.boundTouchStart) this.button.removeEventListener('touchstart', this.boundTouchStart);
      if (this.boundTouchEnd) this.button.removeEventListener('touchend', this.boundTouchEnd);
    }
    
    // Clean up wake word
    if (this.wakeWordEnabled) {
      wakeWordService.stop();
    }
    if (this.wakeLock) {
      this.wakeLock.release();
      this.wakeLock = null;
    }
    
    // Do NOT destroy sttService — it's a shared singleton
    this.container.remove();
  }
}