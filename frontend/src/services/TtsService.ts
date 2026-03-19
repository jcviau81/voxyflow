/**
 * TtsService — Text-to-speech via browser speechSynthesis API.
 *
 * Usage:
 *   ttsService.speak("Hello!")   // Uses browser speechSynthesis
 *   ttsService.stop()            // Stops current playback
 *   ttsService.isSpeaking        // true while audio is playing
 *
 * NOTE: Server-side TTS (XTTS on Corsair) has been removed.
 * TTS is now 100% client-side via the Web Speech API.
 */

class TtsService {
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
   * Synthesize and play the given text using browser speechSynthesis.
   * Returns immediately if TTS is disabled or text is empty.
   */
  async speak(text: string): Promise<void> {
    if (!text.trim()) return;
    if (!('speechSynthesis' in window)) {
      console.warn('[TtsService] speechSynthesis not available in this browser');
      return;
    }

    // Stop previous playback
    this.stop();

    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);

      // Try to pick a good voice
      const lang = this.detectLanguage();
      utterance.lang = lang;

      const voices = speechSynthesis.getVoices();
      if (voices.length > 0) {
        const preferred = voices.find(v => v.lang.startsWith(lang.split('-')[0]) && v.localService);
        if (preferred) utterance.voice = preferred;
      }

      utterance.rate = 1.0;
      utterance.pitch = 1.0;

      this._isSpeaking = true;

      utterance.onend = () => {
        this._isSpeaking = false;
        this._notifyEnd();
        resolve();
      };

      utterance.onerror = (e) => {
        console.warn('[TtsService] speechSynthesis error:', e);
        this._isSpeaking = false;
        this._notifyEnd();
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }

  /** Stop current audio playback. */
  stop(): void {
    if ('speechSynthesis' in window) {
      speechSynthesis.cancel();
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

  private detectLanguage(): string {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const lang = settings?.personality?.preferred_language;
        if (lang === 'fr') return 'fr-CA';
        if (lang === 'en') return 'en-US';
      }
    } catch { /* ignore */ }
    return 'en-US';
  }

  private _notifyEnd(): void {
    for (const cb of this._onEndCallbacks) {
      try { cb(); } catch { /* ignore */ }
    }
  }
}

export const ttsService = new TtsService();
