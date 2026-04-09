import { eventBus } from '../utils/eventBus';
import * as ort from 'onnxruntime-web';
// Explicit ?url imports so Vite emits the ORT runtime files as hashed build
// assets — the old `wasmPaths = '/'` relied on files that only existed in the
// legacy webpack public/ dir and 404 in the Vite build.
// ORT 1.25 loads a single variant at runtime (the default non-jsep build is
// enough for pure CPU inference, which is all wake word needs).
import ortWasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';
import ortMjsUrl from 'onnxruntime-web/ort-wasm-simd-threaded.mjs?url';

ort.env.wasm.wasmPaths = { wasm: ortWasmUrl, mjs: ortMjsUrl };
ort.env.wasm.numThreads = 1;

const MEL_FEATURES = 32;

class WakeWordService {
  private listening = false;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;

  private melSession: ort.InferenceSession | null = null;
  private embSession: ort.InferenceSession | null = null;
  private wwSession: ort.InferenceSession | null = null;
  private modelsLoaded = false;

  private readonly CHUNK_SIZE = 1280;
  private audioAccum: Float32Array = new Float32Array(this.CHUNK_SIZE);
  private audioAccumIdx = 0;

  private chunkQueue: Float32Array[] = [];
  private drainRunning = false;

  private melBuffer: Float32Array[] = [];
  private readonly MEL_WINDOW = 76;
  private readonly MEL_SLIDE = 8;

  private embBuffer: Float32Array[] = [];
  private readonly EMB_WINDOW = 16;

  private lastDetection = 0;
  private readonly COOLDOWN_MS = 3000;
  private inCooldown = false;

  private debugCounters = {
    audioChunks: 0, melFrames: 0, embeddings: 0, scores: 0, lastAudioLevel: 0, lastLogTime: 0,
  };

  async loadModels(): Promise<void> {
    if (this.modelsLoaded) return;
    const opts: ort.InferenceSession.SessionOptions = { executionProviders: ['wasm'] };
    this.melSession = await ort.InferenceSession.create('/models/melspectrogram.onnx', opts);
    this.embSession = await ort.InferenceSession.create('/models/embedding_model.onnx', opts);
    this.wwSession  = await ort.InferenceSession.create('/models/alexa_v0.1.onnx', opts);
    this.modelsLoaded = true;
  }

  async start(): Promise<void> {
    if (this.listening) return;
    try {
      await this.loadModels();
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });
      this.audioContext = new AudioContext({ sampleRate: 16000 });
      if (this.audioContext.state === 'suspended') await this.audioContext.resume();

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.processor = this.audioContext.createScriptProcessor(2048, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.listening || this.inCooldown) return;
        const data = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        this.debugCounters.lastAudioLevel = Math.sqrt(sum / data.length);

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
      if (this.chunkQueue.length > 50) this.chunkQueue.splice(0, this.chunkQueue.length - 20);
      const chunk = this.chunkQueue.shift()!;
      await this.processChunk(chunk);
    }
    this.drainRunning = false;
  }

  private async processChunk(audio: Float32Array): Promise<void> {
    if (!this.melSession || !this.embSession || !this.wwSession) return;

    try {
      const melIn = new ort.Tensor('float32', audio, [1, audio.length]);
      const melOut = await this.melSession.run({ input: melIn });
      const rawMel = melOut[Object.keys(melOut)[0]].data as Float32Array;

      const numFrames = rawMel.length / MEL_FEATURES;
      for (let f = 0; f < numFrames; f++) {
        const frame = new Float32Array(MEL_FEATURES);
        for (let j = 0; j < MEL_FEATURES; j++) {
          frame[j] = (rawMel[f * MEL_FEATURES + j] / 10.0) + 2.0;
        }
        this.melBuffer.push(frame);
        this.debugCounters.melFrames++;
      }

      const now = Date.now();
      if (now - this.debugCounters.lastLogTime > 3000) {
        console.log(`[WakeWord] mel: ${this.melBuffer.length}/${this.MEL_WINDOW} | emb: ${this.embBuffer.length}/${this.EMB_WINDOW} | RMS: ${this.debugCounters.lastAudioLevel.toFixed(4)}`);
        this.debugCounters.lastLogTime = now;
      }

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

        if (this.embBuffer.length >= this.EMB_WINDOW) {
          const flat = new Float32Array(this.EMB_WINDOW * 96);
          this.embBuffer.forEach((e, i) => flat.set(e, i * 96));
          const wwIn = new ort.Tensor('float32', flat, [1, this.EMB_WINDOW, 96]);
          const wwOut = await this.wwSession.run({ 'onnx::Flatten_0': wwIn });
          const score = (wwOut['13'].data as Float32Array)[0];
          this.debugCounters.scores++;

          if (score > 0.3) {
            console.log(`[WakeWord] 🎉 WAKE WORD DETECTED! score=${score.toFixed(3)}`);
            eventBus.emit('wakeword:detected');
            this.melBuffer = [];
            this.embBuffer = [];
            this.chunkQueue = [];
            this.inCooldown = true;
            this.lastDetection = Date.now();
            setTimeout(() => {
              this.inCooldown = false;
              this.melBuffer = [];
              this.embBuffer = [];
              if (this.chunkQueue.length > 0) this.scheduleDrain();
            }, this.COOLDOWN_MS);
            return;
          }
        }
      }
    } catch (err) {
      console.error('[WakeWord] Processing error:', err);
    }
    void this.lastDetection; // suppress unused warning
  }

  async stop(): Promise<void> {
    if (!this.listening) return;
    this.listening = false;
    this.cleanup();
  }

  private cleanup(): void {
    if (this.processor) { this.processor.disconnect(); this.processor = null; }
    if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach((t) => t.stop()); this.mediaStream = null; }
    this.resetBuffers();
  }

  isListening(): boolean { return this.listening; }
  setAccessKey(_key: string): void {}
}

export const wakeWordService = new WakeWordService();
