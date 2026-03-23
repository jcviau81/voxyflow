/**
 * TtsService — Text-to-speech with two backends:
 *   1. Browser speechSynthesis (default, no setup needed)
 *   2. Remote XTTS server (higher quality, configurable URL)
 *
 * Usage:
 *   ttsService.speak("Hello!")        // Uses configured backend
 *   ttsService.stop()                 // Stops current playback
 *   ttsService.isSpeaking             // true while audio is playing
 *   ttsService.speakIfAutoPlay(text)  // Only speaks if auto-play is on
 */

class TtsService {
  private _isSpeaking = false;
  private _onEndCallbacks: Array<() => void> = [];
  private _currentAudio: HTMLAudioElement | null = null;

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

  /** Read voice settings from localStorage */
  private getVoiceSettings(): { tts_url: string; tts_voice: string; tts_speed: number; tts_auto_play: boolean } {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const v = settings?.voice;
        if (v) {
          return {
            tts_url: v.tts_url || '',
            tts_voice: v.tts_voice || 'default',
            tts_speed: v.tts_speed ?? 1.0,
            tts_auto_play: v.tts_auto_play ?? false,
          };
        }
      }
    } catch { /* ignore */ }
    return { tts_url: '', tts_voice: 'default', tts_speed: 1.0, tts_auto_play: false };
  }

  /**
   * Synthesize and play the given text.
   * Uses server TTS if a URL is configured, otherwise falls back to browser speechSynthesis.
   */
  async speak(text: string): Promise<void> {
    if (!text.trim()) return;

    // Stop previous playback
    this.stop();

    const { tts_url, tts_speed } = this.getVoiceSettings();

    if (tts_url) {
      await this.speakServer(text, tts_url, tts_speed);
    } else {
      await this.speakBrowser(text, tts_speed);
    }
  }

  /** Play via remote XTTS server */
  private async speakServer(text: string, serverUrl: string, speed: number): Promise<void> {
    const lang = this.detectLanguage();
    const langShort = lang.split('-')[0]; // 'en-US' → 'en'

    console.log(`[TtsService] Speaking via server: ${serverUrl}`);
    this._isSpeaking = true;

    try {
      // Route through backend proxy to avoid mixed-content (HTTPS→HTTP) and CORS issues
      const proxyEndpoint = '/api/tts/speak';
      console.log(`[TtsService] Using backend TTS proxy (server: ${serverUrl})`);
      const response = await fetch(proxyEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language: langShort }),
      });

      if (!response.ok) {
        throw new Error(`TTS server returned ${response.status}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);

      return new Promise<void>((resolve) => {
        const audio = new Audio(url);
        this._currentAudio = audio;
        audio.playbackRate = speed;

        audio.onended = () => {
          this._isSpeaking = false;
          this._currentAudio = null;
          URL.revokeObjectURL(url);
          this._notifyEnd();
          resolve();
        };

        audio.onerror = () => {
          console.warn('[TtsService] Server audio playback error, falling back to browser');
          this._isSpeaking = false;
          this._currentAudio = null;
          URL.revokeObjectURL(url);
          this._notifyEnd();
          // Fallback to browser TTS
          this.speakBrowser(text, speed).then(resolve);
        };

        audio.play().catch((err) => {
          console.warn('[TtsService] Failed to play server audio:', err);
          this._isSpeaking = false;
          this._currentAudio = null;
          URL.revokeObjectURL(url);
          this._notifyEnd();
          resolve();
        });
      });
    } catch (err) {
      console.warn('[TtsService] Server TTS failed, falling back to browser:', err);
      this._isSpeaking = false;
      // Fallback to browser
      await this.speakBrowser(text, speed);
    }
  }

  /** Play via browser speechSynthesis */
  private async speakBrowser(text: string, speed: number): Promise<void> {
    if (!('speechSynthesis' in window)) {
      console.warn('[TtsService] speechSynthesis not available in this browser');
      return;
    }

    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);

      const lang = this.detectLanguage();
      utterance.lang = lang;

      const voices = speechSynthesis.getVoices();
      if (voices.length > 0) {
        const { tts_voice } = this.getVoiceSettings();
        // Try to use the saved voice by name
        if (tts_voice && tts_voice !== 'default') {
          const savedVoice = voices.find(v => v.name === tts_voice);
          if (savedVoice) {
            utterance.voice = savedVoice;
          }
        }
        // If no saved voice matched, fall back to first local voice matching language
        if (!utterance.voice) {
          const preferred = voices.find(v => v.lang.startsWith(lang.split('-')[0]) && v.localService);
          if (preferred) utterance.voice = preferred;
        }
      }

      utterance.rate = speed;
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
    // Stop server audio
    if (this._currentAudio) {
      this._currentAudio.pause();
      this._currentAudio.src = '';
      this._currentAudio = null;
    }
    // Stop browser speechSynthesis
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

  /** Speak only if auto-play is enabled in settings. */
  async speakIfAutoPlay(text: string): Promise<void> {
    try {
      const { tts_auto_play } = this.getVoiceSettings();
      if (tts_auto_play && this.isEnabled) {
        await this.speak(text);
      }
    } catch {
      // ignore
    }
  }

  /**
   * Strip markdown, code blocks, and system artifacts from text before speaking.
   * Returns clean spoken text.
   */
  static cleanForSpeech(text: string): string {
    let clean = text;
    // Remove code blocks (```...```)
    clean = clean.replace(/```[\s\S]*?```/g, '');
    // Remove inline code (`...`)
    clean = clean.replace(/`[^`]*`/g, '');
    // Remove markdown headers
    clean = clean.replace(/^#{1,6}\s+/gm, '');
    // Remove markdown bold/italic
    clean = clean.replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1');
    clean = clean.replace(/_{1,3}([^_]+)_{1,3}/g, '$1');
    // Remove markdown links [text](url) → text
    clean = clean.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    // Remove markdown images
    clean = clean.replace(/!\[[^\]]*\]\([^)]+\)/g, '');
    // Remove HTML tags
    clean = clean.replace(/<[^>]+>/g, '');
    // Remove delegate blocks
    clean = clean.replace(/<delegate[\s\S]*?<\/delegate>/gi, '');
    // Collapse whitespace
    clean = clean.replace(/\n{2,}/g, '. ');
    clean = clean.replace(/\n/g, ' ');
    clean = clean.replace(/\s{2,}/g, ' ');
    return clean.trim();
  }
}

export const ttsService = new TtsService();

/** Strip markdown, code blocks, and system artifacts from text before speaking. */
export function cleanTextForSpeech(text: string): string {
  return TtsService.cleanForSpeech(text);
}
