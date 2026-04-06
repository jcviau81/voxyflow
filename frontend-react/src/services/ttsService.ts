/**
 * TtsService — Text-to-speech with two backends:
 *   1. Browser speechSynthesis (default, no setup needed)
 *   2. Remote XTTS server (higher quality, configurable URL)
 */

class TtsService {
  private _isSpeaking = false;
  private _onEndCallbacks: Array<() => void> = [];
  private _onStartCallbacks: Array<() => void> = [];
  private _currentAudio: HTMLAudioElement | null = null;
  private _queue: string[] = [];
  private _processing = false;
  private _forceNative = false;

  set forceNative(val: boolean) {
    this._forceNative = val;
  }

  get forceNative(): boolean {
    return this._forceNative;
  }

  get isSpeaking(): boolean {
    return this._isSpeaking;
  }

  get isEnabled(): boolean {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.tts_enabled ?? true;
      }
    } catch { /* ignore */ }
    return true;
  }

  setEnabled(value: boolean): void {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      if (!settings.voice) settings.voice = {};
      settings.voice.tts_enabled = value;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch { /* ignore */ }
  }

  private getVoiceSettings(): { tts_url: string; tts_voice: string; tts_speed: number; tts_auto_play: boolean } {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const v = settings?.voice;
        if (v) {
          return { tts_url: v.tts_url || '', tts_voice: v.tts_voice || 'default', tts_speed: v.tts_speed ?? 1.0, tts_auto_play: v.tts_auto_play ?? false };
        }
      }
    } catch { /* ignore */ }
    return { tts_url: '', tts_voice: 'default', tts_speed: 1.0, tts_auto_play: false };
  }

  async speak(text: string): Promise<void> {
    const cleaned = TtsService.cleanForSpeech(text);
    if (!cleaned) return;
    this._queue.push(cleaned);
    if (!this._processing) await this._processQueue();
  }

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

  private splitSentences(text: string): string[] {
    const sentences = text.split(/(?<=[.!?])\s+/).map(s => s.trim()).filter(Boolean);
    return sentences.length > 0 ? sentences : [text];
  }

  private async fetchTtsAudio(text: string, language: string): Promise<Blob> {
    const response = await fetch('/api/settings/tts/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, language }),
    });
    if (!response.ok) throw new Error(`TTS server returned ${response.status}`);
    return response.blob();
  }

  private playBlob(blob: Blob, speed: number): Promise<void> {
    const url = URL.createObjectURL(blob);
    return new Promise<void>((resolve) => {
      const audio = new Audio(url);
      this._currentAudio = audio;
      audio.playbackRate = speed;
      const done = () => {
        this._currentAudio = null;
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onended = done;
      audio.onerror = done;
      audio.play().catch(done);
    });
  }

  private async speakServer(text: string, serverUrl: string, speed: number): Promise<void> {
    const lang = this.detectLanguage();
    const langShort = lang.split('-')[0];
    this._isSpeaking = true;
    this._notifyStart();
    try {
      const sentences = this.splitSentences(text);

      if (sentences.length === 1) {
        // Single sentence — no prefetch needed
        const blob = await this.fetchTtsAudio(sentences[0], langShort);
        await this.playBlob(blob, speed);
      } else {
        // Multiple sentences — prefetch next while current plays
        let nextFetch: Promise<Blob> | null = this.fetchTtsAudio(sentences[0], langShort);

        for (let i = 0; i < sentences.length; i++) {
          const currentBlob = await nextFetch!;
          // Start fetching next sentence while current one plays
          nextFetch = (i + 1 < sentences.length)
            ? this.fetchTtsAudio(sentences[i + 1], langShort)
            : null;
          await this.playBlob(currentBlob, speed);
        }
      }

      this._isSpeaking = false;
      this._notifyEnd();
    } catch (err) {
      console.warn('[TtsService] Server TTS failed, falling back to browser:', err);
      this._isSpeaking = false;
      await this.speakBrowser(text, speed);
    }
    void serverUrl;
  }

  private async speakBrowser(text: string, speed: number): Promise<void> {
    if (!('speechSynthesis' in window)) return;
    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text);
      const hasFrench = /[àâçéèêëîïôùûüÿæœ]|qu'|l'|d'|n'|j'|c'est|je |tu |il |nous |vous |ils |les |des |une |est |dans |pour |avec |sur |pas |que |qui |mais |ont |sont /i.test(text);
      const settingsLang = this.detectLanguage();
      const lang = hasFrench ? 'fr-CA' : settingsLang;
      utterance.lang = lang;

      const voices = speechSynthesis.getVoices();
      if (voices.length > 0) {
        const { tts_voice } = this.getVoiceSettings();
        if (tts_voice && tts_voice !== 'default') {
          const saved = voices.find((v) => v.name === tts_voice);
          if (saved) utterance.voice = saved;
        }
        if (!utterance.voice) {
          const langPrefix = lang.split('-')[0];
          const preferred = voices.find((v) => v.lang.startsWith(langPrefix) && v.localService);
          if (preferred) utterance.voice = preferred;
          else {
            const any = voices.find((v) => v.lang.startsWith(langPrefix));
            if (any) utterance.voice = any;
          }
        }
      }

      utterance.rate = speed;
      utterance.volume = 1.0;
      utterance.pitch = 1.0;
      this._isSpeaking = true;
      this._notifyStart();

      const done = (e?: SpeechSynthesisErrorEvent) => {
        if (e && (e.error === 'interrupted' || e.error === 'canceled')) {
          this._isSpeaking = false;
          this._notifyEnd();
          resolve();
          return;
        }
        this._isSpeaking = false;
        this._notifyEnd();
        resolve();
      };
      utterance.onend = () => done();
      utterance.onerror = (e) => done(e);
      speechSynthesis.speak(utterance);
    });
  }

  stop(): void {
    this._queue = [];
    this._processing = false;
    if (this._currentAudio) {
      this._currentAudio.pause();
      this._currentAudio.src = '';
      this._currentAudio = null;
    }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    if (this._isSpeaking) {
      this._isSpeaking = false;
      this._notifyEnd();
    }
  }

  onEnd(cb: () => void): () => void {
    this._onEndCallbacks.push(cb);
    return () => { this._onEndCallbacks = this._onEndCallbacks.filter((x) => x !== cb); };
  }

  /** Subscribe to TTS start events. Returns an unsubscribe function. */
  onStart(cb: () => void): () => void {
    this._onStartCallbacks.push(cb);
    return () => { this._onStartCallbacks = this._onStartCallbacks.filter((x) => x !== cb); };
  }

  async speakIfAutoPlay(text: string): Promise<void> {
    try {
      const { tts_auto_play } = this.getVoiceSettings();
      if (tts_auto_play && this.isEnabled) await this.speak(text);
    } catch { /* ignore */ }
  }

  private detectLanguage(): string {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const lang = settings?.personality?.preferred_language;
        if (lang === 'fr') return 'fr-CA';
        if (lang === 'en') return 'en-US';
        if (lang === 'both' || !lang) {
          const b = navigator.language || 'en-US';
          return b.startsWith('fr') ? 'fr-CA' : b;
        }
      }
    } catch { /* ignore */ }
    const b = navigator.language || 'en-US';
    return b.startsWith('fr') ? 'fr-CA' : 'en-US';
  }

  private _notifyStart(): void {
    for (const cb of this._onStartCallbacks) {
      try { cb(); } catch { /* ignore */ }
    }
  }

  private _notifyEnd(): void {
    for (const cb of this._onEndCallbacks) {
      try { cb(); } catch { /* ignore */ }
    }
  }

  static cleanForSpeech(text: string): string {
    let clean = text;
    clean = clean.replace(/```[\s\S]*?```/g, '');
    clean = clean.replace(/`[^`]*`/g, '');
    clean = clean.replace(/<delegate[\s\S]*?<\/delegate>/gi, '');
    clean = clean.replace(/<delegate[\s\S]*$/gi, '');
    clean = clean.replace(/<tool_call[\s\S]*?<\/tool_call>/gi, '');
    clean = clean.replace(/<tool_call[\s\S]*$/gi, '');
    clean = clean.replace(/<tool_result[\s\S]*?<\/tool_result>/gi, '');
    clean = clean.replace(/^\s*\{[\s\S]*?\}\s*$/gm, '');
    clean = clean.replace(/\{"[^"]*":\s*(?:"[^"]*"|[^}])*\}/g, '');
    clean = clean.replace(/<[^>]+>/g, '');
    clean = clean.replace(/^\|.*\|$/gm, '');
    clean = clean.replace(/^[\s]*[-*_]{3,}[\s]*$/gm, '');
    clean = clean.replace(/^#{1,6}\s+/gm, '');
    clean = clean.replace(/\*{1,3}([^*]+)\*{1,3}/g, '$1');
    clean = clean.replace(/_{1,3}([^_]+)_{1,3}/g, '$1');
    clean = clean.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');
    clean = clean.replace(/!\[[^\]]*\]\([^)]+\)/g, '');
    clean = clean.replace(/https?:\/\/[^\s)]+/g, '');
    clean = clean.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{200D}\u{20E3}\u{E0020}-\u{E007F}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}]/gu, '');
    clean = clean.replace(/^([\s]*[-*•]\s+.+?)([^.!?:])$/gm, '$1$2.');
    clean = clean.replace(/^([\s]*\d+\.\s+.+?)([^.!?:])$/gm, '$1$2.');
    clean = clean.replace(/^[\s]*[-*•]\s+/gm, '');
    clean = clean.replace(/^[\s]*\d+\.\s+/gm, '');
    clean = clean.replace(/[~|>]/g, '');
    clean = clean.replace(/\n{2,}/g, '. ');
    clean = clean.replace(/\n/g, ' ');
    clean = clean.replace(/\s{2,}/g, ' ');
    clean = clean.replace(/\.{2,}/g, '.');
    clean = clean.replace(/\s*-\s*-\s*/g, ', ');
    return clean.trim();
  }
}

export const ttsService = new TtsService();
export function cleanTextForSpeech(text: string): string {
  return TtsService.cleanForSpeech(text);
}
