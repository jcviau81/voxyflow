import { AudioQueueItem } from '../types';
import { generateId } from '../utils/helpers';

export class AudioService {
  private audioContext: AudioContext | null = null;
  private gainNode: GainNode | null = null;
  private currentSource: AudioBufferSourceNode | null = null;
  private queue: AudioQueueItem[] = [];
  private isPlaying = false;
  private _volume = 0.8;
  private _paused = false;
  private pauseTime = 0;
  private currentBuffer: AudioBuffer | null = null;

  constructor() {
    this.initContext();
  }

  private initContext(): void {
    try {
      this.audioContext = new (window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext)();
      this.gainNode = this.audioContext.createGain();
      this.gainNode.connect(this.audioContext.destination);
      this.gainNode.gain.value = this._volume;
    } catch (error) {
      console.error('[AudioService] Failed to create AudioContext:', error);
    }
  }

  private ensureContext(): void {
    if (this.audioContext?.state === 'suspended') {
      this.audioContext.resume();
    }
    if (!this.audioContext) {
      this.initContext();
    }
  }

  async playAudio(buffer: ArrayBuffer): Promise<void> {
    this.ensureContext();
    if (!this.audioContext || !this.gainNode) return;

    try {
      const audioBuffer = await this.audioContext.decodeAudioData(buffer.slice(0));
      this.currentBuffer = audioBuffer;

      const source = this.audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.gainNode);

      // Cleanup previous source
      if (this.currentSource) {
        try {
          this.currentSource.stop();
        } catch {
          // Already stopped
        }
      }

      this.currentSource = source;
      this.isPlaying = true;
      this._paused = false;

      source.onended = () => {
        this.isPlaying = false;
        this.currentSource = null;
        this.playNext();
      };

      source.start(0);
    } catch (error) {
      console.error('[AudioService] Failed to play audio:', error);
      this.isPlaying = false;
      this.playNext();
    }
  }

  queueAudio(buffer: ArrayBuffer): void {
    const item: AudioQueueItem = {
      buffer,
      id: generateId(),
    };
    this.queue.push(item);

    if (!this.isPlaying) {
      this.playNext();
    }
  }

  private async playNext(): Promise<void> {
    if (this.queue.length === 0) return;

    const next = this.queue.shift()!;
    await this.playAudio(next.buffer);
  }

  pause(): void {
    if (!this.isPlaying || this._paused || !this.audioContext) return;

    this.audioContext.suspend();
    this._paused = true;
    this.pauseTime = this.audioContext.currentTime;
  }

  resume(): void {
    if (!this._paused || !this.audioContext) return;

    this.audioContext.resume();
    this._paused = false;
  }

  stop(): void {
    if (this.currentSource) {
      try {
        this.currentSource.stop();
      } catch {
        // Already stopped
      }
      this.currentSource = null;
    }
    this.isPlaying = false;
    this._paused = false;
    this.queue = [];

    if (this.audioContext?.state === 'suspended') {
      this.audioContext.resume();
    }
  }

  set volume(value: number) {
    this._volume = Math.max(0, Math.min(1, value));
    if (this.gainNode) {
      this.gainNode.gain.value = this._volume;
    }
  }

  get volume(): number {
    return this._volume;
  }

  get playing(): boolean {
    return this.isPlaying;
  }

  get paused(): boolean {
    return this._paused;
  }

  get queueLength(): number {
    return this.queue.length;
  }

  clearQueue(): void {
    this.queue = [];
  }

  destroy(): void {
    this.stop();
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }
    this.gainNode = null;
  }
}

export const audioService = new AudioService();
