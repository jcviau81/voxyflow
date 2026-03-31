import { eventBus } from '../utils/eventBus';
import { VOICE_EVENTS, STT_EVENTS, type SttResult } from '../utils/voiceEvents';

type SttEngine = 'webspeech' | 'whisper' | 'whisper_local';

class SttService {
  private engine: SttEngine;
  private recognition: SpeechRecognition | null = null;
  private isRecording = false;
  private _oneShot = false;
  private _oneShotRetries = 0;
  private readonly MAX_ONESHOT_RETRIES = 80;
  private _silenceTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly SILENCE_TIMEOUT_MS = 5000;
  private _transcript = '';
  private _lang: string;
  private _whisperModel: string | null = null;
  private _whisperModelFile: File | null = null;
  private _modelReady = false;

  // Whisper WASM worker
  private whisperWorker: Worker | null = null;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private audioChunks: Float32Array[] = [];
  private scriptProcessor: ScriptProcessorNode | null = null;
  private lastFinalResultIndex = -1;
  private finalizedBuffer = '';
  private _webSpeechSupported = false;
  private _isMobile = false;

  constructor() {
    this._isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    this.engine = 'webspeech';
    this._lang = this.detectLanguage();
    this.initWebSpeech();
  }

  private initWebSpeech(): void {
    const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognitionClass) {
      console.warn('[SttService] Web Speech API not supported.');
      this._webSpeechSupported = false;
      return;
    }

    this._webSpeechSupported = true;
    this.recognition = new SpeechRecognitionClass();
    this.recognition.continuous = !this._isMobile;
    this.recognition.interimResults = true;
    this.recognition.lang = this._lang;
    this.recognition.maxAlternatives = 1;

    this.recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interimTranscript = '';
      let hasNewFinal = false;

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          if (i <= this.lastFinalResultIndex) continue;
          const text = result[0].transcript.trim();
          if (text) {
            this.finalizedBuffer += (this.finalizedBuffer ? ' ' : '') + text;
            hasNewFinal = true;
          }
          this.lastFinalResultIndex = i;
        } else {
          interimTranscript += result[0].transcript;
        }
      }

      const displayText =
        this.finalizedBuffer +
        (interimTranscript ? (this.finalizedBuffer ? ' ' : '') + interimTranscript : '');

      if (!displayText) return;

      this._transcript = displayText;
      const sttResult: SttResult = {
        transcript: displayText,
        confidence: hasNewFinal ? event.results[event.results.length - 1][0].confidence : 0,
        isFinal: hasNewFinal,
      };
      eventBus.emit(VOICE_EVENTS.VOICE_TRANSCRIPT, sttResult);

      if (this._oneShot && hasNewFinal && this.finalizedBuffer.trim()) {
        this._oneShotRetries = 0;
      }
      if (this._oneShot && this.finalizedBuffer.trim()) {
        this.resetSilenceTimer();
      }
    };

    this.recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (this._isMobile && (event.error === 'no-speech' || event.error === 'aborted')) return;

      console.error('[SttService] Web Speech error:', event.error);
      let errorMessage = 'Speech recognition error';
      switch (event.error) {
        case 'not-allowed':
          errorMessage = 'Microphone access denied.';
          break;
        case 'no-speech':
          errorMessage = 'No speech detected.';
          break;
        case 'network':
          errorMessage = 'Web Speech API requires internet. Configure a local Whisper model in Settings → Voice.';
          break;
        case 'audio-capture':
          errorMessage = 'No microphone found.';
          break;
      }
      eventBus.emit(VOICE_EVENTS.VOICE_ERROR, { error: event.error, message: errorMessage });
      this.isRecording = false;
    };

    this.recognition.onend = () => {
      if (this._oneShot) {
        if (this.finalizedBuffer.trim() || this._transcript.trim()) {
          if (this._oneShotRetries < this.MAX_ONESHOT_RETRIES) {
            this._oneShotRetries++;
            this.lastFinalResultIndex = -1;
            setTimeout(() => {
              if (!this.isRecording || !this._oneShot) return;
              try { this.recognition?.start(); } catch { this.finishOneShot(); }
            }, 200);
            return;
          }
          this.finishOneShot();
          return;
        }
        if (this._oneShotRetries < this.MAX_ONESHOT_RETRIES) {
          this._oneShotRetries++;
          this.lastFinalResultIndex = -1;
          setTimeout(() => {
            if (!this.isRecording || !this._oneShot) return;
            try { this.recognition?.start(); } catch {
              this.isRecording = false;
              this._oneShot = false;
              this._oneShotRetries = 0;
              eventBus.emit(VOICE_EVENTS.VOICE_STOP);
            }
          }, 200);
          return;
        }
        this.isRecording = false;
        this._oneShot = false;
        this._oneShotRetries = 0;
        this.clearSilenceTimer();
        eventBus.emit(VOICE_EVENTS.VOICE_STOP);
        return;
      }
      if (this.isRecording) {
        this.lastFinalResultIndex = -1;
        const restartDelay = this._isMobile ? 250 : 0;
        setTimeout(() => {
          if (!this.isRecording) return;
          try { this.recognition?.start(); } catch { this.isRecording = false; }
        }, restartDelay);
      }
    };
  }

  private initWhisperWorker(): void {
    if (this.whisperWorker) return;
    this.whisperWorker = new Worker(
      new URL('../workers/whisper.worker.ts', import.meta.url),
      { type: 'module' },
    );

    this.whisperWorker.onmessage = (event: MessageEvent) => {
      const { type, status, message, progress, text } = event.data;
      switch (type) {
        case 'status':
          if (status === 'ready') {
            this._modelReady = true;
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'ready' });
          } else if (status === 'loading') {
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'loading', message });
          } else if (status === 'error') {
            this._modelReady = false;
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'error', message });
          }
          break;
        case 'progress':
          eventBus.emit(STT_EVENTS.MODEL_PROGRESS, { progress });
          break;
        case 'result':
          eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE);
          if (text) {
            this._transcript = text;
            const sttResult: SttResult = { transcript: text, confidence: 1.0, isFinal: true };
            eventBus.emit(VOICE_EVENTS.VOICE_TRANSCRIPT, sttResult);
          }
          break;
        case 'error':
          eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE);
          eventBus.emit(VOICE_EVENTS.VOICE_ERROR, {
            error: 'whisper-error',
            message: message || 'Whisper transcription failed',
          });
          break;
      }
    };

    this.whisperWorker.onerror = () => {
      eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'error', message: 'Worker crashed' });
    };
  }

  private async startWhisperRecording(): Promise<void> {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000 },
      });
      this.audioContext = new AudioContext({ sampleRate: 16000 });
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.audioChunks = [];
      this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.scriptProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
        if (this.isRecording) {
          this.audioChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
        }
      };
      source.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.audioContext.destination);
      this.isRecording = true;
      eventBus.emit(VOICE_EVENTS.VOICE_START);
    } catch (err) {
      this.isRecording = false;
      eventBus.emit(VOICE_EVENTS.VOICE_ERROR, {
        error: 'mic-error',
        message: err instanceof Error ? err.message : 'Failed to access microphone',
      });
    }
  }

  private stopWhisperRecording(): void {
    this.isRecording = false;
    eventBus.emit(VOICE_EVENTS.VOICE_STOP);

    if (this.scriptProcessor) { this.scriptProcessor.disconnect(); this.scriptProcessor = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach((t) => t.stop()); this.mediaStream = null; }
    if (this.audioContext) { this.audioContext.close().catch(() => {}); this.audioContext = null; }

    if (this.audioChunks.length === 0) { console.warn('[SttService] No audio captured'); return; }

    const totalLength = this.audioChunks.reduce((sum, c) => sum + c.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of this.audioChunks) { merged.set(chunk, offset); offset += chunk.length; }
    this.audioChunks = [];

    eventBus.emit(STT_EVENTS.TRANSCRIBING);

    const langMap: Record<string, string> = { 'en-US': 'english', 'fr-CA': 'french', 'fr-FR': 'french' };
    const whisperLang = langMap[this._lang] || undefined;

    if (this.whisperWorker) {
      this.whisperWorker.postMessage({ type: 'transcribe', audio: merged, language: whisperLang }, [merged.buffer]);
    }
  }

  private resetSilenceTimer(): void {
    this.clearSilenceTimer();
    this._silenceTimer = setTimeout(() => {
      if (this.isRecording && this._oneShot && this.finalizedBuffer.trim()) {
        const sttResult = { transcript: this.finalizedBuffer, confidence: 1.0, isFinal: true };
        eventBus.emit(VOICE_EVENTS.VOICE_TRANSCRIPT, sttResult);
        this.stopRecording();
      }
    }, this.SILENCE_TIMEOUT_MS);
  }

  private clearSilenceTimer(): void {
    if (this._silenceTimer) { clearTimeout(this._silenceTimer); this._silenceTimer = null; }
  }

  private finishOneShot(): void {
    const text = this.finalizedBuffer.trim() || this._transcript.trim();
    if (text && !this.finalizedBuffer.trim()) {
      this.finalizedBuffer = text;
      eventBus.emit(VOICE_EVENTS.VOICE_TRANSCRIPT, { transcript: text, confidence: 0.8, isFinal: true });
    }
    this.isRecording = false;
    this._oneShot = false;
    this._oneShotRetries = 0;
    this.clearSilenceTimer();
    eventBus.emit(VOICE_EVENTS.VOICE_STOP);
  }

  async startRecordingOneShot(): Promise<void> {
    this._oneShot = true;
    this._oneShotRetries = 0;
    await this.startRecording();
  }

  async startRecording(): Promise<void> {
    if (this.isRecording) return;
    this._transcript = '';
    this.finalizedBuffer = '';

    if (this.engine === 'whisper_local' && this._modelReady) {
      await this.startWhisperRecording();
    } else if (this.engine === 'whisper_local' && !this._modelReady) {
      eventBus.emit(VOICE_EVENTS.VOICE_ERROR, {
        error: 'model-not-ready',
        message: 'Whisper model not loaded yet. Using Web Speech API as fallback.',
      });
      this.startWebSpeechRecording();
    } else {
      this.startWebSpeechRecording();
    }
  }

  private startWebSpeechRecording(): void {
    this.lastFinalResultIndex = -1;
    if (!this.recognition) {
      if (this._whisperModel && this._modelReady) {
        this.engine = 'whisper_local';
        this.startWhisperRecording();
        return;
      }
      this.isRecording = false;
      eventBus.emit(VOICE_EVENTS.VOICE_ERROR, {
        error: 'not-supported',
        message: 'Speech recognition not supported. Configure a local Whisper model in Settings → Voice.',
      });
      return;
    }
    this.isRecording = true;
    this._lang = this.detectLanguage();
    this.recognition.lang = this._lang;
    try {
      this.recognition.start();
      eventBus.emit(VOICE_EVENTS.VOICE_START);
    } catch (error) {
      console.error('[SttService] Failed to start Web Speech:', error);
      this.isRecording = false;
      eventBus.emit(VOICE_EVENTS.VOICE_ERROR, { error: 'start-failed', message: 'Failed to start speech recognition' });
    }
  }

  stopRecording(): void {
    if (!this.isRecording) return;
    this.clearSilenceTimer();
    if (this.engine === 'whisper_local' && this.audioContext) {
      this.stopWhisperRecording();
    } else {
      this.isRecording = false;
      if (this.recognition) {
        this.recognition.stop();
        eventBus.emit(VOICE_EVENTS.VOICE_STOP);
      }
    }
  }

  clearBuffer(): void {
    this.finalizedBuffer = '';
    this._transcript = '';
    this.lastFinalResultIndex = -1;
  }

  get transcript(): string { return this._transcript; }
  get recording(): boolean { return this.isRecording; }
  get currentEngine(): SttEngine { return this.engine; }
  get webSpeechSupported(): boolean { return this._webSpeechSupported; }
  get isMobile(): boolean { return this._isMobile; }
  get modelReady(): boolean { return this._modelReady; }
  get whisperModel(): string | null { return this._whisperModel; }

  setEngine(newEngine: SttEngine): void {
    if (this.isRecording) this.stopRecording();
    this.engine = newEngine;
    this._modelReady = false;
    if (newEngine === 'webspeech') {
      this.initWebSpeech();
    } else if (newEngine === 'whisper_local') {
      this.initWhisperWorker();
      if (this._whisperModel) this.loadModelInWorker(this._whisperModel);
    }
  }

  setWhisperModel(modelIdOrFile: string | File): void {
    this._modelReady = false;
    if (modelIdOrFile instanceof File) {
      this._whisperModel = `local:${modelIdOrFile.name}`;
      this._whisperModelFile = modelIdOrFile;
      eventBus.emit(STT_EVENTS.MODEL_STATUS, {
        status: 'error',
        message: 'Local file loading not supported. Use a HuggingFace model ID.',
      });
      return;
    }
    this._whisperModel = modelIdOrFile;
    this._whisperModelFile = null;
    this.initWhisperWorker();
    this.loadModelInWorker(modelIdOrFile);
  }

  private loadModelInWorker(modelId: string): void {
    if (!this.whisperWorker) this.initWhisperWorker();
    eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'loading', message: `Loading model ${modelId}…` });
    this.whisperWorker!.postMessage({ type: 'load', modelId });
  }

  get whisperModelFile(): File | null { return this._whisperModelFile; }

  setLanguage(lang: string): void {
    this._lang = lang;
    if (this.recognition) this.recognition.lang = lang;
  }

  get lang(): string { return this._lang; }

  private detectLanguage(): string {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        const sttLang = settings?.voice?.stt_language;
        if (sttLang && sttLang !== 'auto') {
          if (sttLang === 'fr') return 'fr-CA';
          if (sttLang === 'en') return 'en-US';
          return sttLang;
        }
        const lang = settings?.personality?.preferred_language;
        if (lang === 'en') return 'en-US';
        if (lang === 'fr') return 'fr-CA';
        if (lang === 'both' || lang === 'auto' || !lang) {
          const browserLang = navigator.language || 'en-US';
          return browserLang.startsWith('fr') ? 'fr-CA' : browserLang;
        }
      } catch { /* ignore */ }
    }
    const browserLang = navigator.language || 'en-US';
    return browserLang.startsWith('fr') ? 'fr-CA' : browserLang;
  }

  destroy(): void {
    this.stopRecording();
    this.recognition = null;
    if (this.whisperWorker) { this.whisperWorker.terminate(); this.whisperWorker = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach((t) => t.stop()); this.mediaStream = null; }
    if (this.audioContext) { this.audioContext.close().catch(() => {}); this.audioContext = null; }
  }
}

export const sttService = new SttService();
export { STT_EVENTS };
