import { useEffect, useRef, useState, useCallback } from 'react';
import { Mic, Square, Radio } from 'lucide-react';
import { Tooltip, TooltipProvider } from '../ui/tooltip';
import { eventBus } from '../../utils/eventBus';
import { VOICE_EVENTS, STT_EVENTS, type SttResult } from '../../utils/voiceEvents';
import { sttService } from '../../services/sttService';
import { ttsService } from '../../services/ttsService';
import { wakeWordService } from '../../services/wakeWordService';
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
  const [modelLoadMessage, setModelLoadMessage] = useState('Loading model…');
  const [modelProgress, setModelProgress] = useState<number | null>(null);
  const [wakeWordEnabled, setWakeWordEnabled] = useState(false);
  const [wakeWordPulsing, setWakeWordPulsing] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [transcriptFinal, setTranscriptFinal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Mutable refs — don't need to trigger re-renders
  const autoSendBufferRef = useRef('');
  const wakeWordSendTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wakeWordSessionIdRef = useRef<string | null>(null);
  const wakeLockRef = useRef<WakeLockSentinel | null>(null);
  const isMobile = useRef(/Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || window.innerWidth <= 768 || 'ontouchstart' in window).current;

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

  const startRecording = useCallback(() => {
    ttsService.stop();
    sttService.startRecording();
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
      const unsub = ttsService.onEnd(() => {
        unsub();
        setTimeout(doRestart, 500);
      });
      // Safety timeout
      setTimeout(doRestart, 30000);
    } else {
      setTimeout(doRestart, 1000);
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

      showToast('🎙️ Wake word mode enabled - say "Alexa" to start', 'info', 4000);
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
  }, [wakeWordEnabled, showToast]);

  // ── Event bus subscriptions ────────────────────────────────────────────────

  useEffect(() => {
    const unsubs: Array<() => void> = [];

    // Wake word detected
    unsubs.push(
      eventBus.on(VOICE_EVENTS.WAKEWORD_DETECTED, async () => {
        if (!wakeWordEnabled || sttService.recording) return;
        await wakeWordService.stop();
        await playAckSound();
        showToast('✨ Listening...', 'success', 3000);
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

        // Forward to ChatProvider for non-wake-word mode (fills input field)
        if (!wakeWordEnabled) {
          chat.handleVoiceTranscript(text, isFinal);
        }

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
  }, [wakeWordEnabled, chat, showError, playAckSound, showToast, autoSendMessage, scheduleWakeWordRestart, stopRecording]);

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

  const handlePttMouseDown = useCallback(() => startRecording(), [startRecording]);
  const handlePttMouseUp = useCallback(() => stopRecording(), [stopRecording]);
  const handlePttMouseLeave = useCallback(() => { if (sttService.recording) stopRecording(); }, [stopRecording]);
  const handlePttTouchStart = useCallback((e: React.TouchEvent) => {
    e.preventDefault();
    if (sttService.recording) stopRecording();
    else startRecording();
  }, [startRecording, stopRecording]);
  const handlePttClick = useCallback((e: React.MouseEvent) => {
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
    : 'Recording...';

  const showIndicator = isRecording || isTranscribing || isModelLoading;

  // ── PTT button tooltip ────────────────────────────────────────────────────


  // ── Render ────────────────────────────────────────────────────────────────

  const buttons = (
    <TooltipProvider>
      <div className="voice-buttons flex items-center gap-1">
        {sttBuiltinEnabled && (
          <Tooltip content={isRecording ? 'Recording… click to stop' : sttService.currentEngine === 'whisper_local' ? 'Push to talk (hold) · Alt+V · Whisper Local' : 'Push to talk (hold) · Alt+V'}>
            {isMobile ? (
              <button
                type="button"
                className={`voice-btn p-2 rounded-lg transition-colors${isRecording ? ' recording bg-red-500 text-white' : ' hover:bg-muted text-muted-foreground'}`}
                onTouchStart={handlePttTouchStart}
                onClick={handlePttClick}
                aria-label={isRecording ? 'Stop recording' : 'Start recording'}
              >
                {isRecording ? <Square size={16} /> : <Mic size={16} />}
              </button>
            ) : (
              <button
                type="button"
                className={`voice-btn p-2 rounded-lg transition-colors${isRecording ? ' recording bg-red-500 text-white' : ' hover:bg-muted text-muted-foreground'}`}
                onMouseDown={handlePttMouseDown}
                onMouseUp={handlePttMouseUp}
                onMouseLeave={handlePttMouseLeave}
                aria-label={isRecording ? 'Stop recording' : 'Hold to talk (Alt+V)'}
              >
                {isRecording ? <Square size={16} /> : <Mic size={16} />}
              </button>
            )}
          </Tooltip>
        )}

        <Tooltip content={wakeWordEnabled ? 'Wake word ON — say "Alexa" to start' : 'Wake word mode — say "Alexa" to start recording'}>
          <button
            type="button"
            className={`wake-word-btn p-2 rounded-lg transition-colors${wakeWordEnabled ? ' active bg-purple-500 text-white' : ' hover:bg-muted text-muted-foreground'}${wakeWordPulsing ? ' animate-pulse' : ''}`}
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

      {/* Recording / transcribing indicator */}
      {showIndicator && (
        <div className={`voice-indicator flex items-center gap-1.5 text-xs text-muted-foreground${isModelLoading ? ' model-loading' : ''}`}>
          <span className="recording-dot w-2 h-2 rounded-full bg-red-500 animate-pulse" />
          <span className="voice-indicator-label">{indicatorLabel}</span>
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
