/**
 * TtsService — Text-to-speech via the Voxyflow backend → XTTS (Corsair).
 *
 * Usage:
 *   ttsService.speak("Hello!")   // POSTs to /api/tts, plays audio
 *   ttsService.stop()            // Stops current playback
 *   ttsService.isSpeaking        // true while audio is playing
 *
 * TTS is opt-in: honour the global `tts_enabled` setting.
 * Fails silently if the backend is unreachable.
 */

import { API_URL } from '../utils/constants';

class TtsService {
  private audio: HTMLAudioElement | null = null;
  private _isSpeaking = false;
  private _onEndCallbacks: Array<() => void> = [];

  get isSpeaking(): boolean {
    return this._isSpeaking;
  }

  /** Returns whether TTS is enabled in app settings. */
  get isEnabled(): boolean {
    try {
      return localStorage.getItem('tts_enabled') !== 'false';
    } catch {
      return true;
    }
  }

  setEnabled(value: boolean): void {
    try {
      localStorage.setItem('tts_enabled', value ? 'true' : 'false');
    } catch {
      // ignore
    }
  }

  /**
   * Synthesize and play the given text.
   * Returns immediately if TTS is disabled or text is empty.
   */
  async speak(text: string): Promise<void> {
    if (!text.trim()) return;

    // Stop previous playback
    this.stop();

    try {
      const response = await fetch(`${API_URL}/api/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language: 'en' }),
      });

      if (!response.ok) {
        // TTS server down — fail silently
        console.warn('[TtsService] TTS request failed:', response.status);
        return;
      }

      const data = await response.json();
      const audioUrl = `${API_URL}${data.url}`;

      await this._play(audioUrl);
    } catch (err) {
      // Network error — fail silently
      console.warn('[TtsService] TTS error (ignored):', err);
      this._isSpeaking = false;
      this._notifyEnd();
    }
  }

  /** Stop current audio playback. */
  stop(): void {
    if (this.audio) {
      this.audio.pause();
      this.audio.src = '';
      this.audio = null;
    }
    if (this._isSpeaking) {
      this._isSpeaking = false;
      this._notifyEnd();
    }
  }

  /** Register a callback to be called when playback ends (or is stopped). */
  onEnd(cb: () => void): () => void {
    this._onEndCallbacks.push(cb);
    return () => {
      this._onEndCallbacks = this._onEndCallbacks.filter((x) => x !== cb);
    };
  }

  private async _play(url: string): Promise<void> {
    return new Promise((resolve) => {
      const audio = new Audio(url);
      this.audio = audio;
      this._isSpeaking = true;

      audio.addEventListener('ended', () => {
        this._isSpeaking = false;
        this.audio = null;
        this._notifyEnd();
        resolve();
      });

      audio.addEventListener('error', (e) => {
        console.warn('[TtsService] Audio playback error:', e);
        this._isSpeaking = false;
        this.audio = null;
        this._notifyEnd();
        resolve();
      });

      audio.play().catch((err) => {
        console.warn('[TtsService] audio.play() failed:', err);
        this._isSpeaking = false;
        this.audio = null;
        this._notifyEnd();
        resolve();
      });
    });
  }

  private _notifyEnd(): void {
    for (const cb of this._onEndCallbacks) {
      try { cb(); } catch { /* ignore */ }
    }
  }
}

export const ttsService = new TtsService();
