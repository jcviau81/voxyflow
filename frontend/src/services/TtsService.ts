/**
 * TtsService — Text-to-speech with two backends:
 *   1. Browser speechSynthesis (default, no setup needed)
 *   2. Remote XTTS server (higher quality, configurable URL)
 *
 * Usage:
 *   ttsService.speak("Hello!")        // Queues text; plays immediately if idle
 *   ttsService.stop()                 // Stops current + clears queue (user interrupt)
 *   ttsService.isSpeaking             // true while audio is playing
 *   ttsService.speakIfAutoPlay(text)  // Only speaks if auto-play is on
 */

class TtsService {
  private _isSpeaking = false;
  private _onEndCallbacks: Array<() => void> = [];
  private _currentAudio: HTMLAudioElement | null = null;
  private _queue: string[] = [];
  private _processing = false;
  private _forceNative = false;

  /** Force native browser TTS (skip XTTS server) — used in wake word conversation mode */
  set forceNative(val: boolean) {
    this._forceNative = val;
    console.log('[TtsService] forceNative:', val);
  }

  get forceNative(): boolean {
    return this._forceNative;
  }

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
   * Queue text for TTS playback. If nothing is currently playing, starts immediately.
   * If already speaking, the text is queued and will play after the current utterance finishes.
   */
  async speak(text: string): Promise<void> {
    // Always sanitize before queuing — safety net in case callers pass raw markup
    const cleaned = TtsService.cleanForSpeech(text);
    if (!cleaned) return;

    this._queue.push(cleaned);
    if (!this._processing) {
      await this._processQueue();
    }
  }

  /** Process queued messages one at a time. */
  private async _processQueue(): Promise<void> {
    if (this._processing) return;
    this._processing = true;

    while (this._queue.length > 0) {
      const text = this._queue.shift()!;
      const { tts_url, tts_speed } = this.getVoiceSettings();

      if (tts_url && !this._forceNative) {
        await this.speakServer(text, tts_url, tts_speed);
      } else {
        await this.speakBrowser(text, tts_speed);
      }
    }

    this._processing = false;
  }

  /** Play via remote XTTS server */
  private async speakServer(text: string, serverUrl: string, speed: number): Promise<void> {
    const lang = this.detectLanguage();
    const langShort = lang.split('-')[0]; // 'en-US' → 'en'

    console.log(`[TtsService] Speaking via server: ${serverUrl}`);
    this._isSpeaking = true;

    try {
      // Route through backend proxy to avoid mixed-content (HTTPS→HTTP) and CORS issues
      const proxyEndpoint = '/api/settings/tts/speak';
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
          console.warn('[TtsService] Server audio playback error (not falling back — server audio was received)');
          this._isSpeaking = false;
          this._currentAudio = null;
          URL.revokeObjectURL(url);
          this._notifyEnd();
          resolve();
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

      // Detect language from text content (French chars/patterns = fr, else settings/browser)
      const hasFrench = /[àâçéèêëîïôùûüÿæœ]|qu'|l'|d'|n'|j'|c'est|je |tu |il |nous |vous |ils |les |des |une |est |dans |pour |avec |sur |pas |que |qui |mais |ont |sont /i.test(text);
      const settingsLang = this.detectLanguage();
      const lang = hasFrench ? 'fr-CA' : settingsLang;
      utterance.lang = lang;
      console.log('[TtsService] Browser TTS lang:', lang, hasFrench ? '(detected French)' : '(from settings)');

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
        // If no saved voice matched, find a voice matching the detected language
        if (!utterance.voice) {
          const langPrefix = lang.split('-')[0];
          // Prefer local (offline) voices
          const preferred = voices.find(v => v.lang.startsWith(langPrefix) && v.localService);
          if (preferred) {
            utterance.voice = preferred;
          } else {
            // Try any voice matching the language
            const anyMatch = voices.find(v => v.lang.startsWith(langPrefix));
            if (anyMatch) utterance.voice = anyMatch;
          }
        }
        if (utterance.voice) {
          console.log('[TtsService] Using voice:', utterance.voice.name, utterance.voice.lang);
        }
      }

      utterance.rate = speed;
      utterance.volume = 1.0;
      utterance.pitch = 1.0;

      this._isSpeaking = true;

      utterance.onend = () => {
        this._isSpeaking = false;
        this._notifyEnd();
        resolve();
      };

      utterance.onerror = (e) => {
        // 'interrupted' and 'canceled' errors are expected when stop() is called
        if (e.error === 'interrupted' || e.error === 'canceled') {
          this._isSpeaking = false;
          this._notifyEnd();
          resolve();
          return;
        }
        console.warn('[TtsService] speechSynthesis error:', e);
        this._isSpeaking = false;
        this._notifyEnd();
        resolve();
      };

      speechSynthesis.speak(utterance);
    });
  }

  /** Stop current audio playback and clear the queue (user interrupt). */
  stop(): void {
    // Clear pending queue
    this._queue = [];
    this._processing = false;
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
        // "both" or other — detect from browser language
        if (lang === 'both' || !lang) {
          const browserLang = navigator.language || 'en-US';
          if (browserLang.startsWith('fr')) return 'fr-CA';
          return browserLang;
        }
      }
    } catch { /* ignore */ }
    // Default: check browser language
    const browserLang = navigator.language || 'en-US';
    if (browserLang.startsWith('fr')) return 'fr-CA';
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
    // Remove delegate blocks (including malformed/unclosed ones)
    clean = clean.replace(/<delegate[\s\S]*?<\/delegate>/gi, '');
    clean = clean.replace(/<delegate[\s\S]*$/gi, ''); // unclosed delegate at end
    // Remove tool_call blocks
    clean = clean.replace(/<tool_call[\s\S]*?<\/tool_call>/gi, '');
    clean = clean.replace(/<tool_call[\s\S]*$/gi, '');
    // Remove tool_result blocks
    clean = clean.replace(/<tool_result[\s\S]*?<\/tool_result>/gi, '');
    // Remove JSON objects (lines that look like {"key": ...} blocks)
    clean = clean.replace(/^\s*\{[\s\S]*?\}\s*$/gm, '');
    // Remove standalone JSON-like content (e.g. {"name": "tool.name", ...})
    clean = clean.replace(/\{"[^"]*":\s*(?:"[^"]*"|[^}])*\}/g, '');
    // Remove HTML tags
    clean = clean.replace(/<[^>]+>/g, '');
    // Remove markdown tables (lines starting with |)
    clean = clean.replace(/^\|.*\|$/gm, '');
    // Remove markdown horizontal rules (---, ***, ___)
    clean = clean.replace(/^[\s]*[-*_]{3,}[\s]*$/gm, '');
    // Remove markdown headers
    clean = clean.replace(/^#{1,6}\s+/gm, '');
    // Remove markdown bold/italic
    clean = clean.replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1');
    clean = clean.replace(/_{1,3}([^_]+)_{1,3}/g, '$1');
    // Remove markdown links [text](url) → text
    clean = clean.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    // Remove markdown images
    clean = clean.replace(/!\[[^\]]*\]\([^)]+\)/g, '');
    // Remove bare URLs
    clean = clean.replace(/https?:\/\/[^\s)]+/g, '');
    // Remove emojis (Unicode emoji ranges)
    clean = clean.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}]/gu, '');
    // Ensure list items end with a period (prevents TTS glitches on enumerations)
    clean = clean.replace(/^([\s]*[-*•]\s+.+?)([^.!?:])$/gm, '$1$2.');
    clean = clean.replace(/^([\s]*\d+\.\s+.+?)([^.!?:])$/gm, '$1$2.');
    // Remove bullet points (-, *, •) at start of lines
    clean = clean.replace(/^[\s]*[-*•]\s+/gm, '');
    // Remove numbered list markers (1., 2., etc.)
    clean = clean.replace(/^[\s]*\d+\.\s+/gm, '');
    // Remove special characters that cause TTS artifacts
    clean = clean.replace(/[~|>]/g, '');
    // Collapse whitespace
    clean = clean.replace(/\n{2,}/g, '. ');
    clean = clean.replace(/\n/g, ' ');
    clean = clean.replace(/\s{2,}/g, ' ');
    // Remove orphan punctuation (multiple dots, dashes)
    clean = clean.replace(/\.{2,}/g, '.');
    clean = clean.replace(/\s*-\s*-\s*/g, ', ');
    return clean.trim();
  }
}

export const ttsService = new TtsService();

/** Strip markdown, code blocks, and system artifacts from text before speaking. */
export function cleanTextForSpeech(text: string): string {
  return TtsService.cleanForSpeech(text);
}
