/**
 * TtsService — Text-to-speech via browser speechSynthesis API.
 *
 * Usage:
 *   ttsService.speak("Hello!")   // Uses speechSynthesis.speak()
 *   ttsService.stop()            // Stops current playback
 *   ttsService.isSpeaking        // true while audio is playing
 *
 * Settings (from voxyflow_settings in localStorage):
 *   voice.tts_enabled    — master toggle
 *   voice.tts_auto_play  — auto-speak assistant responses
 *   voice.tts_voice      — voice name (e.g. "Google français", "default")
 *
 * 100% browser-side. No server calls.
 */

import { eventBus } from '../utils/EventBus';
import { EVENTS } from '../utils/constants';

class TtsService {
  private _isSpeaking = false;
  private _onEndCallbacks: Array<() => void> = [];
  private _voices: SpeechSynthesisVoice[] = [];
  private _voicesLoaded = false;

  constructor() {
    this._loadVoices();
    // Voices load asynchronously in most browsers
    if (typeof speechSynthesis !== 'undefined') {
      speechSynthesis.onvoiceschanged = () => this._loadVoices();
    }
  }

  private _loadVoices(): void {
    if (typeof speechSynthesis === 'undefined') return;
    this._voices = speechSynthesis.getVoices();
    this._voicesLoaded = this._voices.length > 0;
  }

  get isSpeaking(): boolean {
    return this._isSpeaking;
  }

  /** Returns whether TTS is enabled in app settings. */
  get isEnabled(): boolean {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.tts_enabled !== false;
      }
      return true;
    } catch {
      return true;
    }
  }

  /** Returns whether auto-play is enabled (auto-speak assistant responses). */
  get isAutoPlay(): boolean {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.tts_auto_play === true;
      }
      return false;
    } catch {
      return false;
    }
  }

  /** Get the configured voice name from settings. */
  private get configuredVoiceName(): string {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.tts_voice || 'default';
      }
    } catch {}
    return 'default';
  }

  /** Get available browser voices. */
  getVoices(): SpeechSynthesisVoice[] {
    if (!this._voicesLoaded) this._loadVoices();
    return this._voices;
  }

  /** Find the best matching voice for the configured name + language. */
  private _resolveVoice(): SpeechSynthesisVoice | null {
    const voices = this.getVoices();
    if (voices.length === 0) return null;

    const name = this.configuredVoiceName;

    // Exact match by name
    if (name && name !== 'default') {
      const exact = voices.find(v => v.name === name);
      if (exact) return exact;
      // Partial match
      const partial = voices.find(v => v.name.toLowerCase().includes(name.toLowerCase()));
      if (partial) return partial;
    }

    // Detect language from settings
    const lang = this._getLanguage();

    // Find a voice matching the language
    const langMatch = voices.find(v => v.lang.startsWith(lang.split('-')[0]));
    if (langMatch) return langMatch;

    // Fallback to default
    const defaultVoice = voices.find(v => v.default);
    return defaultVoice || voices[0] || null;
  }

  private _getLanguage(): string {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        const lang = settings?.personality?.preferred_language;
        if (lang === 'en') return 'en-US';
        if (lang === 'fr') return 'fr-CA';
      }
    } catch {}
    return 'en-US';
  }

  /**
   * Speak the given text using browser speechSynthesis.
   * Respects tts_enabled setting. Does nothing if disabled or text is empty.
   */
  speak(text: string): void {
    if (!text.trim()) return;
    if (typeof speechSynthesis === 'undefined') {
      console.warn('[TtsService] speechSynthesis not available');
      return;
    }

    // Stop any current speech
    this.stop();

    // Clean text for speech (remove markdown formatting)
    const cleanText = this._cleanForSpeech(text);
    if (!cleanText.trim()) return;

    const utterance = new SpeechSynthesisUtterance(cleanText);
    const voice = this._resolveVoice();
    if (voice) {
      utterance.voice = voice;
      utterance.lang = voice.lang;
    } else {
      utterance.lang = this._getLanguage();
    }

    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    utterance.onstart = () => {
      this._isSpeaking = true;
    };

    utterance.onend = () => {
      this._isSpeaking = false;
      this._notifyEnd();
    };

    utterance.onerror = (event) => {
      // 'interrupted' and 'canceled' are normal when stop() is called
      if (event.error !== 'interrupted' && event.error !== 'canceled') {
        console.warn('[TtsService] Speech error:', event.error);
      }
      this._isSpeaking = false;
      this._notifyEnd();
    };

    this._isSpeaking = true;
    speechSynthesis.speak(utterance);
  }

  /**
   * Speak if auto-play is enabled and TTS is enabled.
   * Called automatically when an assistant message is received.
   */
  speakIfAutoPlay(text: string): void {
    if (this.isEnabled && this.isAutoPlay) {
      this.speak(text);
    }
  }

  /** Stop current speech. */
  stop(): void {
    if (typeof speechSynthesis !== 'undefined') {
      speechSynthesis.cancel();
    }
    if (this._isSpeaking) {
      this._isSpeaking = false;
      this._notifyEnd();
    }
  }

  /** Register a callback for when playback ends. Returns unsubscribe function. */
  onEnd(cb: () => void): () => void {
    this._onEndCallbacks.push(cb);
    return () => {
      this._onEndCallbacks = this._onEndCallbacks.filter(x => x !== cb);
    };
  }

  /** Clean markdown/code from text before speaking. */
  private _cleanForSpeech(text: string): string {
    return text
      // Remove code blocks
      .replace(/```[\s\S]*?```/g, ' code block ')
      // Remove inline code
      .replace(/`[^`]+`/g, (m) => m.slice(1, -1))
      // Remove markdown bold/italic
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/\*([^*]+)\*/g, '$1')
      .replace(/__([^_]+)__/g, '$1')
      .replace(/_([^_]+)_/g, '$1')
      // Remove markdown headers
      .replace(/^#{1,6}\s+/gm, '')
      // Remove markdown links, keep text
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
      // Remove image syntax
      .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
      // Remove bullet points
      .replace(/^[-*+]\s+/gm, '')
      // Collapse multiple newlines
      .replace(/\n{2,}/g, '. ')
      .replace(/\n/g, ' ')
      // Collapse multiple spaces
      .replace(/\s{2,}/g, ' ')
      .trim();
  }

  private _notifyEnd(): void {
    for (const cb of this._onEndCallbacks) {
      try { cb(); } catch { /* ignore */ }
    }
  }
}

export const ttsService = new TtsService();
