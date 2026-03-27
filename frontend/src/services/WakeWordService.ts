import {
  PorcupineWorker,
  BuiltInKeyword,
  PorcupineModel
} from '@picovoice/porcupine-web';
import { WebVoiceProcessor } from '@picovoice/web-voice-processor';
import { eventBus } from '../utils/EventBus';

export class WakeWordService {
  private porcupineWorker: PorcupineWorker | null = null;
  private listening = false;
  private accessKey: string | null = null;

  constructor() {
    // Load access key from localStorage
    this.accessKey = localStorage.getItem('voxyflow_wake_word_access_key');
  }

  async start(): Promise<void> {
    if (this.listening) return;

    // Check access key
    if (!this.accessKey) {
      eventBus.emit('wakeword:error', { 
        message: 'No Porcupine AccessKey configured. Add it in Settings.' 
      });
      return;
    }

    try {
      // Initialize Porcupine Worker with built-in "Porcupine" keyword for testing
      // The 4th parameter is the model - we'll use the base64 default model
      this.porcupineWorker = await PorcupineWorker.create(
        this.accessKey,
        [BuiltInKeyword.Porcupine],
        this.detectionCallback.bind(this),
        { base64: '', publicPath: '/porcupine' } // Use default model
      );

      // WebVoiceProcessor will automatically handle the audio processing
      // when we pass the porcupine worker to it
      await WebVoiceProcessor.subscribe(this.porcupineWorker);

      this.listening = true;
      console.log('[WakeWordService] Started listening for wake word');
    } catch (error) {
      console.error('[WakeWordService] Failed to start:', error);
      eventBus.emit('wakeword:error', { 
        message: error instanceof Error ? error.message : 'Failed to start wake word detection' 
      });
      this.listening = false;
    }
  }

  async stop(): Promise<void> {
    if (!this.listening) return;

    try {
      if (this.porcupineWorker) {
        await WebVoiceProcessor.unsubscribe(this.porcupineWorker);
        this.porcupineWorker.release();
        this.porcupineWorker = null;
      }

      this.listening = false;
      console.log('[WakeWordService] Stopped listening');
    } catch (error) {
      console.error('[WakeWordService] Error stopping:', error);
    }
  }

  private detectionCallback(detection: { index: number }): void {
    console.log('[WakeWordService] Wake word detected!', detection);
    eventBus.emit('wakeword:detected');
  }

  isListening(): boolean {
    return this.listening;
  }

  // Update access key
  setAccessKey(key: string): void {
    this.accessKey = key;
    localStorage.setItem('voxyflow_wake_word_access_key', key);
    
    // If already listening, restart with new key
    if (this.listening) {
      this.stop().then(() => this.start());
    }
  }
}

export const wakeWordService = new WakeWordService();