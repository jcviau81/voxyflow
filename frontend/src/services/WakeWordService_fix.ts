import * as ort from 'onnxruntime-web';

export class WakeWordService {
  private melSession?: ort.InferenceSession;
  private embSession?: ort.InferenceSession;
  private wwSession?: ort.InferenceSession;
  private stream?: MediaStream;
  private context?: AudioContext;
  private processor?: AudioWorkletNode;
  private isListening = false;
  private onDetection?: (score: number) => void;

  // Model parameters from openWakeWord
  private readonly CHUNK_SIZE = 1280;      // Audio samples per chunk
  private readonly MEL_WINDOW = 76;        // Mel frames for embedding
  private readonly MEL_STEP = 8;           // Step between mel windows
  private readonly EMB_WINDOW = 16;        // Embeddings for wake word
  private readonly EMB_STEP = 1;           // Step between emb windows
  private readonly THRESHOLD = 0.5;        // Detection threshold

  private audioAccum: Float32Array = new Float32Array(this.CHUNK_SIZE);
  private accumulatedSamples = 0;

  // Fixed to store individual frames
  private melBuffer: Float32Array[] = [];

  private audioContext?: AudioContext;
  private audioSource?: MediaStreamAudioSourceNode;

  private embBuffer: Float32Array[] = [];

  constructor(onDetection?: (score: number) => void) {
    this.onDetection = onDetection;
  }

  async initialize(): Promise<void> {
    // https://github.com/microsoft/onnxruntime/issues/18160#issuecomment-1803595895
    ort.env.wasm.numThreads = 1;
    const opts: ort.InferenceSession.SessionOptions = {
      executionProviders: ['wasm'],
      graphOptimizationLevel: 'all',
      enableCpuMemArena: true,
      enableMemPattern: true,
      executionMode: 'sequential',
      interOpNumThreads: 1,
      intraOpNumThreads: 1
    };
    this.melSession = await ort.InferenceSession.create('/models/melspectrogram.onnx', opts);
    this.embSession = await ort.InferenceSession.create('/models/embedding_model.onnx', opts);
    this.wwSession = await ort.InferenceSession.create('/models/alexa_v0.1.onnx', opts);
  }

  async start(): Promise<void> {
    if (this.isListening) return;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      });
      this.audioContext = new AudioContext({ sampleRate: 16000 });
      this.audioSource = this.audioContext.createMediaStreamSource(this.stream);
      await this.audioContext.audioWorklet.addModule('/audio-processor.js');
      this.processor = new AudioWorkletNode(this.audioContext, 'audio-processor', {
        processorOptions: { bufferSize: 512 }
      });
      this.processor.port.onmessage = (event) => {
        if (event.data.audio) {
          this.processAudioData(event.data.audio);
        }
      };
      this.audioSource.connect(this.processor);
      this.processor.connect(this.audioContext.destination);
      this.isListening = true;
    } catch (err) {
      console.error('Error starting wake word:', err);
      throw err;
    }
  }

  private processAudioData(audioData: Float32Array): void {
    const remaining = this.CHUNK_SIZE - this.accumulatedSamples;
    const toCopy = Math.min(remaining, audioData.length);
    this.audioAccum.set(audioData.slice(0, toCopy), this.accumulatedSamples);
    this.accumulatedSamples += toCopy;
    if (this.accumulatedSamples >= this.CHUNK_SIZE) {
      this.processChunk(this.audioAccum.slice()).catch(err =>
        console.error('Wake word processing error:', err)
      );
      this.accumulatedSamples = 0;
    }
  }

  private async processChunk(audio: Float32Array): Promise<void> {
    if (!this.melSession || !this.embSession || !this.wwSession) return;
    try {
      // === Stage 1: Audio → Mel ===
      const melIn = new ort.Tensor('float32', audio, [1, audio.length]);
      const melOut = await this.melSession.run({ input: melIn });
      const melData = melOut[Object.keys(melOut)[0]];
      
      // The output shape is [time, 1, 1, 32]
      // Extract frames properly
      const shape = melData.dims;
      const numFrames = shape[0];
      const featuresPerFrame = shape[3];
      const rawData = melData.data as Float32Array;
      
      // Process each frame
      for (let i = 0; i < numFrames; i++) {
        const frame = new Float32Array(featuresPerFrame);
        for (let j = 0; j < featuresPerFrame; j++) {
          // Extract frame from 4D tensor [time, 1, 1, features]
          const idx = i * shape[1] * shape[2] * shape[3] + j;
          frame[j] = (rawData[idx] / 10.0) + 2.0; // MANDATORY transformation
        }
        this.melBuffer.push(frame);
      }

      // === Stage 2: Mel buffer → Embedding (needs 76 frames, slide by 8) ===
      while (this.melBuffer.length >= this.MEL_WINDOW) {
        const window = this.melBuffer.slice(0, this.MEL_WINDOW);
        
        // Prepare input for embedding model [1, 76, 32, 1]
        const windowFlat = new Float32Array(this.MEL_WINDOW * 32 * 1);
        for (let i = 0; i < this.MEL_WINDOW; i++) {
          for (let j = 0; j < 32; j++) {
            windowFlat[i * 32 + j] = window[i][j];
          }
        }
        
        const embIn = new ort.Tensor('float32', windowFlat, [1, this.MEL_WINDOW, 32, 1]);
        const embOut = await this.embSession.run({ input_1: embIn });
        const embData = embOut['conv2d_19'];
        
        const embArr = embData.data as Float32Array;
        const emb = new Float32Array(96);
        emb.set(embArr.slice(0, 96));
        this.embBuffer.push(emb);
        
        // Slide mel window
        this.melBuffer = this.melBuffer.slice(this.MEL_STEP);
      }

      // === Stage 3: Embedding buffer → Wake word (needs 16 embeddings, slide by 1) ===
      while (this.embBuffer.length >= this.EMB_WINDOW) {
        const window = this.embBuffer.slice(0, this.EMB_WINDOW);
        const flat = new Float32Array(this.EMB_WINDOW * 96);
        window.forEach((e, i) => flat.set(e, i * 96));
        const wwIn = new ort.Tensor('float32', flat, [1, this.EMB_WINDOW, 96]);
        const wwOut = await this.wwSession.run({ 'onnx::Flatten_0': wwIn });
        const score = (wwOut['13'].data as Float32Array)[0];
        if (score > this.THRESHOLD) {
          console.log();
          this.onDetection?.(score);
          // Clear buffers to prevent repeated detections
          this.melBuffer = [];
          this.embBuffer = [];
        }
        this.embBuffer = this.embBuffer.slice(this.EMB_STEP);
      }
    } catch (err) {
      console.error('Processing error:', err);
    }
  }

  stop(): void {
    if (this.processor) {
      this.processor.disconnect();
      this.processor = undefined;
    }
    if (this.audioSource) {
      this.audioSource.disconnect();
      this.audioSource = undefined;
    }
    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = undefined;
    }
    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = undefined;
    }
    this.isListening = false;
    this.melBuffer = [];
    this.embBuffer = [];
    this.accumulatedSamples = 0;
  }

  isActive(): boolean {
    return this.isListening;
  }
}
