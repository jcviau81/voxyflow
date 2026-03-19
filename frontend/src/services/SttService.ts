import { SttResult } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS, API_URL } from '../utils/constants';

export type SttEngine = 'webspeech' | 'whisper' | 'whisper_local';

/** Events emitted during transcription */
export const STT_EVENTS = {
  TRANSCRIBING: 'stt:transcribing',
  TRANSCRIBE_DONE: 'stt:transcribe_done',
  MODEL_STATUS: 'stt:model_status',      // { status: 'loading'|'ready'|'error', message? }
  MODEL_PROGRESS: 'stt:model_progress',  // { progress: number 0-100 }
} as const;

/** Whisper model presets for the settings UI */
export const WHISPER_MODEL_PRESETS = [
  {
    id: 'onnx-community/whisper-tiny',
    label: 'Whisper tiny (fastest, ~150MB)',
    lang: 'multilingual',
  },
  {
    id: 'onnx-community/whisper-small',
    label: 'Whisper small (good balance, ~500MB)',
    lang: 'multilingual',
  },
  {
    id: 'onnx-community/whisper-medium',
    label: 'Whisper medium (best for French, ~1.5GB)',
    lang: 'multilingual',
  },
  {
    id: 'Xenova/whisper-small',
    label: 'Xenova whisper-small (lighter alternative)',
    lang: 'multilingual',
  },
] as const;

export class SttService {
  private engine: SttEngine;
  private recognition: SpeechRecognition | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private audioChunks: Blob[] = [];
  private isRecording = false;
  private _transcript = '';
  private stream: MediaStream | null = null;
  private _lang: string;

  // Whisper local (WebWorker)
  private whisperWorker: Worker | null = null;
  private whisperReady = false;
  private whisperModelId = '';
  private pendingAudio: Float32Array | null = null;
  private audioContext: AudioContext | null = null;

  constructor() {
    this.engine = this.detectEngine();
    this._lang = this.detectLanguage();
    this.init();
  }

  private init(): void {
    if (this.engine === 'webspeech') {
      this.initWebSpeech();
    } else if (this.engine === 'whisper_local') {
      this.initWhisperLocal();
    }
  }

  private detectEngine(): SttEngine {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        const engineOverride = settings?.stt_engine as string | undefined;
        if (engineOverride === 'whisper_local') return 'whisper_local';
        if (engineOverride === 'whisper') return 'whisper';
        if (engineOverride === 'webspeech' || engineOverride === 'native') return 'webspeech';
      } catch { /* ignore */ }
    }

    if (window.SpeechRecognition || window.webkitSpeechRecognition) {
      return 'webspeech';
    }
    return 'whisper';
  }

  // ── Web Speech API ────────────────────────────────────────────────────────

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
        try {
          this.recognition?.start();
        } catch {
          this.isRecording = false;
        }
      }
    };
  }

  // ── Whisper Local (WebWorker + Transformers.js) ───────────────────────────

  private initWhisperLocal(): void {
    const modelId = this.getWhisperModelId();
    if (!modelId) {
      console.warn('[SttService] No Whisper model configured. Falling back to Web Speech API.');
      this.engine = 'webspeech';
      this.initWebSpeech();
      return;
    }

    this.whisperModelId = modelId;
    this.spawnWorker(modelId);
  }

  private getWhisperModelId(): string {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        return settings?.whisper_model_id || '';
      } catch { /* ignore */ }
    }
    return '';
  }

  private spawnWorker(modelId: string): void {
    this.destroyWorker();

    this.whisperWorker = new Worker(
      new URL('../workers/whisper.worker.ts', import.meta.url),
      { type: 'module' },
    );

    this.whisperWorker.addEventListener('message', (event: MessageEvent) => {
      const msg = event.data;
      switch (msg.type) {
        case 'status':
          this.whisperReady = msg.status === 'ready';
          eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: msg.status, message: msg.message });
          if (msg.status === 'error') {
            console.error('[SttService] Whisper model error:', msg.message);
          }
          // If model is ready and there's pending audio, transcribe it
          if (this.whisperReady && this.pendingAudio) {
            this.sendToWorker(this.pendingAudio);
            this.pendingAudio = null;
          }
          break;
        case 'progress':
          eventBus.emit(STT_EVENTS.MODEL_PROGRESS, { progress: msg.progress });
          break;
        case 'result':
          this.handleWhisperResult(msg.text as string);
          break;
        case 'error':
          console.error('[SttService] Whisper worker error:', msg.message);
          eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript: '' });
          eventBus.emit(EVENTS.VOICE_ERROR, {
            error: 'whisper-local-failed',
            message: `Local transcription failed: ${msg.message}`,
          });
          break;
      }
    });

    // Load model
    this.whisperWorker.postMessage({ type: 'load', modelId });
  }

  private destroyWorker(): void {
    if (this.whisperWorker) {
      this.whisperWorker.terminate();
      this.whisperWorker = null;
      this.whisperReady = false;
    }
  }

  private sendToWorker(audio: Float32Array): void {
    const lang = this._lang.split('-')[0]; // 'fr-CA' → 'fr'
    this.whisperWorker?.postMessage(
      { type: 'transcribe', audio, language: lang === 'en' || lang === 'fr' ? lang : undefined },
      [audio.buffer], // transfer ownership
    );
  }

  private handleWhisperResult(text: string): void {
    eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript: text });

    if (text) {
      this._transcript = text;
      const result: SttResult = {
        transcript: text,
        confidence: 1.0,
        isFinal: true,
      };
      eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
    } else {
      console.warn('[SttService] Whisper returned empty transcript');
      const result: SttResult = { transcript: '', confidence: 0, isFinal: true };
      eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
    }
  }

  // ── Recording Control ─────────────────────────────────────────────────────

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
    } else if (this.engine === 'whisper_local' || this.engine === 'whisper') {
      await this.startMediaRecording();
    }
  }

  stopRecording(): void {
    if (!this.isRecording) return;
    this.isRecording = false;

    if (this.engine === 'webspeech' && this.recognition) {
      this.recognition.stop();
      eventBus.emit(EVENTS.VOICE_STOP);
    } else if (this.engine === 'whisper_local' || this.engine === 'whisper') {
      this.stopMediaRecording();
    }
  }

  // ── MediaRecorder (shared by whisper_local and whisper server) ────────────

  private async startMediaRecording(): Promise<void> {
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

        if (this.engine === 'whisper_local') {
          await this.processWhisperLocal(audioBlob);
        } else {
          await this.processWhisperServer(audioBlob);
        }

        this.cleanupStream();
      };

      this.mediaRecorder.start(100);
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

  private stopMediaRecording(): void {
    if (this.mediaRecorder?.state === 'recording') {
      this.mediaRecorder.stop();
    }
    eventBus.emit(EVENTS.VOICE_STOP);
  }

  // ── Whisper Local processing ──────────────────────────────────────────────

  private async processWhisperLocal(audioBlob: Blob): Promise<void> {
    eventBus.emit(STT_EVENTS.TRANSCRIBING, { size: audioBlob.size });

    try {
      // Decode audio to Float32Array at 16kHz (Whisper's expected sample rate)
      const float32Audio = await this.decodeAudioToFloat32(audioBlob);

      if (this.whisperReady && this.whisperWorker) {
        this.sendToWorker(float32Audio);
      } else {
        // Model still loading — queue it
        this.pendingAudio = float32Audio;
        console.warn('[SttService] Whisper model not ready yet, audio queued.');
      }
    } catch (error) {
      console.error('[SttService] Audio decode error:', error);
      eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript: '' });
      eventBus.emit(EVENTS.VOICE_ERROR, {
        error: 'audio-decode',
        message: `Failed to decode audio: ${error instanceof Error ? error.message : String(error)}`,
      });
    }
  }

  /**
   * Decode an audio Blob into a Float32Array resampled to 16 kHz (mono).
   */
  private async decodeAudioToFloat32(blob: Blob): Promise<Float32Array> {
    if (!this.audioContext) {
      this.audioContext = new AudioContext({ sampleRate: 16000 });
    }

    const arrayBuffer = await blob.arrayBuffer();
    const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);

    // Get mono channel (mix down if stereo)
    if (audioBuffer.numberOfChannels === 1) {
      return audioBuffer.getChannelData(0);
    }

    const length = audioBuffer.length;
    const mono = new Float32Array(length);
    const channels = audioBuffer.numberOfChannels;
    for (let ch = 0; ch < channels; ch++) {
      const channelData = audioBuffer.getChannelData(ch);
      for (let i = 0; i < length; i++) {
        mono[i] += channelData[i] / channels;
      }
    }
    return mono;
  }

  // ── Whisper Server processing (legacy) ────────────────────────────────────

  private async processWhisperServer(audioBlob: Blob): Promise<void> {
    console.log('[SttService] Sending audio to server-side Whisper:', audioBlob.size, 'bytes');
    eventBus.emit(STT_EVENTS.TRANSCRIBING, { size: audioBlob.size });

    try {
      const lang = this._lang.split('-')[0];
      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.webm');
      formData.append('language', lang === 'en' || lang === 'fr' ? lang : 'auto');

      const sttUrl = `${API_URL}/api/stt`;
      const response = await fetch(sttUrl, { method: 'POST', body: formData });

      if (!response.ok) {
        const errText = await response.text().catch(() => response.statusText);
        throw new Error(`STT server error ${response.status}: ${errText}`);
      }

      const data = await response.json() as { text: string; language?: string };
      const transcript = (data.text ?? '').trim();

      eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE, { transcript });

      if (transcript) {
        this._transcript = transcript;
        const result: SttResult = { transcript, confidence: 1.0, isFinal: true };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, result);
      } else {
        console.warn('[SttService] Whisper server returned empty transcript');
        const result: SttResult = { transcript: '', confidence: 0, isFinal: true };
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

  // ── Stream cleanup ────────────────────────────────────────────────────────

  private cleanupStream(): void {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
  }

  // ── Public API ────────────────────────────────────────────────────────────

  get transcript(): string {
    return this._transcript;
  }

  get recording(): boolean {
    return this.isRecording;
  }

  get currentEngine(): SttEngine {
    return this.engine;
  }

  get modelReady(): boolean {
    if (this.engine !== 'whisper_local') return true;
    return this.whisperReady;
  }

  private detectLanguage(): string {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        const lang = settings?.personality?.preferred_language;
        if (lang === 'en') return 'en-US';
        if (lang === 'fr') return 'fr-CA';
        // Check STT-specific language setting
        const sttLang = settings?.stt_language;
        if (sttLang && sttLang !== 'auto') {
          const langMap: Record<string, string> = {
            en: 'en-US', fr: 'fr-CA', es: 'es-ES',
            de: 'de-DE', ja: 'ja-JP', zh: 'zh-CN',
          };
          return langMap[sttLang] || sttLang;
        }
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

  /**
   * Switch STT engine at runtime. Persists to localStorage.
   */
  setEngine(engine: SttEngine): void {
    this.engine = engine;
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      settings.stt_engine = engine;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch { /* ignore */ }

    if (engine === 'webspeech' && !this.recognition) {
      this.initWebSpeech();
    } else if (engine === 'whisper_local') {
      this.initWhisperLocal();
    }

    // Destroy worker if switching away from local
    if (engine !== 'whisper_local') {
      this.destroyWorker();
    }

    console.log('[SttService] Engine switched to:', engine);
  }

  /**
   * Set the Whisper model ID (HuggingFace model identifier).
   * Persists to localStorage and reloads the worker if engine is whisper_local.
   */
  setWhisperModel(modelId: string): void {
    this.whisperModelId = modelId;
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      settings.whisper_model_id = modelId;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch { /* ignore */ }

    if (this.engine === 'whisper_local' && modelId) {
      this.spawnWorker(modelId);
    }
  }

  get whisperModel(): string {
    return this.whisperModelId;
  }

  destroy(): void {
    this.stopRecording();
    this.cleanupStream();
    this.destroyWorker();
    this.recognition = null;
    this.mediaRecorder = null;
    if (this.audioContext) {
      this.audioContext.close().catch(() => { /* ignore */ });
      this.audioContext = null;
    }
  }
}

export const sttService = new SttService();
