import { SttResult } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, API_URL } from '../utils/constants';
import { isMobile } from '../utils/helpers';

type SttEngine = 'webspeech' | 'whisper';

/** Events emitted during Whisper server-side transcription */
export const STT_EVENTS = {
  TRANSCRIBING: 'stt:transcribing',
  TRANSCRIBE_DONE: 'stt:transcribe_done',
} as const;

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
    // Check user override from settings first
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        const engineOverride = settings?.stt_engine as SttEngine | undefined;
        if (engineOverride === 'whisper' || engineOverride === 'webspeech') {
          return engineOverride;
        }
      } catch {}
    }

    // Default: Web Speech API (browser-native, zero server dependency)
    // Falls back to Whisper only if Web Speech API is not available
    if (window.SpeechRecognition || window.webkitSpeechRecognition) {
      return 'webspeech';
    }

    // Fallback: server-side Whisper (for browsers without Web Speech API, e.g. Firefox)
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
    console.log('[SttService] Sending audio to server-side Whisper:', audioBlob.size, 'bytes');

    // Emit transcribing state so UI can show a loading indicator
    eventBus.emit(STT_EVENTS.TRANSCRIBING, { size: audioBlob.size });

    try {
      const lang = this._lang.split('-')[0]; // e.g. 'fr-CA' → 'fr'
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.webm');
      formData.append('language', lang === 'en' || lang === 'fr' ? lang : 'auto');

      const sttUrl = `${API_URL}/api/stt`;
      const response = await fetch(sttUrl, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText);
        throw new Error(`STT server error ${response.status}: ${errText}`);
      }

      const data = await response.json() as { text: string; language?: string };
      const transcript = (data.text ?? '').trim();

      eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript });

      if (transcript) {
        this._transcript = transcript;
        const result: SttResult = {
          transcript,
          confidence: 1.0,
          isFinal: true,
        };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
      } else {
        // Empty transcript — nothing heard or silence
        console.warn('[SttService] Whisper returned empty transcript');
        const result: SttResult = {
          transcript: '',
          confidence: 0,
          isFinal: true,
        };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
      }
    } catch (error) {
      console.error('[SttService] Whisper server transcription failed:', error);
      eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript: '' });
      eventBus.emit(EVENTS.VOICE_ERROR, {
        error: 'whisper-failed',
        message: `Transcription failed: ${error instanceof Error ? error.message : String(error)}`,
      });
    }
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

  /**
   * Override the STT engine and persist to localStorage.
   * Takes effect on next recording session.
   */
  setEngine(engine: SttEngine): void {
    this.engine = engine;
    // Persist override in settings
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      settings.stt_engine = engine;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch {}

    // Init Web Speech if switching to it
    if (engine === 'webspeech' && !this.recognition) {
      this.initWebSpeech();
    }
    console.log('[SttService] Engine switched to:', engine);
  }

  destroy(): void {
    this.stopRecording();
    this.cleanupStream();
    this.recognition = null;
    this.mediaRecorder = null;
  }
}

export const sttService = new SttService();
