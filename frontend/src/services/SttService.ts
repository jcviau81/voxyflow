import { SttResult } from '../types';
import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

/**
 * STT engine type.
 * 'webspeech' uses browser Web Speech API (requires internet).
 * 'whisper_local' uses Whisper WASM via WebWorker (private, offline).
 * 'whisper' reserved for remote whisper server (not implemented).
 */
type SttEngine = 'webspeech' | 'whisper' | 'whisper_local';

/** Events emitted during transcription */
export const STT_EVENTS = {
  TRANSCRIBING: 'stt:transcribing',
  TRANSCRIBE_DONE: 'stt:transcribe_done',
  MODEL_STATUS: 'stt:model_status',
  MODEL_PROGRESS: 'stt:model_progress',
} as const;

/** Available Whisper model presets */
export const WHISPER_MODEL_PRESETS = [
  { id: 'Xenova/whisper-tiny', label: 'Whisper Tiny (~40MB, fastest)' },
  { id: 'Xenova/whisper-base', label: 'Whisper Base (~75MB, fast)' },
  { id: 'Xenova/whisper-small', label: 'Whisper Small (~250MB, balanced)' },
  { id: 'Xenova/whisper-medium', label: 'Whisper Medium (~750MB, accurate)' },
] as const;

export class SttService {
  private engine: SttEngine;
  private recognition: SpeechRecognition | null = null;
  private isRecording = false;
  private _oneShot = false;
  private _oneShotRetries = 0;
  private readonly MAX_ONESHOT_RETRIES = 80;
  private _sendDelayTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly SEND_DELAY_MS = 3000;
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
  /** Track last finalized result index to avoid re-processing on mobile (resultIndex stays 0) */
  private lastFinalResultIndex = -1;
  /** Accumulated finalized transcript segments across multiple onresult events */
  private finalizedBuffer = '';
  /** Whether browser supports Web Speech API */
  private _webSpeechSupported = false;
  /** Whether running on mobile (Android/iOS) */
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
      console.warn('[SttService] Web Speech API not supported in this browser. Use Settings → Voice to configure a local Whisper model.');
      this._webSpeechSupported = false;
      return;
    }

    this._webSpeechSupported = true;
    this.recognition = new SpeechRecognitionClass();
    // continuous=true is unstable on Android Chrome — disable it on mobile
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
          // Skip final results we've already processed — on mobile Chrome,
          // resultIndex can stay at 0, causing old finals to be re-emitted
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

      // Build display text: all finalized segments + current interim
      const displayText = this.finalizedBuffer
        + (interimTranscript ? (this.finalizedBuffer ? ' ' : '') + interimTranscript : '');

      if (!displayText) return;

      this._transcript = displayText;
      const sttResult: SttResult = {
        transcript: displayText,
        confidence: hasNewFinal ? event.results[event.results.length - 1][0].confidence : 0,
        isFinal: hasNewFinal,
      };
      eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);

      // In oneShot mode: when we get a new final result, reset retry counter
      // so we keep listening for more speech
      if (this._oneShot && hasNewFinal && this.finalizedBuffer.trim()) {
        console.log('[SttService] OneShot: got final result, resetting retries. Text:', this.finalizedBuffer);
        this._oneShotRetries = 0; // Reset — user is still talking
      }
      // In oneShot mode with only interim results, use silence timer as backup
      if (this._oneShot && this.finalizedBuffer.trim()) {
        this.resetSilenceTimer();
      }
    };

    this.recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // On mobile, 'no-speech' and 'aborted' fire during natural pauses —
      // don't kill the session, let onend handle the restart
      if (this._isMobile && (event.error === "no-speech" || event.error === "aborted"))  {
        console.log('[SttService] Ignoring transient error on mobile:', event.error);
        return;
      }

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
          errorMessage = 'Web Speech API requires internet (sends audio to Google). Go to Settings → Voice to configure a local Whisper model for private offline transcription.';
          break;
        case 'audio-capture':
          errorMessage = 'No microphone found.';
          break;
      }

      eventBus.emit(EVENTS.VOICE_ERROR, { error: event.error, message: errorMessage });
      this.isRecording = false;
    };

    this.recognition.onend = () => {
      if (this._oneShot) {
        console.log('[SttService] OneShot onend fired. Buffer:', this.finalizedBuffer, 'Transcript:', this._transcript, 'Retries:', this._oneShotRetries);
        
        // If we have text, don't send yet — retry to get more speech
        // Only send after MAX retries with no NEW text
        if (this.finalizedBuffer.trim() || this._transcript.trim()) {
          // Still have retries left? Keep listening for more
          if (this._oneShotRetries < this.MAX_ONESHOT_RETRIES) {
            this._oneShotRetries++;
            console.log('[SttService] OneShot: have text but waiting for more speech... (' + this._oneShotRetries + '/' + this.MAX_ONESHOT_RETRIES + ')');
            this.lastFinalResultIndex = -1;
            setTimeout(() => {
              if (!this.isRecording || !this._oneShot) return;
              try {
                this.recognition?.start();
              } catch {
                // Can't restart — send what we have
                this.finishOneShot();
              }
            }, 200);
            return;
          }
          // Max retries with no new text — send what we have
          this.finishOneShot();
          return;
        }
        
        // No text yet — retry if we haven't exceeded max retries
        if (this._oneShotRetries < this.MAX_ONESHOT_RETRIES) {
          this._oneShotRetries++;
          console.log('[SttService] OneShot: no speech yet, retrying... (' + this._oneShotRetries + '/' + this.MAX_ONESHOT_RETRIES + ')');
          this.lastFinalResultIndex = -1;
          setTimeout(() => {
            if (!this.isRecording || !this._oneShot) return;
            try {
              this.recognition?.start();
            } catch {
              console.error('[SttService] OneShot retry failed');
              this.isRecording = false;
              this._oneShot = false;
              this._oneShotRetries = 0;
              eventBus.emit(EVENTS.VOICE_STOP);
            }
          }, 200);
          return;
        }
        
        // Max retries exceeded — give up
        console.log('[SttService] OneShot: max retries reached, stopping');
        this.isRecording = false;
        this._oneShot = false;
        this._oneShotRetries = 0;
        this.clearSilenceTimer();
        eventBus.emit(EVENTS.VOICE_STOP);
        return;
      }
      if (this.isRecording) {
        // Auto-restart if still recording (continuous mode)
        // Reset final index — new session starts result indices from 0
        this.lastFinalResultIndex = -1;
        // On Android (continuous:false), add a small delay before restart
        // to avoid rapid restart loops that crash the recognition engine
        const restartDelay = this._isMobile ? 250 : 0;
        setTimeout(() => {
          if (!this.isRecording) return; // User may have stopped during delay
          try {
            this.recognition?.start();
          } catch {
            this.isRecording = false;
          }
        }, restartDelay);
      }
    };
  }

  // ── Whisper WASM Worker ──────────────────────────────────────────────

  private initWhisperWorker(): void {
    if (this.whisperWorker) return;

    this.whisperWorker = new Worker(
      new URL('../workers/whisper.worker.ts', import.meta.url),
      { type: 'module' }
    );

    this.whisperWorker.onmessage = (event: MessageEvent) => {
      const { type, status, message, progress, text } = event.data;

      switch (type) {
        case 'status':
          if (status === 'ready') {
            this._modelReady = true;
            console.log('[SttService] Whisper model ready');
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'ready' });
          } else if (status === 'loading') {
            console.log('[SttService] Whisper model loading:', message);
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'loading', message });
          } else if (status === 'error') {
            console.error('[SttService] Whisper model error:', message);
            this._modelReady = false;
            eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'error', message });
          }
          break;

        case 'progress':
          eventBus.emit(STT_EVENTS.MODEL_PROGRESS, { progress });
          break;

        case 'result':
          console.log('[SttService] Whisper transcription result:', text);
          eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE);
          if (text) {
            this._transcript = text;
            const sttResult: SttResult = {
              transcript: text,
              confidence: 1.0,
              isFinal: true,
            };
            eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);
          }
          break;

        case 'error':
          console.error('[SttService] Whisper worker error:', message);
          eventBus.emit(STT_EVENTS.TRANSCRIBE_DONE);
          eventBus.emit(EVENTS.VOICE_ERROR, { error: 'whisper-error', message: message || 'Whisper transcription failed' });
          break;
      }
    };

    this.whisperWorker.onerror = (err) => {
      console.error('[SttService] Whisper worker fatal error:', err);
      eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'error', message: 'Worker crashed' });
    };
  }

  private async startWhisperRecording(): Promise<void> {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });

      this.audioContext = new AudioContext({ sampleRate: 16000 });
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);

      // Collect audio chunks via ScriptProcessor (widely supported)
      this.audioChunks = [];
      this.scriptProcessor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.scriptProcessor.onaudioprocess = (e: AudioProcessingEvent) => {
        if (this.isRecording) {
          const data = e.inputBuffer.getChannelData(0);
          this.audioChunks.push(new Float32Array(data));
        }
      };

      source.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.audioContext.destination);

      this.isRecording = true;
      eventBus.emit(EVENTS.VOICE_START);
      console.log('[SttService] Whisper recording started');
    } catch (err) {
      console.error('[SttService] Failed to start Whisper recording:', err);
      this.isRecording = false;
      eventBus.emit(EVENTS.VOICE_ERROR, {
        error: 'mic-error',
        message: err instanceof Error ? err.message : 'Failed to access microphone',
      });
    }
  }

  private stopWhisperRecording(): void {
    this.isRecording = false;
    eventBus.emit(EVENTS.VOICE_STOP);

    // Stop mic and audio context
    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(t => t.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }

    // Merge audio chunks into a single Float32Array
    if (this.audioChunks.length === 0) {
      console.warn('[SttService] No audio captured');
      return;
    }

    const totalLength = this.audioChunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of this.audioChunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    this.audioChunks = [];

    console.log(`[SttService] Sending ${(totalLength / 16000).toFixed(1)}s of audio to Whisper worker`);
    eventBus.emit(STT_EVENTS.TRANSCRIBING);

    // Determine language for Whisper
    const langMap: Record<string, string> = { 'en-US': 'english', 'fr-CA': 'french', 'fr-FR': 'french' };
    const whisperLang = langMap[this._lang] || undefined;

    // Send to worker
    if (this.whisperWorker) {
      this.whisperWorker.postMessage(
        { type: 'transcribe', audio: merged, language: whisperLang },
        [merged.buffer] // Transfer buffer for performance
      );
    }
  }

  // ── Public API ───────────────────────────────────────────────────────

  private resetSilenceTimer(): void {
    this.clearSilenceTimer();
    this._silenceTimer = setTimeout(() => {
      if (this.isRecording && this._oneShot && this.finalizedBuffer.trim()) {
        console.log('[SttService] Silence timeout — auto-stopping one-shot recording');
        // Emit final transcript before stopping
        const sttResult = {
          transcript: this.finalizedBuffer,
          confidence: 1.0,
          isFinal: true,
        };
        eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);
        this.stopRecording();
      }
    }, this.SILENCE_TIMEOUT_MS);
  }

  private clearSilenceTimer(): void {
    if (this._silenceTimer) {
      clearTimeout(this._silenceTimer);
      this._silenceTimer = null;
    }
  }

  private finishOneShot(): void {
    const text = this.finalizedBuffer.trim() || this._transcript.trim();
    console.log('[SttService] OneShot: finishing with text:', text);
    if (text && !this.finalizedBuffer.trim()) {
      this.finalizedBuffer = text;
      const sttResult = {
        transcript: text,
        confidence: 0.8,
        isFinal: true,
      };
      eventBus.emit(EVENTS.VOICE_TRANSCRIPT, sttResult);
    }
    this.isRecording = false;
    this._oneShot = false;
    this._oneShotRetries = 0;
    this.clearSilenceTimer();
    eventBus.emit(EVENTS.VOICE_STOP);
  }

  /** Start recording in one-shot mode (stops after first final result, no auto-restart) */
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
      // Model not loaded yet — fall back to webspeech with a warning
      console.warn('[SttService] Whisper model not ready, falling back to Web Speech');
      eventBus.emit(EVENTS.VOICE_ERROR, {
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
      // Web Speech not available — try falling back to whisper_local
      console.warn('[SttService] Web Speech unavailable, attempting whisper_local fallback');
      if (this._whisperModel && this._modelReady) {
        this.engine = 'whisper_local';
        this.startWhisperRecording();
        return;
      }
      // No fallback available — notify user
      this.isRecording = false;
      eventBus.emit(EVENTS.VOICE_ERROR, {
        error: 'not-supported',
        message: 'Speech recognition not supported in this browser. Go to Settings → Voice to configure a local Whisper model.',
      });
      return;
    }

    this.isRecording = true;
    // Re-detect language on every recording start (settings may have changed)
    this._lang = this.detectLanguage();
    this.recognition.lang = this._lang;
    console.log(`[SttService] Recording with lang: ${this._lang}`);
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

  stopRecording(): void {
    if (!this.isRecording) return;
    this.clearSilenceTimer();

    if (this.engine === 'whisper_local' && this.audioContext) {
      this.stopWhisperRecording();
    } else {
      this.isRecording = false;
      if (this.recognition) {
        this.recognition.stop();
        eventBus.emit(EVENTS.VOICE_STOP);
      }
    }
  }

  /** Clear the finalized buffer (called after auto-send flushes the message) */
  clearBuffer(): void {
    this.finalizedBuffer = '';
    this._transcript = '';
    this.lastFinalResultIndex = -1;
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

  get webSpeechSupported(): boolean {
    return this._webSpeechSupported;
  }

  get isMobile(): boolean {
    return this._isMobile;
  }

  private detectLanguage(): string {
    const stored = localStorage.getItem('voxyflow_settings');
    if (stored) {
      try {
        const settings = JSON.parse(stored);
        // Check explicit STT language first
        const sttLang = settings?.voice?.stt_language;
        if (sttLang && sttLang !== 'auto') {
          if (sttLang === 'fr') return 'fr-CA';
          if (sttLang === 'en') return 'en-US';
          return sttLang; // Pass through custom locale
        }
        // Fall back to personality language
        const lang = settings?.personality?.preferred_language;
        if (lang === 'en') return 'en-US';
        if (lang === 'fr') return 'fr-CA';
        // "both" or "auto" → use browser language
        if (lang === 'both' || lang === 'auto' || !lang) {
          const browserLang = navigator.language || 'en-US';
          if (browserLang.startsWith('fr')) return 'fr-CA';
          return browserLang;
        }
      } catch { /* ignore */ }
    }
    // Default: use browser language
    const browserLang = navigator.language || 'en-US';
    if (browserLang.startsWith('fr')) return 'fr-CA';
    return browserLang;
  }

  get lang(): string {
    return this._lang;
  }

  get whisperModel(): string | null {
    return this._whisperModel;
  }

  get modelReady(): boolean {
    return this._modelReady;
  }

  /**
   * Switch STT engine. Stops any active recording first.
   */
  setEngine(newEngine: SttEngine): void {
    if (this.isRecording) {
      this.stopRecording();
    }
    this.engine = newEngine;
    this._modelReady = false;

    if (newEngine === 'webspeech') {
      this.initWebSpeech();
    } else if (newEngine === 'whisper_local') {
      this.initWhisperWorker();
      // If a model was already set, reload it
      if (this._whisperModel) {
        this.loadModelInWorker(this._whisperModel);
      }
    }
  }

  /**
   * Set a Whisper model by ID or File. Loads the model in the worker.
   */
  setWhisperModel(modelIdOrFile: string | File): void {
    this._modelReady = false;

    if (modelIdOrFile instanceof File) {
      this._whisperModel = `local:${modelIdOrFile.name}`;
      this._whisperModelFile = modelIdOrFile;
      // Local file models aren't supported by the HuggingFace pipeline directly.
      // For now, show an error — only HuggingFace model IDs work with WASM.
      eventBus.emit(STT_EVENTS.MODEL_STATUS, {
        status: 'error',
        message: 'Local file loading not supported yet. Use a HuggingFace model ID instead.',
      });
      return;
    }

    this._whisperModel = modelIdOrFile;
    this._whisperModelFile = null;

    this.initWhisperWorker();
    this.loadModelInWorker(modelIdOrFile);
  }

  private loadModelInWorker(modelId: string): void {
    if (!this.whisperWorker) {
      this.initWhisperWorker();
    }
    console.log('[SttService] Loading Whisper model in worker:', modelId);
    eventBus.emit(STT_EVENTS.MODEL_STATUS, { status: 'loading', message: `Loading model ${modelId}…` });
    this.whisperWorker!.postMessage({ type: 'load', modelId });
  }

  get whisperModelFile(): File | null {
    return this._whisperModelFile;
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

    if (this.whisperWorker) {
      this.whisperWorker.terminate();
      this.whisperWorker = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(t => t.stop());
      this.mediaStream = null;
    }
    if (this.audioContext) {
      this.audioContext.close().catch(() => {});
      this.audioContext = null;
    }
  }
}

export const sttService = new SttService();
