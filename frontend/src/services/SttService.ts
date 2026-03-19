import { SttResult } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

/**
 * STT engine type.
 * - 'webspeech': Browser Web Speech API (works on mobile + desktop Chrome/Edge)
 *
 * NOTE: Server-side Whisper ('whisper') has been removed.
 * Local Whisper WASM support is in the ember/whisper-wasm-stt branch.
 */
type SttEngine = 'webspeech';

/** Events emitted during transcription */
export const STT_EVENTS = {
  TRANSCRIBING: 'stt:transcribing',
  TRANSCRIBE_DONE: 'stt:transcribe_done',
} as const;

export class SttService {
  private engine: SttEngine;
  private recognition: SpeechRecognition | null = null;
  private isRecording = false;
  private _transcript = '';
  private _lang: string;

  constructor() {
    this.engine = 'webspeech';
    this._lang = this.detectLanguage();
    this.initWebSpeech();
  }

  private initWebSpeech(): void {
    const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionClass) return;

    this.recognition = new SpeechRecognitionClass();
    this.recognition.continuous = true;
    this.recognition.interimResults = true;
    this.recognition.lang = this._lang;
    this.recognition.maxAlternatives = 1;

    this.recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interimTranscript = '';
      let finalTranscript = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalTranscript += result[0].transcript;
        } else {
          interimTranscript += result[0].transcript;
        }
      }

      if (finalTranscript) {
        this._transcript = finalTranscript;
        const sttResult: SttResult = {
          transcript: finalTranscript,
          confidence: event.results[event.results.length - 1][0].confidence,
          isFinal: true,
        };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);
      } else if (interimTranscript) {
        this._transcript = interimTranscript;
        const sttResult: SttResult = {
          transcript: interimTranscript,
          confidence: 0,
          isFinal: false,
        };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);
      }
    };

    this.recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      console.error('[SttService] Web Speech error:', event.error);
      let errorMessage = 'Speech recognition error';

      switch (event.error) {
        case 'not-allowed':
          errorMessage = 'Microphone access denied. Please allow microphone access.';
          break;
        case 'no-speech':
          errorMessage = 'No speech detected. Please try again.';
          break;
        case 'network':
          errorMessage = 'Network error. Check your connection.';
          break;
        case 'audio-capture':
          errorMessage = 'No microphone found.';
          break;
      }

      eventBus.emit(EVENTS.VOICE_ERROR, { error: event.error, message: errorMessage });
      this.isRecording = false;
    };

    this.recognition.onend = () => {
      if (this.isRecording) {
        // Auto-restart if still recording (continuous mode)
        try {
          this.recognition?.start();
        } catch {
          this.isRecording = false;
        }
      }
    };
  }

  async startRecording(): Promise<void> {
    if (this.isRecording) return;

    this._transcript = '';
    this.isRecording = true;

    if (this.recognition) {
      try {
        this.recognition.start();
        eventBus.emit(EVENTS.VOICE_START);
      } catch (error) {
        console.error('[SttService] Failed to start Web Speech:', error);
        this.isRecording = false;
        eventBus.emit(EVENTS.VOICE_ERROR, {
          error: 'start-failed',
          message: 'Failed to start speech recognition',
        });
      }
    }
  }

  stopRecording(): void {
    if (!this.isRecording) return;

    this.isRecording = false;

    if (this.recognition) {
      this.recognition.stop();
      eventBus.emit(EVENTS.VOICE_STOP);
    }
  }

  get transcript(): string {
    return this._transcript;
  }

  get recording(): boolean {
    return this.isRecording;
  }

  get currentEngine(): SttEngine {
    return this.engine;
  }

  private detectLanguage(): string {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        const lang = settings?.personality?.preferred_language;
        if (lang === 'en') return 'en-US';
        if (lang === 'fr') return 'fr-CA';
      } catch { /* ignore */ }
    }
    return 'en-US';
  }

  get lang(): string {
    return this._lang;
  }

  setLanguage(lang: string): void {
    this._lang = lang;
    if (this.recognition) {
      this.recognition.lang = lang;
    }
  }

  destroy(): void {
    this.stopRecording();
    this.recognition = null;
  }
}

export const sttService = new SttService();
