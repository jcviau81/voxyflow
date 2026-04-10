import { useEffect, useRef, useState, useCallback } from 'react';
import { Mic, Square, Radio } from 'lucide-react';
import { Tooltip, TooltipProvider } from '../ui/tooltip';
import { eventBus } from '../../utils/eventBus';
import { VOICE_EVENTS, STT_EVENTS, type SttResult } from '../../utils/voiceEvents';
import { sttService } from '../../services/sttService';
import { ttsService } from '../../services/ttsService';
import {
  wakeWordService,
  WAKE_WORD_MODELS,
  DEFAULT_WAKE_WORD_MODEL_ID,
} from '../../services/wakeWordService';
import { useChatService } from '../../contexts/useChatService';
import { useTabStore } from '../../stores/useTabStore';
import { useSessionStore } from '../../stores/useSessionStore';
import { useToastStore } from '../../stores/useToastStore';
import { SYSTEM_PROJECT_ID } from '../../lib/constants';

const WAKE_WORD_SEND_DELAY_MS = 3000;

interface VoiceInputProps {
  sttBuiltinEnabled?: boolean;
  className?: string;
  /** Renders only the two action buttons (no indicators/transcript) for inline use */
  compact?: boolean;
}

export function VoiceInput({ sttBuiltinEnabled = true, className, compact = false }: VoiceInputProps) {
  const chat = useChatService();
  const showToast = useToastStore((s) => s.showToast);

  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [isModelLoading, setIsModelLoading] = useState(false);
  const [isTtsSpeaking, setIsTtsSpeaking] = useState(() => ttsService.isSpeaking);
  const [modelLoadMessage, setModelLoadMessage] = useState('Loading model…');
  const [modelProgress, setModelProgress] = useState<number | null>(null);
  const [wakeWordEnabled, setWakeWordEnabled] = useState(false);
  const [wakeWordPulsing, setWakeWordPulsing] = useState(false);
  const [wakeWordLabel, setWakeWordLabel] = useState<string>(() => {
    const fallback = WAKE_WORD_MODELS.find((m) => m.id === DEFAULT_WAKE_WORD_MODEL_ID)?.label
      ?? WAKE_WORD_MODELS[0].label;
    try {
      const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
      const id = stored?.voice?.wake_word_model as string | undefined;
      const match = id ? WAKE_WORD_MODELS.find((m) => m.id === id) : null;
      return match?.label ?? fallback;
    } catch {
      return fallback;
    }
  });
  const [transcript, setTranscript] = useState('');
  const [transcriptFinal, setTranscriptFinal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Mutable refs — don't need to trigger re-renders
  const autoSendBufferRef = useRef('');
  const wakeWordSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wakeWordSessionIdRef = useRef<string | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);

  // ── Helpers ────────────────────────────────────────────────────────────────

  const showError = useCallback((message: string) => {
    setError(message);
    setTimeout(() => setError(null), 5000);
  }, []);

  const playAckSound = useCallback(async () => {
    try {
      const ctx = new AudioContext();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(1320, ctx.currentTime + 0.08);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.25);
      await new Promise((r) => setTimeout(r, 300));
      ctx.close();
    } catch { /* ignore */ }
  }, []);

  const startRecording = useCallback(async () => {
    ttsService.stop();
    await sttService.startRecording();
  }, []);

  const stopRecording = useCallback(() => {
    sttService.stopRecording();
  }, []);

  const autoSendMessage = useCallback(() => {
    if (wakeWordSendTimerRef.current) {
      clearTimeout(wakeWordSendTimerRef.current);
      wakeWordSendTimerRef.current = null;
    }
    const text = autoSendBufferRef.current.trim();
    if (!text) return;

    const activeTab = useTabStore.getState().getActiveTab();
    const contextTabId = activeTab === 'main' ? SYSTEM_PROJECT_ID : activeTab;
    const sessionId = wakeWordSessionIdRef.current || useSessionStore.getState().getActiveChatId(contextTabId);
    chat.sendMessage(text, undefined, undefined, sessionId);
    eventBus.emit(VOICE_EVENTS.VOICE_MESSAGE_SENT);
    // Clear the chat input textarea (it was being filled live via
    // handleVoiceTranscript during wake-word transcription).
    chat.handleVoiceTranscript('', false);

    autoSendBufferRef.current = '';
    sttService.clearBuffer();
    setTranscript('');
    setTranscriptFinal(false);
    setWakeWordPulsing(false);

    if (sttService.recording) stopRecording();
  }, [chat, stopRecording]);

  const scheduleWakeWordRestart = useCallback(() => {
    if (!wakeWordEnabled) return;
    const doRestart = async () => {
      if (!wakeWordEnabled || wakeWordService.isListening() || sttService.recording) return;
      setWakeWordPulsing(false);
      await wakeWordService.start();
    };

    if (ttsService.isSpeaking) {
      // TTS is already playing — wait for it to finish
      const unsub = ttsService.onEnd(() => {
        unsub();
        setTimeout(doRestart, 500);
      });
      // Safety: restart after 30s regardless
      setTimeout(() => { unsub(); void doRestart(); }, 30000);
    } else {
      // TTS not yet playing — AI response may be on its way.
      // Subscribe to TTS start, then wait for TTS end before restarting.
      // Fallback: if TTS never starts (auto-play off), restart after 8s.
      let settled = false;
      let unsubStart: (() => void) | null = null;
      let unsubEnd: (() => void) | null = null;

      const finish = () => {
        if (settled) return;
        settled = true;
        unsubStart?.();
        unsubEnd?.();
        unsubStart = null;
        unsubEnd = null;
        setTimeout(doRestart, 500);
      };

      unsubStart = ttsService.onStart(() => {
        // TTS started — unsub from start, now wait for end
        unsubStart?.();
        unsubStart = null;
        unsubEnd = ttsService.onEnd(() => finish());
        // Safety: if TTS runs for too long, restart anyway
        setTimeout(finish, 30000);
      });

      // Fallback: if TTS never starts within 8s (auto-play disabled or no response)
      setTimeout(() => { if (!settled) finish(); }, 8000);
    }
  }, [wakeWordEnabled]);

  // ── Wake word toggle ───────────────────────────────────────────────────────

  const toggleWakeWord = useCallback(async () => {
    const next = !wakeWordEnabled;
    setWakeWordEnabled(next);

    if (next) {
      const activeTab = useTabStore.getState().getActiveTab();
      const contextTabId = activeTab === 'main' ? SYSTEM_PROJECT_ID : activeTab;
      wakeWordSessionIdRef.current = useSessionStore.getState().getActiveChatId(contextTabId);

      ttsService.forceNative = true;
      await wakeWordService.start();

      if ('wakeLock' in navigator) {
        try {
          wakeLockRef.current = await (navigator as Navigator & { wakeLock: { request: (type: string) => Promise<WakeLockSentinel> } }).wakeLock.request('screen');
        } catch { /* ignore */ }
      }

      showToast(`🎙️ Wake word mode enabled — say "${wakeWordLabel}" to start`, 'info', 4000);
    } else {
      ttsService.forceNative = false;
      await wakeWordService.stop();

      if (wakeLockRef.current) {
        await wakeLockRef.current.release();
        wakeLockRef.current = null;
      }

      showToast('🎙️ Wake word mode disabled', 'info', 3000);
    }

    // Persist preference
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const parsed = stored ? JSON.parse(stored) : {};
      if (!parsed.voice) parsed.voice = {};
      parsed.voice.wake_word_enabled = next;
      localStorage.setItem('voxyflow_settings', JSON.stringify(parsed));
    } catch { /* ignore */ }
  }, [wakeWordEnabled, wakeWordLabel, showToast]);

  // ── Sync selected wake word model from settings ────────────────────────────

  useEffect(() => {
    const applyFromStorage = () => {
      try {
        const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
        const id = (stored?.voice?.wake_word_model as string | undefined) ?? DEFAULT_WAKE_WORD_MODEL_ID;
        const match = WAKE_WORD_MODELS.find((m) => m.id === id) ?? WAKE_WORD_MODELS[0];
        setWakeWordLabel(match.label);
        void wakeWordService.setModel(match.id);
      } catch { /* ignore */ }
    };
    applyFromStorage();
    const unsub = eventBus.on('settings:changed', applyFromStorage);
    return () => { unsub(); };
  }, []);

  // ── Event bus subscriptions ────────────────────────────────────────────────

  useEffect(() => {
    const unsubs: Array<() => void> = [];

    // Wake word detected
    unsubs.push(
      eventBus.on(VOICE_EVENTS.WAKEWORD_DETECTED, async (data: unknown) => {
        if (!wakeWordEnabled || sttService.recording) return;
        const { modelLabel, score } = (data ?? {}) as { modelLabel?: string; score?: number };
        const label = modelLabel ?? wakeWordLabel;
        await wakeWordService.stop();
        await playAckSound();
        showToast(`✨ Wake word detected — ${label} (${score?.toFixed(2) ?? '?'})`, 'success', 3000);
        setWakeWordPulsing(true);
        await sttService.startRecording();
      }),
    );

    // Wake word error
    unsubs.push(
      eventBus.on(VOICE_EVENTS.WAKEWORD_ERROR, (data: unknown) => {
        const { message } = data as { message: string };
        showError(message);
      }),
    );

    // Transcript updates
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_TRANSCRIPT, (result: unknown) => {
        const { transcript: text, isFinal } = result as SttResult;
        setTranscript(text);
        setTranscriptFinal(isFinal);

        // Forward to ChatProvider so the live transcript shows up in the
        // chat input textarea. In wake-word mode we force isFinal=false so
        // ChatProvider's stt_auto_send path doesn't fire — the wake-word
        // auto-send handler below owns that flow.
        chat.handleVoiceTranscript(text, wakeWordEnabled ? false : isFinal);

        // Wake word mode: buffer finals and debounce auto-send
        if (wakeWordEnabled && text.trim()) {
          if (isFinal) autoSendBufferRef.current = text;

          if (wakeWordSendTimerRef.current) clearTimeout(wakeWordSendTimerRef.current);

          if (autoSendBufferRef.current.trim()) {
            wakeWordSendTimerRef.current = setTimeout(() => {
              wakeWordSendTimerRef.current = null;
              if (autoSendBufferRef.current.trim()) autoSendMessage();
            }, WAKE_WORD_SEND_DELAY_MS);
          }
        }
      }),
    );

    // Voice error
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_ERROR, (data: unknown) => {
        const { message } = data as { message: string };
        showError(message);
        setIsRecording(false);
        setIsTranscribing(false);
      }),
    );

    // Recording started
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_START, () => {
        setIsRecording(true);
        setIsTranscribing(false);
      }),
    );

    // Recording stopped
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_STOP, () => {
        setIsRecording(false);
        if (sttService.currentEngine === 'whisper' || sttService.currentEngine === 'whisper_local') {
          setIsTranscribing(true);
        }
        if (wakeWordEnabled && !wakeWordService.isListening()) {
          scheduleWakeWordRestart();
        }
        chat.handleVoiceStop();
      }),
    );

    // Transcribing in progress
    unsubs.push(eventBus.on(STT_EVENTS.TRANSCRIBING, () => setIsTranscribing(true)));
    unsubs.push(eventBus.on(STT_EVENTS.TRANSCRIBE_DONE, () => setIsTranscribing(false)));

    // Model loading
    unsubs.push(
      eventBus.on(STT_EVENTS.MODEL_STATUS, (data: unknown) => {
        const { status, message } = data as { status: string; message?: string };
        if (status === 'loading') {
          setIsModelLoading(true);
          setModelLoadMessage(message || 'Loading model…');
        } else {
          setIsModelLoading(false);
          if (status === 'error') showError(`Model error: ${message || 'unknown'}`);
        }
      }),
    );

    // Model download progress
    unsubs.push(
      eventBus.on(STT_EVENTS.MODEL_PROGRESS, (data: unknown) => {
        const { progress } = data as { progress: number };
        setModelProgress(progress);
      }),
    );

    // Auto-send recording stop signal
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_RECORDING_STOP, () => {
        if (sttService.recording) stopRecording();
      }),
    );

    // Voice buffer cleared (hide transcript)
    unsubs.push(
      eventBus.on(VOICE_EVENTS.VOICE_BUFFER_UPDATE, (data: unknown) => {
        const { text } = data as { text: string };
        if (!text) { setTranscript(''); setTranscriptFinal(false); }
      }),
    );

    return () => unsubs.forEach((unsub) => unsub());
  }, [wakeWordEnabled, wakeWordLabel, chat, showError, playAckSound, showToast, autoSendMessage, scheduleWakeWordRestart, stopRecording]);

  // ── TTS speaking indicator ─────────────────────────────────────────────────

  useEffect(() => {
    const unsubStart = ttsService.onStart(() => setIsTtsSpeaking(true));
    const unsubEnd = ttsService.onEnd(() => setIsTtsSpeaking(false));
    return () => { unsubStart(); unsubEnd(); };
  }, []);

  // ── Keyboard shortcut Alt+V ────────────────────────────────────────────────

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        if (sttService.recording) stopRecording();
        else startRecording();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [startRecording, stopRecording]);

  // ── Load persisted wake word preference ──────────────────────────────────

  useEffect(() => {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (parsed?.voice?.wake_word_enabled) {
          setWakeWordEnabled(true);
          // Start wake word asynchronously
          const activeTab = useTabStore.getState().getActiveTab();
          const contextTabId = activeTab === 'main' ? SYSTEM_PROJECT_ID : activeTab;
          wakeWordSessionIdRef.current = useSessionStore.getState().getActiveChatId(contextTabId);
          ttsService.forceNative = true;
          wakeWordService.start().catch(() => {});
        }
      }
    } catch { /* ignore */ }

    // Show one-time engine hint
    if (sttService.currentEngine === 'webspeech') {
      const hintShown = localStorage.getItem('voxyflow_stt_hint_shown');
      if (!hintShown) {
        try {
          const stored = localStorage.getItem('voxyflow_settings');
          if (stored) {
            const settings = JSON.parse(stored);
            if (settings?.whisper_model_id) return;
          }
        } catch { /* ignore */ }
        setTimeout(() => {
          showToast('💡 Configure a local Whisper model in Settings for private, offline transcription.', 'info', 8000);
          localStorage.setItem('voxyflow_stt_hint_shown', '1');
        }, 3000);
      }
    }

    return () => {
      if (wakeLockRef.current) {
        wakeLockRef.current.release().catch(() => {});
        wakeLockRef.current = null;
      }
      if (wakeWordEnabled) wakeWordService.stop().catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── PTT / toggle handlers ─────────────────────────────────────────────────

  const handlePttClick = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault();
    if (sttService.recording) stopRecording();
    else startRecording();
  }, [startRecording, stopRecording]);

  // ── Indicator label ───────────────────────────────────────────────────────

  const indicatorLabel = isModelLoading
    ? modelProgress !== null
      ? `Loading model… ${Math.round(modelProgress)}%`
      : modelLoadMessage
    : isTranscribing
    ? 'Transcribing…'
    : isTtsSpeaking
    ? 'Speaking…'
    : 'Recording...';

  const showIndicator = isRecording || isTranscribing || isModelLoading || isTtsSpeaking;

  // ── PTT button tooltip ────────────────────────────────────────────────────


  // ── Render ────────────────────────────────────────────────────────────────

  const buttons = (
    <TooltipProvider>
      <div className="voice-buttons flex items-center gap-1">
        {sttBuiltinEnabled && (
          <Tooltip content={isRecording ? 'Recording… click to stop' : sttService.currentEngine === 'whisper_local' ? 'Push to talk (hold) · Alt+V · Whisper Local' : 'Push to talk (hold) · Alt+V'}>
            <button
              type="button"
              className={`voice-btn p-2 rounded-lg transition-colors${isRecording ? ' recording bg-red-500 text-white' : ' hover:bg-muted text-muted-foreground'}`}
              onClick={handlePttClick}
              aria-label={isRecording ? 'Stop recording' : 'Click to talk (Alt+V)'}
            >
              {isRecording ? <Square size={16} /> : <Mic size={16} />}
            </button>
          </Tooltip>
        )}

        <Tooltip content={wakeWordEnabled ? `Wake word ON — say "${wakeWordLabel}" to start` : `Wake word mode — say "${wakeWordLabel}" to start recording`}>
          <button
            type="button"
            className={`wake-word-btn p-2 rounded-lg transition-colors${wakeWordEnabled ? ' active bg-primary text-primary-foreground' : ' hover:bg-muted text-muted-foreground'}${wakeWordPulsing ? ' animate-pulse' : ''}`}
            onClick={toggleWakeWord}
            aria-label={wakeWordEnabled ? 'Disable wake word mode' : 'Enable wake word mode'}
          >
            <Radio size={16} />
          </button>
        </Tooltip>
      </div>
    </TooltipProvider>
  );

  if (compact) return buttons;

  return (
    <div className={`voice-input flex flex-col gap-1${className ? ` ${className}` : ''}`} data-testid="voice-input-btn">
      {/* Buttons row */}
      {buttons}

      {/* Recording / transcribing / TTS speaking indicator */}
      {showIndicator && (
        <div className={`voice-indicator flex items-center gap-1.5 text-xs text-muted-foreground${isModelLoading ? ' model-loading' : ''}`}>
          <span className={`recording-dot w-2 h-2 rounded-full animate-pulse ${isTtsSpeaking && !isRecording && !isTranscribing ? 'bg-primary' : 'bg-red-500'}`} />
          <span className="voice-indicator-label">{indicatorLabel}</span>
          {isTtsSpeaking && !isRecording && (
            <button
              type="button"
              className="ml-1 text-xs underline hover:no-underline text-muted-foreground hover:text-foreground"
              onClick={() => ttsService.stop()}
              title="Stop TTS"
            >
              stop
            </button>
          )}
        </div>
      )}

      {/* Transcript display */}
      {transcript && (
        <div className={`voice-transcript text-xs px-2 py-1 rounded bg-muted text-muted-foreground max-w-xs truncate${transcriptFinal ? ' final font-medium' : ''}`}>
          {transcript}
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="voice-error text-xs text-destructive px-2 py-1 rounded bg-destructive/10">
          {error}
        </div>
      )}
    </div>
  );
}
