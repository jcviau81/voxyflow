import { SttResult } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';
import { isMobile } from '../utils/helpers';

type SttEngine = 'webspeech' | 'whisper';

export class SttService {
  private engine: SttEngine;
  private recognition: SpeechRecognition | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private isRecording = false;
  private _transcript = '';
  private stream: MediaStream | null = null;
  private _lang: string;

  constructor() {
    this.engine = this.detectEngine();
    this._lang = this.detectLanguage();
    if (this.engine === 'webspeech') {
      this.initWebSpeech();
    }
  }

  private detectEngine(): SttEngine {
    // Mobile: use Web Speech API (native Google/Apple)
    // Desktop: use Whisper WASM (placeholder)
    if (isMobile() && (window.SpeechRecognition || window.webkitSpeechRecognition)) {
      return 'webspeech';
    }
    // For now, fall back to Web Speech API on desktop too if available
    if (window.SpeechRecognition || window.webkitSpeechRecognition) {
      return 'webspeech';
    }
    return 'whisper';
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

    if (this.engine === 'webspeech' && this.recognition) {
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
    } else if (this.engine === 'whisper') {
      await this.startWhisperRecording();
    }
  }

  stopRecording(): void {
    if (!this.isRecording) return;

    this.isRecording = false;

    if (this.engine === 'webspeech' && this.recognition) {
      this.recognition.stop();
      eventBus.emit(EVENTS.VOICE_STOP);
    } else if (this.engine === 'whisper') {
      this.stopWhisperRecording();
    }
  }

  // --- Whisper WASM (placeholder for future integration) ---

  private async startWhisperRecording(): Promise<void> {
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.audioChunks = [];

      this.mediaRecorder = new MediaRecorder(this.stream, {
        mimeType: 'audio/webm;codecs=opus',
      });

      this.mediaRecorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          this.audioChunks.push(event.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        await this.processWhisperAudio(audioBlob);
        this.cleanupStream();
      };

      this.mediaRecorder.start(100); // Collect chunks every 100ms
      eventBus.emit(EVENTS.VOICE_START);
    } catch (error) {
      console.error('[SttService] Microphone access error:', error);
      this.isRecording = false;
      eventBus.emit(EVENTS.VOICE_ERROR, {
        error: 'mic-denied',
        message: 'Microphone access denied. Please allow microphone access.',
      });
    }
  }

  private stopWhisperRecording(): void {
    if (this.mediaRecorder?.state === 'recording') {
      this.mediaRecorder.stop();
    }
    eventBus.emit(EVENTS.VOICE_STOP);
  }

  private async processWhisperAudio(audioBlob: Blob): Promise<void> {
    // TODO: Integrate Whisper.cpp WASM
    // For now, this is a placeholder that would:
    // 1. Convert audio blob to float32 PCM
    // 2. Feed to Whisper WASM module
    // 3. Get transcript back
    console.log('[SttService] Whisper WASM processing placeholder', audioBlob.size, 'bytes');

    // Placeholder: emit empty transcript
    const result: SttResult = {
      transcript: '[Whisper WASM not yet integrated]',
      confidence: 0,
      isFinal: true,
    };
    this._transcript = result.transcript;
    eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
  }

  private cleanupStream(): void {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
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
      } catch {}
    }
    return 'en-US'; // default (Quebec-based user)
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
    this.cleanupStream();
    this.recognition = null;
    this.mediaRecorder = null;
  }
}

export const sttService = new SttService();
