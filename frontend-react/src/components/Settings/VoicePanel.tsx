/**
 * VoicePanel — Voice, STT & TTS settings panel.
 *
 * Mirrors renderVoiceSection() + bindVoiceEvents() from
 * frontend/src/components/Settings/SettingsPage.ts (lines 749–2138).
 *
 * Features:
 *  - Built-in STT toggle (show/hide engine section)
 *  - STT engine selection: Native (Web Speech) | Whisper Local | Whisper Server
 *  - Whisper Local: model source tabs (HuggingFace model ID + presets | Local file)
 *    with live model status (loading / ready / error)
 *  - Whisper Server: model name input
 *  - Language select (shared across engines)
 *  - Auto-send toggle + wake word toggle
 *  - TTS enabled / auto-play / service URL / voice dropdown (grouped by language)
 *    with voice preview button
 *  - TTS speed slider + volume slider
 *  - Test TTS button (calls /api/settings/tts/speak)
 *  - Save button (PUT /api/settings)
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { useQuery, useMutation } from '@tanstack/react-query';
import { cn } from '../../lib/utils';
import { eventBus } from '../../utils/eventBus';
import { STT_EVENTS } from '../../utils/voiceEvents';
import { sttService } from '../../services/sttService';

// ── Types ──────────────────────────────────────────────────────────────────

type SttEngine = 'native' | 'whisper' | 'whisper_local';
type WhisperModelSource = 'huggingface' | 'local';

interface VoiceSettings {
  stt_builtin_enabled: boolean;
  stt_engine: SttEngine;
  stt_model: string;
  stt_language: string;
  stt_auto_send: boolean;
  whisper_model_id: string;
  whisper_model_source: WhisperModelSource;
  whisper_local_filename: string;
  tts_enabled: boolean;
  tts_auto_play: boolean;
  tts_url: string;
  tts_voice: string;
  tts_speed: number;
  volume: number;
  wake_word_enabled: boolean;
}

interface AppSettings {
  voice?: Partial<VoiceSettings>;
  [key: string]: unknown;
}

// ── Constants ──────────────────────────────────────────────────────────────

const WHISPER_MODEL_PRESETS = [
  { id: 'Xenova/whisper-tiny',   label: 'Whisper Tiny (~40MB, fastest)' },
  { id: 'Xenova/whisper-base',   label: 'Whisper Base (~75MB, fast)' },
  { id: 'Xenova/whisper-small',  label: 'Whisper Small (~250MB, balanced)' },
  { id: 'Xenova/whisper-medium', label: 'Whisper Medium (~750MB, accurate)' },
] as const;

const LANG_OPTIONS = [
  { value: 'auto', label: 'Auto' },
  { value: 'en',   label: 'English' },
  { value: 'fr',   label: 'French' },
  { value: 'es',   label: 'Spanish' },
  { value: 'de',   label: 'German' },
  { value: 'ja',   label: 'Japanese' },
  { value: 'zh',   label: 'Chinese' },
] as const;

const LANG_MAP: Record<string, string> = {
  auto: 'en-US', en: 'en-US', fr: 'fr-CA', es: 'es-ES',
  de: 'de-DE',   ja: 'ja-JP', zh: 'zh-CN',
};

const isMobilePlatform = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);

const DEFAULT_VOICE: VoiceSettings = {
  stt_builtin_enabled:   !isMobilePlatform,
  stt_engine:            'native',
  stt_model:             'medium',
  stt_language:          'auto',
  stt_auto_send:         false,
  whisper_model_id:      '',
  whisper_model_source:  'huggingface',
  whisper_local_filename: '',
  tts_enabled:           true,
  tts_auto_play:         false,
  tts_url:               'http://192.168.1.59:5500',
  tts_voice:             'default',
  tts_speed:             1.0,
  volume:                80,
  wake_word_enabled:     false,
};

// ── Helpers ────────────────────────────────────────────────────────────────

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('voxyflow_token');
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(url, { ...options, headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

// ── Sub-components ─────────────────────────────────────────────────────────

interface SettingRowProps {
  label: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
  column?: boolean;
}

function SettingRow({ label, description, children, column }: SettingRowProps) {
  return (
    <div
      className={cn(
        'setting-row py-4 border-b border-border last:border-0 gap-4',
        column
          ? 'flex flex-col items-start'
          : 'flex items-start justify-between',
      )}
    >
      <div className="setting-info min-w-0 shrink-0 w-52">
        <div className="setting-label text-sm font-medium text-foreground">{label}</div>
        {description && (
          <div className="setting-description text-xs text-muted-foreground mt-0.5">{description}</div>
        )}
      </div>
      {children && <div className="flex-1">{children}</div>}
    </div>
  );
}

interface PillGroupProps<T extends string> {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (v: T) => void;
}

function PillGroup<T extends string>({ options, value, onChange }: PillGroupProps<T>) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            'px-3 py-1 text-xs rounded-md border transition-colors',
            'border-border hover:border-[var(--color-accent,#6c5ce7)] hover:text-foreground',
            value === opt.value
              ? 'bg-[var(--color-accent,#6c5ce7)] text-white border-[var(--color-accent,#6c5ce7)] font-medium'
              : 'bg-transparent text-muted-foreground',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mt-6 mb-2 pb-1 border-b border-border">
      {children}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="relative inline-flex items-center cursor-pointer">
      <input
        type="checkbox"
        className="sr-only peer"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <div className={cn(
        'w-10 h-5 rounded-full transition-colors',
        'peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-[var(--color-accent,#6c5ce7)]',
        checked ? 'bg-[var(--color-accent,#6c5ce7)]' : 'bg-muted',
      )}>
        <div className={cn(
          'absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform',
          checked ? 'translate-x-5' : 'translate-x-0',
        )} />
      </div>
    </label>
  );
}

// ── Whisper Model Status hook ──────────────────────────────────────────────

type ModelStatus = 'idle' | 'loading' | 'ready' | 'error';

function useWhisperModelStatus(engine: SttEngine): { status: ModelStatus; message: string; progress: number } {
  const [status, setStatus] = useState<ModelStatus>('idle');
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (engine !== 'whisper_local') {
      setStatus('idle');
      setMessage('');
      setProgress(0);
      return;
    }

    // Reflect current state immediately
    if (sttService.modelReady) {
      setStatus('ready');
    } else if (sttService.whisperModel) {
      setStatus('loading');
    }

    const unsubStatus = eventBus.on(STT_EVENTS.MODEL_STATUS, (data: unknown) => {
      const { status: s, message: m } = data as { status: string; message?: string };
      if (s === 'loading') { setStatus('loading'); setMessage(''); }
      else if (s === 'ready') { setStatus('ready'); setMessage(''); setProgress(0); }
      else if (s === 'error') { setStatus('error'); setMessage(m ?? 'Error'); }
    });

    const unsubProgress = eventBus.on(STT_EVENTS.MODEL_PROGRESS, (data: unknown) => {
      const { progress: p } = data as { progress: number };
      setStatus('loading');
      setProgress(Math.round(p));
    });

    return () => {
      unsubStatus();
      unsubProgress();
    };
  }, [engine]);

  return { status, message, progress };
}

// ── VoicePanel ─────────────────────────────────────────────────────────────

export function VoicePanel() {
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [ttsTestStatus, setTtsTestStatus] = useState('');
  const [whisperLocalFile, setWhisperLocalFile] = useState<File | null>(null);
  const [browserVoices, setBrowserVoices] = useState<SpeechSynthesisVoice[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load settings
  const { data: rawSettings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => apiFetch<AppSettings>('/api/settings'),
  });

  const { control, reset, handleSubmit, setValue, watch } = useForm<VoiceSettings>({
    defaultValues: DEFAULT_VOICE,
  });

  // Populate form once settings loaded (merge backend + localStorage for frontend-only fields)
  useEffect(() => {
    if (!rawSettings) return;
    let localVoice: Partial<VoiceSettings> = {};
    try {
      const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
      localVoice = stored?.voice ?? {};
    } catch { /* ignore */ }
    reset({ ...DEFAULT_VOICE, ...(rawSettings.voice ?? {}), ...localVoice });
  }, [rawSettings, reset]);

  const sttEngine = watch('stt_engine');
  const sttBuiltinEnabled = watch('stt_builtin_enabled');
  const whisperModelSource = watch('whisper_model_source');
  const ttsSpeed = watch('tts_speed');
  const volume = watch('volume');

  const { status: modelStatus, message: modelMessage, progress: modelProgress } =
    useWhisperModelStatus(sttEngine);

  // Populate browser voices
  useEffect(() => {
    const populate = () => setBrowserVoices(speechSynthesis?.getVoices() ?? []);
    populate();
    if (typeof speechSynthesis !== 'undefined') {
      speechSynthesis.onvoiceschanged = populate;
    }
    return () => {
      if (typeof speechSynthesis !== 'undefined') {
        speechSynthesis.onvoiceschanged = null;
      }
    };
  }, []);

  // Apply STT engine change to service immediately
  const handleEngineChange = useCallback((engine: SttEngine) => {
    setValue('stt_engine', engine);
    const svcEngine = engine === 'native' ? 'webspeech' : engine;
    sttService.setEngine(svcEngine as 'webspeech' | 'whisper' | 'whisper_local');
    if (engine === 'whisper_local') {
      if (whisperLocalFile) {
        sttService.setWhisperModel(whisperLocalFile);
      } else {
        const modelId = (control._formValues as VoiceSettings).whisper_model_id;
        if (modelId?.trim()) sttService.setWhisperModel(modelId.trim());
      }
    }
  }, [setValue, whisperLocalFile, control]);

  // Apply language change to service immediately
  const handleLanguageChange = useCallback((lang: string) => {
    setValue('stt_language', lang);
    sttService.setLanguage(LANG_MAP[lang] ?? lang);
  }, [setValue]);

  // Apply whisper model ID to service on blur/change
  const handleWhisperModelIdChange = useCallback((modelId: string) => {
    setValue('whisper_model_id', modelId);
    if (sttService.currentEngine === 'whisper_local' && modelId.trim()) {
      sttService.setWhisperModel(modelId.trim());
    }
  }, [setValue]);

  // Local file selection
  const handleFileChange = useCallback((file: File) => {
    setWhisperLocalFile(file);
    setValue('whisper_local_filename', file.name);
    if (sttService.currentEngine === 'whisper_local') {
      sttService.setWhisperModel(file);
    }
  }, [setValue]);

  // TTS preview
  const handleVoicePreview = useCallback(() => {
    const voiceName = (control._formValues as VoiceSettings).tts_voice;
    if (!('speechSynthesis' in window)) return;
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance('Hello! This is a voice preview.');
    if (voiceName && voiceName !== 'default') {
      const match = speechSynthesis.getVoices().find((v) => v.name === voiceName);
      if (match) {
        utterance.voice = match;
        if (match.lang.startsWith('fr')) utterance.text = 'Bonjour! Ceci est un aperçu de la voix.';
      }
    }
    speechSynthesis.speak(utterance);
  }, [control]);

  // TTS test
  const handleTtsTest = useCallback(async () => {
    setTtsTestStatus('Testing…');
    try {
      const token = localStorage.getItem('voxyflow_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const res = await fetch('/api/settings/tts/speak', {
        method: 'POST',
        headers,
        body: JSON.stringify({ text: 'Voxyflow TTS test. Hello!', language: 'fr' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const audioUrl = URL.createObjectURL(blob);
      const audio = new Audio(audioUrl);
      audio.onended = () => URL.revokeObjectURL(audioUrl);
      await audio.play();
      setTtsTestStatus('✓ Playing');
      setTimeout(() => setTtsTestStatus(''), 3000);
    } catch {
      setTtsTestStatus('✗ Failed (server may be down)');
    }
  }, []);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async (voiceData: VoiceSettings) => {
      const current = await apiFetch<AppSettings>('/api/settings');
      return apiFetch<AppSettings>('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, voice: voiceData }),
      });
    },
    onMutate: () => setSaveStatus('saving'),
    onSuccess: (_data, voiceData) => {
      // Sync to localStorage so chat components pick up the change
      try {
        const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
        stored.voice = voiceData;
        localStorage.setItem('voxyflow_settings', JSON.stringify(stored));
      } catch { /* ignore */ }
      eventBus.emit('settings:changed');
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    },
    onError: () => {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 5000);
    },
  });

  const onSubmit = handleSubmit((data) => saveMutation.mutate(data));

  // Group browser voices by language
  const voiceGroups = (() => {
    const groups: Record<string, SpeechSynthesisVoice[]> = {};
    browserVoices.forEach((voice) => {
      const langKey = voice.lang.split('-')[0].toUpperCase();
      if (!groups[langKey]) groups[langKey] = [];
      groups[langKey].push(voice);
    });
    const priority = ['FR', 'EN', 'ES', 'DE'];
    const keys = Object.keys(groups).sort((a, b) => {
      const ai = priority.indexOf(a);
      const bi = priority.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return a.localeCompare(b);
    });
    return keys.map((k) => ({ lang: k, voices: groups[k] }));
  })();

  // Whisper model status badge
  const modelStatusBadge = (() => {
    if (sttEngine !== 'whisper_local') return null;
    if (modelStatus === 'loading') return (
      <span className="text-xs text-yellow-400 ml-2">
        ⏳ {modelProgress > 0 ? `${modelProgress}%` : 'Loading…'}
      </span>
    );
    if (modelStatus === 'ready') return <span className="text-xs text-green-400 ml-2">✅ Ready</span>;
    if (modelStatus === 'error') return <span className="text-xs text-red-400 ml-2">❌ {modelMessage || 'Error'}</span>;
    return null;
  })();

  return (
    <form
      onSubmit={onSubmit}
      className="voice-panel p-6 max-w-2xl"
      data-testid="settings-voice"
    >
      <h3 className="text-base font-semibold text-foreground mb-1">🎤 Voice</h3>
      <p className="text-xs text-muted-foreground mb-6">
        Configure speech-to-text, text-to-speech, and wake word detection.
      </p>

      {/* ── STT section ── */}
      <SectionLabel>Speech-to-Text (STT)</SectionLabel>

      <SettingRow
        label="Built-in STT"
        description={
          <>
            Show the mic button for in-app speech-to-text.
            {isMobilePlatform && (
              <><br /><em>Off by default on mobile — your keyboard already has a dictation mic.</em></>
            )}
          </>
        }
      >
        <Controller
          control={control}
          name="stt_builtin_enabled"
          render={({ field }) => (
            <Toggle checked={field.value} onChange={field.onChange} />
          )}
        />
      </SettingRow>

      {sttBuiltinEnabled && (
        <>
          <SettingRow
            label="Engine"
            description="Native: Web Speech API (fast, sends audio to Google) · Whisper Local: 🔒 private, runs in browser via WebAssembly · Whisper Server: server-side transcription"
          >
            <Controller
              control={control}
              name="stt_engine"
              render={({ field }) => (
                <PillGroup<SttEngine>
                  options={[
                    { value: 'native',        label: 'Native (Browser)' },
                    { value: 'whisper_local', label: '🔒 Whisper Local' },
                    { value: 'whisper',       label: 'Whisper (Server)' },
                  ]}
                  value={field.value}
                  onChange={(v) => {
                    field.onChange(v);
                    handleEngineChange(v);
                  }}
                />
              )}
            />
          </SettingRow>

          {/* Whisper Local config */}
          {sttEngine === 'whisper_local' && (
            <>
              <SettingRow
                label="Model Source"
                description={
                  <>
                    Choose where to load the Whisper model from{modelStatusBadge}
                  </>
                }
                column
              >
                <Controller
                  control={control}
                  name="whisper_model_source"
                  render={({ field }) => (
                    <PillGroup<WhisperModelSource>
                      options={[
                        { value: 'huggingface', label: '🤗 From HuggingFace' },
                        { value: 'local',       label: '📁 Local File' },
                      ]}
                      value={field.value}
                      onChange={field.onChange}
                    />
                  )}
                />
              </SettingRow>

              {whisperModelSource === 'huggingface' && (
                <>
                  <SettingRow
                    label="🤗 HuggingFace Model"
                    description="ONNX model identifier from HuggingFace Hub. Downloaded and cached in the browser."
                  >
                    <Controller
                      control={control}
                      name="whisper_model_id"
                      render={({ field }) => (
                        <input
                          type="text"
                          className="setting-input w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                          placeholder="onnx-community/whisper-small"
                          value={field.value}
                          onChange={field.onChange}
                          onBlur={(e) => handleWhisperModelIdChange(e.target.value)}
                        />
                      )}
                    />
                  </SettingRow>

                  <SettingRow label="Quick select" description="Click a preset to fill the model field" column>
                    <div className="flex flex-wrap gap-1.5">
                      {WHISPER_MODEL_PRESETS.map((preset) => (
                        <button
                          key={preset.id}
                          type="button"
                          title={preset.label}
                          onClick={() => {
                            setValue('whisper_model_id', preset.id);
                            handleWhisperModelIdChange(preset.id);
                          }}
                          className="px-2 py-0.5 text-xs rounded border border-border bg-muted hover:bg-accent hover:text-accent-foreground transition-colors"
                        >
                          {preset.id.split('/')[1] ?? preset.id}
                        </button>
                      ))}
                    </div>
                    <div className="mt-3 text-xs text-muted-foreground space-y-1">
                      <div className="font-medium">📖 Recommended models:</div>
                      <div>• <strong>onnx-community/whisper-small</strong> — Good balance, ~500MB, multilingual</div>
                      <div>• <strong>onnx-community/whisper-medium</strong> — Best for French, ~1.5GB</div>
                      <div>• <strong>onnx-community/whisper-tiny</strong> — Fastest, ~150MB, lower accuracy</div>
                      <div>• <strong>Xenova/whisper-small</strong> — Lighter alternative</div>
                      <div className="opacity-70 italic">First load downloads the model; subsequent loads use browser cache.</div>
                    </div>
                  </SettingRow>
                </>
              )}

              {whisperModelSource === 'local' && (
                <SettingRow
                  label="📁 Local Model File"
                  description="Select a Whisper model file from your disk (.bin, .gguf, .onnx). The file stays in memory for this session only."
                >
                  <div className="flex items-center gap-3">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".bin,.gguf,.onnx"
                      className="sr-only"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (file) handleFileChange(file);
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="px-3 py-1.5 text-xs rounded border border-border bg-muted hover:bg-accent hover:text-accent-foreground transition-colors whitespace-nowrap"
                    >
                      Browse…
                    </button>
                    <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                      {whisperLocalFile
                        ? whisperLocalFile.name
                        : watch('whisper_local_filename')
                          ? `${watch('whisper_local_filename')} (session expired — re-select)`
                          : 'No file selected'}
                    </span>
                  </div>
                </SettingRow>
              )}
            </>
          )}

          {/* Whisper Server: model name */}
          {sttEngine === 'whisper' && (
            <SettingRow
              label="Whisper Model"
              description="Model name (e.g. tiny, base, small, medium, large-v3, turbo)"
            >
              <Controller
                control={control}
                name="stt_model"
                render={({ field }) => (
                  <input
                    type="text"
                    className="setting-input w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                    placeholder="medium"
                    {...field}
                  />
                )}
              />
            </SettingRow>
          )}

          <SettingRow label="Language" description="Recognition language for all engines">
            <Controller
              control={control}
              name="stt_language"
              render={({ field }) => (
                <select
                  className="setting-select w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                  value={field.value}
                  onChange={(e) => {
                    field.onChange(e.target.value);
                    handleLanguageChange(e.target.value);
                  }}
                >
                  {LANG_OPTIONS.map(({ value, label }) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              )}
            />
          </SettingRow>

          <SettingRow
            label="Auto-send transcripts"
            description="When OFF, voice transcripts fill the input box for review before sending"
          >
            <Controller
              control={control}
              name="stt_auto_send"
              render={({ field }) => (
                <Toggle checked={field.value} onChange={field.onChange} />
              )}
            />
          </SettingRow>
        </>
      )}

      {/* ── Wake Word section ── */}
      <SectionLabel>Wake Word Detection</SectionLabel>

      <SettingRow
        label="Enable wake word mode by default"
        description="Start with wake word detection active (say wake word to trigger — Alexa, Hey Jarvis, etc.)"
      >
        <Controller
          control={control}
          name="wake_word_enabled"
          render={({ field }) => (
            <Toggle checked={field.value} onChange={field.onChange} />
          )}
        />
      </SettingRow>

      {/* ── TTS section ── */}
      <SectionLabel>Text-to-Speech (TTS)</SectionLabel>

      <SettingRow label="Enable TTS" description="Allow text-to-speech on assistant messages">
        <Controller
          control={control}
          name="tts_enabled"
          render={({ field }) => (
            <Toggle checked={field.value} onChange={field.onChange} />
          )}
        />
      </SettingRow>

      <SettingRow label="Auto-play responses" description="Read Voxy's responses aloud automatically">
        <Controller
          control={control}
          name="tts_auto_play"
          render={({ field }) => (
            <Toggle checked={field.value} onChange={field.onChange} />
          )}
        />
      </SettingRow>

      <SettingRow label="TTS Service URL" description="URL of your TTS server (XTTS, Coqui, etc.)">
        <Controller
          control={control}
          name="tts_url"
          render={({ field }) => (
            <input
              type="text"
              className="setting-input w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
              placeholder="http://192.168.1.59:5500"
              {...field}
            />
          )}
        />
      </SettingRow>

      <SettingRow label="Voice" description="Browser voice for text-to-speech (grouped by language)">
        <div className="flex items-center gap-2">
          <Controller
            control={control}
            name="tts_voice"
            render={({ field }) => (
              <select
                className="setting-select flex-1 min-w-0 rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                value={field.value}
                onChange={field.onChange}
              >
                <option value="default">Default</option>
                {voiceGroups.map(({ lang, voices }) => (
                  <optgroup key={lang} label={lang}>
                    {voices.map((v) => (
                      <option key={v.name} value={v.name}>
                        {v.name} ({v.lang})
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            )}
          />
          <button
            type="button"
            onClick={handleVoicePreview}
            title="Preview selected voice"
            className="px-2 py-1.5 text-xs rounded border border-border bg-muted hover:bg-accent hover:text-accent-foreground transition-colors whitespace-nowrap"
          >
            🔊 Preview
          </button>
        </div>
      </SettingRow>

      <SettingRow
        label="Speed"
        description={<>Playback speed — <span className="tabular-nums">{(ttsSpeed ?? 1.0).toFixed(1)}x</span></>}
      >
        <Controller
          control={control}
          name="tts_speed"
          render={({ field }) => (
            <input
              type="range"
              min="0.5" max="2.0" step="0.1"
              className="w-full accent-[var(--color-accent,#6c5ce7)]"
              value={field.value}
              onChange={(e) => field.onChange(parseFloat(e.target.value))}
            />
          )}
        />
      </SettingRow>

      {/* ── Volume section ── */}
      <SectionLabel>Volume</SectionLabel>

      <SettingRow
        label="Audio volume"
        description={<>TTS and notification volume — <span className="tabular-nums">{volume ?? 80}%</span></>}
      >
        <Controller
          control={control}
          name="volume"
          render={({ field }) => (
            <input
              type="range"
              min="0" max="100"
              className="w-full accent-[var(--color-accent,#6c5ce7)]"
              value={field.value}
              onChange={(e) => field.onChange(parseInt(e.target.value))}
            />
          )}
        />
      </SettingRow>

      {/* TTS test */}
      <div className="flex items-center gap-3 mt-4 mb-6">
        <button
          type="button"
          onClick={handleTtsTest}
          className="px-3 py-1.5 text-sm rounded border border-border bg-muted hover:bg-accent hover:text-accent-foreground transition-colors"
        >
          🔊 Test TTS
        </button>
        {ttsTestStatus && (
          <span className="text-xs text-muted-foreground">{ttsTestStatus}</span>
        )}
      </div>

      {/* ── Save bar ── */}
      <div className="flex items-center justify-between pt-4 border-t border-border">
        <span className="text-xs text-muted-foreground">
          {saveStatus === 'saving' && 'Saving…'}
          {saveStatus === 'saved'  && '✓ Saved'}
          {saveStatus === 'error'  && '✗ Save failed'}
        </span>
        <button
          type="submit"
          disabled={saveMutation.isPending}
          className={cn(
            'px-4 py-1.5 text-sm font-medium rounded transition-colors',
            'bg-[var(--color-accent,#6c5ce7)] text-white hover:opacity-90',
            'disabled:opacity-50 disabled:cursor-not-allowed',
          )}
        >
          Save
        </button>
      </div>
    </form>
  );
}
