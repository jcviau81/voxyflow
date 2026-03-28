import { eventBus } from '../utils/EventBus';
import * as ort from 'onnxruntime-web';

ort.env.wasm.wasmPaths = '/';
ort.env.wasm.numThreads = 1;

const MEL_FEATURES = 32;

export class WakeWordService {
  private listening = false;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;

  private melSession: ort.InferenceSession | null = null;
  private embSession: ort.InferenceSession | null = null;
  private wwSession: ort.InferenceSession | null = null;
  private modelsLoaded = false;

  // Stage 1: accumulate audio to 1280 samples
  private readonly CHUNK_SIZE = 1280;
  private audioAccum: Float32Array = new Float32Array(this.CHUNK_SIZE);
  private audioAccumIdx = 0;

  // Audio chunk queue — never drop chunks
  private chunkQueue: Float32Array[] = [];
  private drainRunning = false;

  // Stage 2: mel buffer — need 76 frames of 32 features, slide by 8
  private melBuffer: Float32Array[] = [];
  private readonly MEL_WINDOW = 76;
  private readonly MEL_SLIDE = 8;

  // Stage 3: embedding buffer — need 16
  private embBuffer: Float32Array[] = [];
  private readonly EMB_WINDOW = 16;

  // Cooldown — after detection, pause processing to avoid re-triggers
  private lastDetection = 0;
  private readonly COOLDOWN_MS = 3000;
  private inCooldown = false;

  // Debug
  private debugCounters = {
    audioChunks: 0,
    melFrames: 0,
    embeddings: 0,
    scores: 0,
    lastAudioLevel: 0,
    lastLogTime: 0
  };

  async loadModels(): Promise<void> {
    if (this.modelsLoaded) return;
    console.log('[WakeWord] Loading ONNX models...');
    const opts: ort.InferenceSession.SessionOptions = { executionProviders: ['wasm'] };
    this.melSession = await ort.InferenceSession.create('/models/melspectrogram.onnx', opts);
    this.embSession = await ort.InferenceSession.create('/models/embedding_model.onnx', opts);
    this.wwSession  = await ort.InferenceSession.create('/models/alexa_v0.1.onnx', opts);
    this.modelsLoaded = true;
    console.log('[WakeWord] Models loaded ✓');
  }

  async start(): Promise<void> {
    if (this.listening) {
      console.log('[WakeWord] Already listening, skipping start');
      return;
    }
    console.log('[WakeWord] Starting...');
    try {
      await this.loadModels();
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });

      this.audioContext = new AudioContext({ sampleRate: 16000 });
      // On Android, AudioContext may start suspended without user gesture
      if (this.audioContext.state === 'suspended') {
        console.log('[WakeWord] AudioContext suspended, resuming...');
        await this.audioContext.resume();
      }
      console.log('[WakeWord] AudioContext state:', this.audioContext.state, 'sampleRate:', this.audioContext.sampleRate);
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.processor = this.audioContext.createScriptProcessor(2048, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.listening || this.inCooldown) return;
        const data = e.inputBuffer.getChannelData(0);

        // RMS for debug
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        this.debugCounters.lastAudioLevel = Math.sqrt(sum / data.length);

        // Accumulate to CHUNK_SIZE
        for (let i = 0; i < data.length; i++) {
          this.audioAccum[this.audioAccumIdx++] = data[i];
          if (this.audioAccumIdx >= this.CHUNK_SIZE) {
            this.chunkQueue.push(this.audioAccum.slice());
            this.audioAccumIdx = 0;
            this.debugCounters.audioChunks++;
            this.scheduleDrain();
          }
        }
      };
      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      this.listening = true;
      this.resetBuffers();
      this.debugCounters = { audioChunks: 0, melFrames: 0, embeddings: 0, scores: 0, lastAudioLevel: 0, lastLogTime: 0 };

      console.log('[WakeWord] ✓ Listening for wake word...');
    } catch (err) {
      console.error('[WakeWord] Start failed:', err);
      eventBus.emit('wakeword:error', { message: err instanceof Error ? err.message : 'Failed to start' });
      this.listening = false;
      this.cleanup();
    }
  }

  private resetBuffers(): void {
    this.melBuffer = [];
    this.embBuffer = [];
    this.chunkQueue = [];
    this.audioAccumIdx = 0;
    this.drainRunning = false;
    this.inCooldown = false;
  }

  private scheduleDrain(): void {
    if (this.drainRunning) return;
    this.drainRunning = true;
    this.drainQueue();
  }

  private async drainQueue(): Promise<void> {
    while (this.chunkQueue.length > 0 && this.listening && !this.inCooldown) {
      if (this.chunkQueue.length > 50) {
        this.chunkQueue.splice(0, this.chunkQueue.length - 20);
      }
      const chunk = this.chunkQueue.shift()!;
      await this.processChunk(chunk);
    }
    this.drainRunning = false;
  }

  private async processChunk(audio: Float32Array): Promise<void> {
    if (!this.melSession || !this.embSession || !this.wwSession) return;

    try {
      // === Stage 1: Audio → Mel ===
      const melIn = new ort.Tensor('float32', audio, [1, audio.length]);
      const melOut = await this.melSession.run({ input: melIn });
      const rawMel = melOut[Object.keys(melOut)[0]].data as Float32Array;

      // rawMel is N*32 — split into individual frames
      const numFrames = rawMel.length / MEL_FEATURES;
      for (let f = 0; f < numFrames; f++) {
        const frame = new Float32Array(MEL_FEATURES);
        for (let j = 0; j < MEL_FEATURES; j++) {
          frame[j] = (rawMel[f * MEL_FEATURES + j] / 10.0) + 2.0;
        }
        this.melBuffer.push(frame);
        this.debugCounters.melFrames++;
      }

      // Periodic status log (every 3s)
      const now = Date.now();
      if (now - this.debugCounters.lastLogTime > 3000) {
        console.log(`[WakeWord] mel: ${this.melBuffer.length}/${this.MEL_WINDOW} | emb: ${this.embBuffer.length}/${this.EMB_WINDOW} | scores: ${this.debugCounters.scores} | RMS: ${this.debugCounters.lastAudioLevel.toFixed(4)}`);
        this.debugCounters.lastLogTime = now;
      }

      // === Stage 2: Mel buffer → Embedding ===
      while (this.melBuffer.length >= this.MEL_WINDOW) {
        const window = this.melBuffer.slice(0, this.MEL_WINDOW);
        const windowFlat = new Float32Array(this.MEL_WINDOW * MEL_FEATURES);
        window.forEach((f, i) => windowFlat.set(f, i * MEL_FEATURES));

        const embIn = new ort.Tensor('float32', windowFlat, [1, this.MEL_WINDOW, MEL_FEATURES, 1]);
        const embOut = await this.embSession.run({ input_1: embIn });
        const embData = embOut['conv2d_19'];

        const embArr = embData.data as Float32Array;
        const emb = new Float32Array(96);
        for (let i = 0; i < 96 && i < embArr.length; i++) emb[i] = embArr[i];
        this.embBuffer.push(emb);
        this.debugCounters.embeddings++;

        if (this.embBuffer.length > this.EMB_WINDOW) this.embBuffer.shift();
        this.melBuffer.splice(0, this.MEL_SLIDE);

        // === Stage 3: Embeddings → Score ===
        if (this.embBuffer.length >= this.EMB_WINDOW) {
          const flat = new Float32Array(this.EMB_WINDOW * 96);
          this.embBuffer.forEach((e, i) => flat.set(e, i * 96));
          const wwIn = new ort.Tensor('float32', flat, [1, this.EMB_WINDOW, 96]);
          const wwOut = await this.wwSession.run({ 'onnx::Flatten_0': wwIn });
          const score = (wwOut['13'].data as Float32Array)[0];
          this.debugCounters.scores++;

          // Only log interesting scores (> 0.05) to reduce noise
          if (score > 0.05) {
            const icon = score > 0.3 ? '🔴' : score > 0.3 ? '🟡' : '🟠';
            console.log(`[WakeWord] SCORE: ${score.toFixed(4)} ${icon}`);
          }

          if (score > 0.3) {
            console.log(`[WakeWord] 🎉 WAKE WORD DETECTED! score=${score.toFixed(3)}`);
            eventBus.emit('wakeword:detected');
            // Flush buffers and enter cooldown to prevent re-triggers
            this.melBuffer = [];
            this.embBuffer = [];
            this.chunkQueue = [];
            this.inCooldown = true;
            setTimeout(() => {
              this.inCooldown = false;
              this.melBuffer = [];
              this.embBuffer = [];
              console.log('[WakeWord] Cooldown over, listening again...');
              // Resume draining if chunks accumulated
              if (this.chunkQueue.length > 0) this.scheduleDrain();
            }, this.COOLDOWN_MS);
            return; // Stop processing this cycle
          }
        }
      }
    } catch (err) {
      console.error('[WakeWord] Processing error:', err);
    }
  }

  async stop(): Promise<void> {
    if (!this.listening) {
      console.log('[WakeWord] Not listening, skipping stop');
      return;
    }
    console.log('[WakeWord] Stopping...');
    this.listening = false;
    this.cleanup();
    console.log('[WakeWord] Stopped ✓');
  }

  private cleanup(): void {
    if (this.processor) { this.processor.disconnect(); this.processor = null; }
    if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
    this.resetBuffers();
  }

  isListening(): boolean { return this.listening; }
  setAccessKey(_key: string): void {}
}

export const wakeWordService = new WakeWordService();
