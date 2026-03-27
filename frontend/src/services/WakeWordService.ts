import { eventBus } from '../utils/EventBus';
import * as ort from 'onnxruntime-web';

export class WakeWordService {
  private listening = false;
  private mediaStream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private session: ort.InferenceSession | null = null;
  private processor: ScriptProcessorNode | null = null;
  
  // Audio buffer for processing (1280 samples = 80ms at 16kHz)
  private readonly FRAME_SIZE = 1280;
  private audioBuffer: Float32Array = new Float32Array(this.FRAME_SIZE);
  private bufferIndex = 0;
  
  constructor() {
    // Initialize ONNX Runtime Web settings
    ort.env.wasm.wasmPaths = '/';
  }

  async start(): Promise<void> {
    if (this.listening) return;

    try {
      console.log('[WakeWordService] Starting openWakeWord detection...');
      
      // Load ONNX model (we'll use a simple pre-trained model)
      if (!this.session) {
        // For now, we'll just mock the model loading
        // In production, you'd load an actual .onnx file
        console.log('[WakeWordService] Would load model from /models/wakeword.onnx');
        
        // Simulate model loading for now
        // this.session = await ort.InferenceSession.create('/models/wakeword.onnx');
      }
      
      // Request microphone access
      this.mediaStream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        } 
      });

      // Create audio context
      this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      
      // Create processor for audio chunks
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      
      this.processor.onaudioprocess = (e) => {
        if (!this.listening) return;
        
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Downsample to 16kHz if needed
        const sampleRatio = this.audioContext!.sampleRate / 16000;
        
        for (let i = 0; i < inputData.length; i += sampleRatio) {
          if (this.bufferIndex < this.FRAME_SIZE) {
            this.audioBuffer[this.bufferIndex++] = inputData[Math.floor(i)];
            
            // When we have a full frame, process it
            if (this.bufferIndex === this.FRAME_SIZE) {
              this.processAudioFrame(this.audioBuffer.slice());
              this.bufferIndex = 0;
            }
          }
        }
      };
      
      // Connect audio nodes
      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);
      
      this.listening = true;
      console.log('[WakeWordService] Started listening for wake words');
      
      // Simulate a detection after 5 seconds for testing
      setTimeout(() => {
        if (this.listening) {
          console.log('[WakeWordService] Simulating wake word detection for testing');
          eventBus.emit('wakeword:detected');
        }
      }, 5000);
      
    } catch (error) {
      console.error('[WakeWordService] Failed to start:', error);
      eventBus.emit('wakeword:error', { 
        message: error instanceof Error ? error.message : 'Failed to start wake word detection' 
      });
      this.listening = false;
      this.cleanup();
    }
  }
  
  private async processAudioFrame(audioData: Float32Array): Promise<void> {
    // In a real implementation, this would:
    // 1. Convert audio to mel spectrogram
    // 2. Run through ONNX model
    // 3. Check if score > threshold
    
    // For now, we just log that we're processing
    // console.log('[WakeWordService] Processing audio frame...');
    
    // Real implementation would be:
    // const inputTensor = new ort.Tensor('float32', audioData, [1, this.FRAME_SIZE]);
    // const results = await this.session!.run({ audio: inputTensor });
    // const score = results.score.data[0];
    // if (score > 0.5) {
    //   eventBus.emit('wakeword:detected');
    // }
  }

  async stop(): Promise<void> {
    if (!this.listening) return;

    try {
      console.log('[WakeWordService] Stopping...');
      this.listening = false;
      this.cleanup();
      console.log('[WakeWordService] Stopped listening');
    } catch (error) {
      console.error('[WakeWordService] Error stopping:', error);
    }
  }

  private cleanup(): void {
    // Disconnect and cleanup audio nodes
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    
    // Close audio context
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    
    // Stop media stream
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
    
    // Clear buffer
    this.bufferIndex = 0;
  }

  isListening(): boolean {
    return this.listening;
  }

  // Kept for compatibility but does nothing
  setAccessKey(key: string): void {
    // No-op - openWakeWord doesn't need an access key!
    console.log('[WakeWordService] Access key not needed with openWakeWord');
  }
}

export const wakeWordService = new WakeWordService();