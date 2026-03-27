import { eventBus } from '../utils/EventBus';
import * as ort from 'onnxruntime-web';

// Configure WASM — force non-threaded WASM backend for mobile compatibility
ort.env.wasm.wasmPaths = '/';
ort.env.wasm.numThreads = 1;  // disable threading (not supported on all mobile browsers)

export class WakeWordService {
  private listening = false;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;

  // ONNX sessions
  private melSession: ort.InferenceSession | null = null;
  private embSession: ort.InferenceSession | null = null;
  private wwSession: ort.InferenceSession | null = null;

  // Audio accumulation
  private readonly FRAME_SIZE = 1280; // 80ms at 16kHz
  private audioBuffer: Float32Array = new Float32Array(this.FRAME_SIZE);
  private bufferIndex = 0;

  // Embedding accumulation (need 16 frames = 1.28s window)
  private readonly EMB_WINDOW = 16;
  private embQueue: Float32Array[] = [];

  // Cooldown to avoid rapid re-triggering
  private lastDetection = 0;
  private readonly COOLDOWN_MS = 2000;

  private modelsLoaded = false;

  async loadModels(): Promise<void> {
    if (this.modelsLoaded) return;
    try {
      console.log('[WakeWordService] Loading ONNX models...');
      this.melSession = await ort.InferenceSession.create('/models/melspectrogram.onnx', {
        executionProviders: ['wasm' as ort.InferenceSession.ExecutionProviderConfig],
      });
      this.embSession = await ort.InferenceSession.create('/models/embedding_model.onnx', {
        executionProviders: ['wasm' as ort.InferenceSession.ExecutionProviderConfig],
      });
      this.wwSession = await ort.InferenceSession.create('/models/alexa_v0.1.onnx', {
        executionProviders: ['wasm' as ort.InferenceSession.ExecutionProviderConfig],
      });
      this.modelsLoaded = true;
      console.log('[WakeWordService] Models loaded ✓');
    } catch (err) {
      console.error('[WakeWordService] Failed to load models:', err);
      eventBus.emit('wakeword:error', { message: 'Failed to load wake word models' });
      throw err;
    }
  }

  async start(): Promise<void> {
    if (this.listening) return;
    try {
      await this.loadModels();

      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      this.audioContext = new AudioContext({ sampleRate: 16000 });
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);

      // ScriptProcessor: 1280 samples = 80ms @ 16kHz
      this.processor = this.audioContext.createScriptProcessor(1280, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.listening) return;
        const data = e.inputBuffer.getChannelData(0);
        this.processChunk(new Float32Array(data));
      };

      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      this.listening = true;
      this.embQueue = [];
      this.bufferIndex = 0;
      console.log('[WakeWordService] Listening for wake word...');
    } catch (err) {
      console.error('[WakeWordService] Start failed:', err);
      eventBus.emit('wakeword:error', {
        message: err instanceof Error ? err.message : 'Failed to start wake word detection',
      });
      this.listening = false;
      this.cleanup();
    }
  }

  private async processChunk(audio: Float32Array): Promise<void> {
    if (!this.melSession || !this.embSession || !this.wwSession) return;

    try {
      // Step 1: mel spectrogram
      // Input name: 'input', shape: ['batch_size', 'samples']
      const melInput = new ort.Tensor('float32', audio, [1, audio.length]);
      const melOut = await this.melSession.run({ input: melInput });
      // Output name: 'output', shape: ['time', 1, 'Clipoutput_dim_2', 32]
      const melData = melOut['output'];

      // Reshape mel data for embedding model
      // Embedding expects: input_1 ['unk__316', 76, 32, 1]
      // Our mel output is ['time', 1, 'Clipoutput_dim_2', 32]
      // We need to transpose and reshape to match
      const melArray = melData.data as Float32Array;
      const melReshaped = new Float32Array(76 * 32 * 1);
      
      // For now, pad/trim to 76x32 (should match the mel output)
      const melSize = Math.min(melArray.length, 76 * 32);
      for (let i = 0; i < melSize; i++) {
        melReshaped[i] = melArray[i];
      }

      // Step 2: embedding
      const embInput = new ort.Tensor('float32', melReshaped, [1, 76, 32, 1]);
      const embOut = await this.embSession.run({ input_1: embInput });
      // Output name: 'conv2d_19', shape: ['unk__317', 1, 1, 96]
      const embData = embOut['conv2d_19'];
      
      // Extract the 96-dim embedding
      const emb = new Float32Array(96);
      const embArray = embData.data as Float32Array;
      for (let i = 0; i < 96; i++) {
        emb[i] = embArray[i];
      }

      // Accumulate embeddings
      this.embQueue.push(emb);
      if (this.embQueue.length < this.EMB_WINDOW) return;
      if (this.embQueue.length > this.EMB_WINDOW) this.embQueue.shift();

      // Step 3: wake word score
      // Input: 'onnx::Flatten_0', shape: [1, 16, 96]
      const windowData = new Float32Array(this.EMB_WINDOW * 96);
      this.embQueue.forEach((e, i) => windowData.set(e, i * 96));
      const wwInput = new ort.Tensor('float32', windowData, [1, this.EMB_WINDOW, 96]);
      const wwOut = await this.wwSession.run({ 'onnx::Flatten_0': wwInput });
      // Output name: '13', shape: [1, 1]
      const scoreData = wwOut['13'].data as Float32Array;
      const score = scoreData[0];

      if (score > 0.5) {
        const now = Date.now();
        if (now - this.lastDetection > this.COOLDOWN_MS) {
          this.lastDetection = now;
          console.log(`[WakeWordService] Wake word detected! score=${score.toFixed(3)}`);
          eventBus.emit('wakeword:detected');
        }
      }
    } catch (err) {
      // Silently ignore per-frame errors to not spam logs
    }
  }

  async stop(): Promise<void> {
    if (!this.listening) return;
    this.listening = false;
    this.cleanup();
    console.log('[WakeWordService] Stopped.');
  }

  private cleanup(): void {
    if (this.processor) { 
      this.processor.disconnect(); 
      this.processor = null; 
    }
    if (this.audioContext) { 
      this.audioContext.close(); 
      this.audioContext = null; 
    }
    if (this.mediaStream) { 
      this.mediaStream.getTracks().forEach(t => t.stop()); 
      this.mediaStream = null; 
    }
    this.embQueue = [];
    this.bufferIndex = 0;
  }

  isListening(): boolean {
    return this.listening;
  }

  setAccessKey(_key: string): void {
    // No-op — openWakeWord needs no API key
  }
}

export const wakeWordService = new WakeWordService();