import { eventBus } from '../utils/EventBus';
import * as ort from 'onnxruntime-web';

ort.env.wasm.wasmPaths = '/';
ort.env.wasm.numThreads = 1;

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

  // Stage 2: mel buffer — need 76 frames, slide by 8
  private melBuffer: Float32Array[] = [];
  private readonly MEL_WINDOW = 76;
  private readonly MEL_SLIDE = 8;

  // Stage 3: embedding buffer — need 16
  private embBuffer: Float32Array[] = [];
  private readonly EMB_WINDOW = 16;

  // Prevent concurrent ONNX runs
  private processing = false;

  // Cooldown
  private lastDetection = 0;
  private readonly COOLDOWN_MS = 2000;

  async loadModels(): Promise<void> {
    if (this.modelsLoaded) return;
    console.log('[WakeWordService] Loading models...');
    const opts: ort.InferenceSession.SessionOptions = { executionProviders: ['wasm'] };
    this.melSession = await ort.InferenceSession.create('/models/melspectrogram.onnx', opts);
    this.embSession = await ort.InferenceSession.create('/models/embedding_model.onnx', opts);
    this.wwSession  = await ort.InferenceSession.create('/models/alexa_v0.1.onnx', opts);
    this.modelsLoaded = true;
    console.log('[WakeWordService] Models loaded ✓');
  }

  async start(): Promise<void> {
    if (this.listening) return;
    try {
      await this.loadModels();
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });
      this.audioContext = new AudioContext({ sampleRate: 16000 });
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);

      // Buffer size must be power of 2 — accumulate manually to CHUNK_SIZE
      this.processor = this.audioContext.createScriptProcessor(2048, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.listening) return;
        const data = e.inputBuffer.getChannelData(0);
        for (let i = 0; i < data.length; i++) {
          this.audioAccum[this.audioAccumIdx++] = data[i];
          if (this.audioAccumIdx >= this.CHUNK_SIZE) {
            const chunk = this.audioAccum.slice();
            this.audioAccumIdx = 0;
            this.processChunk(chunk); // fire and forget, mutex inside
          }
        }
      };
      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      this.listening = true;
      this.melBuffer = [];
      this.embBuffer = [];
      this.audioAccumIdx = 0;
      console.log('[WakeWordService] Listening...');
    } catch (err) {
      console.error('[WakeWordService] Start failed:', err);
      eventBus.emit('wakeword:error', { message: err instanceof Error ? err.message : 'Failed to start' });
      this.listening = false;
      this.cleanup();
    }
  }

  private async processChunk(audio: Float32Array): Promise<void> {
    if (!this.melSession || !this.embSession || !this.wwSession) return;
    if (this.processing) return;
    this.processing = true;
    try {
      // === Stage 1: Audio → Mel ===
      const melIn = new ort.Tensor('float32', audio, [1, audio.length]);
      const melOut = await this.melSession.run({ input: melIn });
      const rawMel = melOut[Object.keys(melOut)[0]].data as Float32Array;

      // MANDATORY transformation: (value / 10.0) + 2.0
      const mel = new Float32Array(rawMel.length);
      for (let i = 0; i < rawMel.length; i++) mel[i] = (rawMel[i] / 10.0) + 2.0;

      this.melBuffer.push(mel);

      // === Stage 2: Mel buffer → Embedding (needs 76 frames, slide by 8) ===
      while (this.melBuffer.length >= this.MEL_WINDOW) {
        const window = this.melBuffer.slice(0, this.MEL_WINDOW);
        const frameSize = window[0].length;
        const windowFlat = new Float32Array(this.MEL_WINDOW * frameSize);
        window.forEach((f, i) => windowFlat.set(f, i * frameSize));

        // embedding_model input: 'input_1', shape [1, 76, frameSize, 1] or similar
        // Try [1, MEL_WINDOW, frameSize] first
        const embIn = new ort.Tensor('float32', windowFlat, [1, this.MEL_WINDOW, frameSize]);
        let embData: ort.Tensor;
        try {
          const embOut = await this.embSession.run({ input_1: embIn });
          embData = embOut['conv2d_19'];
        } catch {
          // Try alternate shape [1, MEL_WINDOW, frameSize, 1]
          const windowFlat2 = new Float32Array(this.MEL_WINDOW * frameSize * 1);
          windowFlat2.set(windowFlat);
          const embIn2 = new ort.Tensor('float32', windowFlat2, [1, this.MEL_WINDOW, frameSize, 1]);
          const embOut2 = await this.embSession.run({ input_1: embIn2 });
          embData = embOut2['conv2d_19'];
        }

        // Extract 96-dim embedding
        const embArr = embData.data as Float32Array;
        const emb = new Float32Array(96);
        for (let i = 0; i < 96 && i < embArr.length; i++) emb[i] = embArr[i];
        this.embBuffer.push(emb);
        if (this.embBuffer.length > this.EMB_WINDOW) this.embBuffer.shift();

        // Slide by 8
        this.melBuffer.splice(0, this.MEL_SLIDE);

        // === Stage 3: Embeddings → Score ===
        if (this.embBuffer.length >= this.EMB_WINDOW) {
          const flat = new Float32Array(this.EMB_WINDOW * 96);
          this.embBuffer.forEach((e, i) => flat.set(e, i * 96));
          const wwIn = new ort.Tensor('float32', flat, [1, this.EMB_WINDOW, 96]);
          const wwOut = await this.wwSession.run({ 'onnx::Flatten_0': wwIn });
          const score = (wwOut['13'].data as Float32Array)[0];

          if (score > 0.05) console.log(`[WakeWordService] score: ${score.toFixed(4)}`);

          if (score > 0.5) {
            const now = Date.now();
            if (now - this.lastDetection > this.COOLDOWN_MS) {
              this.lastDetection = now;
              console.log(`[WakeWordService] DETECTED! score=${score.toFixed(3)}`);
              eventBus.emit('wakeword:detected');
            }
          }
        }
      }
    } catch (err) {
      console.error('[WakeWordService] Error:', err);
    } finally {
      this.processing = false;
    }
  }

  async stop(): Promise<void> {
    if (!this.listening) return;
    this.listening = false;
    this.cleanup();
  }

  private cleanup(): void {
    if (this.processor) { this.processor.disconnect(); this.processor = null; }
    if (this.audioContext) { this.audioContext.close(); this.audioContext = null; }
    if (this.mediaStream) { this.mediaStream.getTracks().forEach(t => t.stop()); this.mediaStream = null; }
    this.melBuffer = [];
    this.embBuffer = [];
    this.audioAccumIdx = 0;
  }

  isListening(): boolean { return this.listening; }
  setAccessKey(_key: string): void {}
}

export const wakeWordService = new WakeWordService();