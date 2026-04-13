/**
 * ModelPanel — Models & Ollama settings panel.
 *
 * Mirrors renderModelsSection() + renderModelLayerRow() + bindModelEvents()
 * from frontend/src/components/Settings/SettingsPage.ts (lines 562–1815).
 *
 * Features:
 *  - Two model layers: Fast, Deep
 *  - Per-layer: provider type (Claude / Ollama / OpenAI-compatible), URL, API key, model
 *  - Global Ollama URL with health-check / model-fetch button
 *  - Dynamic dropdown when Ollama models are fetched
 *  - Thinking-model badge (⚡) for models that emit <think> tokens
 *  - Test button per layer with latency / error feedback
 *  - Save button (PUT /api/settings)
 */

import { useState, useEffect, useCallback } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { useQuery, useMutation } from '@tanstack/react-query';

// ── Types ──────────────────────────────────────────────────────────────────

type ProviderType = 'claude' | 'ollama' | 'openai_compatible';
type LayerKey = 'fast' | 'deep';

interface ModelLayerConfig {
  enabled: boolean;
  provider_type: ProviderType;
  provider_url: string;
  api_key: string;
  model: string;
}

interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;
  default_worker_model: string;
}

interface AppSettings {
  models?: ModelsSettings;
  [key: string]: unknown;
}

interface OllamaModel {
  name: string;
  size_gb: number;
}

interface TestResult {
  success: boolean;
  latency_ms?: number;
}

// ── Constants ──────────────────────────────────────────────────────────────

const THINKING_MODELS = ['claude-sonnet-4', 'claude-opus-4', 'deepseek-r', 'qwq', 'o1', 'o3'];

const DEFAULT_LAYER: ModelLayerConfig = {
  enabled: true,
  provider_type: 'claude',
  provider_url: 'https://api.anthropic.com',
  api_key: '',
  model: '',
};

const DEFAULT_MODELS: ModelsSettings = {
  fast:     { ...DEFAULT_LAYER, model: 'claude-sonnet-4' },
  deep:     { ...DEFAULT_LAYER, model: 'claude-opus-4' },
  default_worker_model: 'sonnet',
};

const LAYER_META: Record<LayerKey, { label: string; placeholder: string; showEnabled: boolean }> = {
  fast:     { label: '⚡ Fast',     placeholder: 'claude-sonnet-4',  showEnabled: false },
  deep:     { label: '🧠 Deep',     placeholder: 'claude-opus-4',    showEnabled: true  },
};

// ── Helpers ────────────────────────────────────────────────────────────────

function isThinkingModel(model: string): boolean {
  const lower = (model || '').toLowerCase();
  return THINKING_MODELS.some((t) => lower.includes(t.toLowerCase()));
}

function detectProviderType(url: string, model: string): ProviderType {
  const u = (url || '').toLowerCase();
  const m = (model || '').toLowerCase();
  if (u.includes('anthropic') || m.includes('claude')) return 'claude';
  if (u.includes('11434') || (m && !m.includes('claude') && u.includes('ollama'))) return 'ollama';
  return 'openai_compatible';
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── ModelLayerRow ──────────────────────────────────────────────────────────

interface ModelLayerRowProps {
  layerKey: LayerKey;
  control: ReturnType<typeof useForm<ModelsSettings>>['control'];
  watch: ReturnType<typeof useForm<ModelsSettings>>['watch'];
  setValue: ReturnType<typeof useForm<ModelsSettings>>['setValue'];
  ollamaModels: OllamaModel[];
  ollamaUrl: string;
}

function ModelLayerRow({ layerKey, control, watch, setValue, ollamaModels, ollamaUrl }: ModelLayerRowProps) {
  const meta = LAYER_META[layerKey];
  const prefix = layerKey as LayerKey;

  const providerType = useWatch({ control, name: `${prefix}.provider_type` as const });
  const modelValue   = useWatch({ control, name: `${prefix}.model` as const });

  const isClaude  = providerType === 'claude';
  const isOllama  = providerType === 'ollama';
  const showUrl   = !isClaude;
  const showKey   = !isClaude && !isOllama;
  const thinking  = isThinkingModel(modelValue ?? '');
  const showModelDropdown = isOllama && ollamaModels.length > 0;

  const [testState, setTestState] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testLatency, setTestLatency] = useState<number | null>(null);

  // Auto-fill URL / key when provider changes
  useEffect(() => {
    if (isClaude) {
      setValue(`${prefix}.provider_url`, 'https://api.anthropic.com');
      setValue(`${prefix}.api_key`, '');
    } else if (isOllama) {
      setValue(`${prefix}.provider_url`, ollamaUrl.replace(/\/$/, '') + '/v1');
      setValue(`${prefix}.api_key`, 'ollama');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerType]);

  async function handleTest() {
    setTestState('testing');
    setTestLatency(null);
    const vals = watch();
    const layer = vals[prefix];
    try {
      const data = await apiFetch<TestResult>('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_url: layer.provider_url,
          api_key: layer.api_key,
          model: layer.model,
        }),
      });
      if (data.success) {
        setTestState('ok');
        setTestLatency(data.latency_ms ?? null);
      } else {
        setTestState('fail');
      }
    } catch {
      setTestState('fail');
    } finally {
      setTimeout(() => setTestState('idle'), 5000);
    }
  }

  return (
    <div
      className="model-layer-row grid items-start gap-2 py-2 border-b border-border last:border-0"
      style={{ gridTemplateColumns: '100px 160px 1fr auto auto' }}
      data-layer={layerKey}
    >
      {/* Layer label + enabled toggle */}
      <div className="flex items-center gap-1.5">
        {meta.showEnabled && (
          <Controller
            control={control}
            name={`${prefix}.enabled`}
            render={({ field }) => (
              <input
                type="checkbox"
                className="setting-checkbox"
                checked={field.value}
                onChange={field.onChange}
              />
            )}
          />
        )}
        <span className="text-sm font-medium">{meta.label}</span>
      </div>

      {/* Provider type */}
      <Controller
        control={control}
        name={`${prefix}.provider_type`}
        render={({ field }) => (
          <select
            className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-full"
            value={field.value}
            onChange={field.onChange}
          >
            <option value="claude">Claude (Anthropic)</option>
            <option value="ollama">Ollama (local)</option>
            <option value="openai_compatible">OpenAI-compatible</option>
          </select>
        )}
      />

      {/* Model + URL + Key stack */}
      <div className="flex flex-col gap-1 min-w-0">
        {/* Model field: dropdown for Ollama (with models), text input otherwise */}
        {showModelDropdown ? (
          <Controller
            control={control}
            name={`${prefix}.model`}
            render={({ field }) => (
              <select
                className="setting-input text-sm rounded border border-input bg-background px-2 py-1"
                value={field.value}
                onChange={field.onChange}
              >
                <option value="">Select model...</option>
                {ollamaModels.map((om) => (
                  <option key={om.name} value={om.name}>
                    {om.name} ({om.size_gb} GB)
                  </option>
                ))}
              </select>
            )}
          />
        ) : (
          <Controller
            control={control}
            name={`${prefix}.model`}
            render={({ field }) => (
              <input
                type="text"
                className="setting-input text-sm rounded border border-input bg-background px-2 py-1"
                placeholder={meta.placeholder}
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        )}

        {thinking && (
          <div className="text-xs" style={{ color: 'var(--color-accent)' }}>
            ⚡ Thinking model — /no_think applied automatically
          </div>
        )}

        {showUrl && (
          <Controller
            control={control}
            name={`${prefix}.provider_url`}
            render={({ field }) => (
              <input
                type="text"
                className="setting-input text-sm rounded border border-input bg-background px-2 py-1"
                placeholder="https://api.example.com/v1"
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        )}

        {showKey && (
          <Controller
            control={control}
            name={`${prefix}.api_key`}
            render={({ field }) => (
              <input
                type="password"
                className="setting-input text-sm rounded border border-input bg-background px-2 py-1"
                placeholder="API key"
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        )}
      </div>

      {/* Test button */}
      <button
        type="button"
        className="btn-secondary text-xs px-2 py-1 rounded border border-border hover:bg-accent"
        disabled={testState === 'testing'}
        onClick={handleTest}
      >
        {testState === 'testing' ? 'Testing…' : 'Test'}
      </button>

      {/* Test result */}
      <div className="text-xs w-14 text-right">
        {testState === 'ok' && (
          <span className="text-green-400">{testLatency != null ? `${testLatency}ms` : 'OK'}</span>
        )}
        {testState === 'fail' && (
          <span className="text-red-400">Failed</span>
        )}
        {testState === 'testing' && (
          <span className="text-muted-foreground">…</span>
        )}
      </div>
    </div>
  );
}

// ── ModelPanel ─────────────────────────────────────────────────────────────

export function ModelPanel() {
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434');
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([]);
  const [ollamaStatus, setOllamaStatus] = useState<'idle' | 'checking' | 'ok' | 'empty' | 'fail'>('idle');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  // Load settings
  const { data: rawSettings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => apiFetch<AppSettings>('/api/settings'),
  });

  const { control, reset, watch, setValue, handleSubmit } = useForm<ModelsSettings>({
    defaultValues: DEFAULT_MODELS,
  });

  // Populate form once settings loaded
  useEffect(() => {
    if (!rawSettings) return;
    const dm = DEFAULT_MODELS;
    const sm = (rawSettings.models || {}) as Partial<ModelsSettings>;
    const merged: ModelsSettings = {
      fast:     { ...dm.fast,     ...(sm.fast     || {}) },
      deep:     { ...dm.deep,     ...(sm.deep     || {}) },
      default_worker_model: sm.default_worker_model ?? dm.default_worker_model,
    };
    reset(merged);

    // Detect Ollama URL from existing settings
    for (const k of ['fast', 'deep'] as LayerKey[]) {
      const purl = merged[k]?.provider_url || '';
      if (purl.includes('11434') || purl.toLowerCase().includes('ollama')) {
        const base = purl.replace('/v1', '').replace(/\/$/, '');
        setOllamaUrl(base);
        break;
      }
    }
  }, [rawSettings, reset]);

  // Auto-fetch Ollama models if any layer uses Ollama
  useEffect(() => {
    if (!rawSettings) return;
    const sm = (rawSettings.models || {}) as Partial<ModelsSettings>;
    const hasOllama = (['fast', 'deep'] as LayerKey[]).some((l) => {
      const m = sm[l];
      return m && detectProviderType(m.provider_url, m.model) === 'ollama';
    });
    if (hasOllama) fetchOllamaModels();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawSettings]);

  const fetchOllamaModels = useCallback(async () => {
    setOllamaStatus('checking');
    try {
      const models = await apiFetch<OllamaModel[]>(
        `/api/models/ollama?url=${encodeURIComponent(ollamaUrl)}`,
      );
      setOllamaModels(models);
      setOllamaStatus(models.length > 0 ? 'ok' : 'empty');
    } catch {
      setOllamaModels([]);
      setOllamaStatus('fail');
    }
  }, [ollamaUrl]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async (modelsData: ModelsSettings) => {
      const current = await apiFetch<AppSettings>('/api/settings');
      return apiFetch<AppSettings>('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, models: modelsData }),
      });
    },
    onMutate: () => setSaveStatus('saving'),
    onSuccess: () => {
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 3000);
    },
    onError: () => {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 4000);
    },
  });

  const onSubmit = (data: ModelsSettings) => saveMutation.mutate(data);

  const ollamaStatusEl = (() => {
    switch (ollamaStatus) {
      case 'checking': return <span className="text-muted-foreground">Checking…</span>;
      case 'ok':       return <span className="text-green-400">Connected ({ollamaModels.length} models)</span>;
      case 'empty':    return <span className="text-yellow-400">Connected but no models found</span>;
      case 'fail':     return <span className="text-red-400">Unreachable</span>;
      default:         return null;
    }
  })();

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Models</h3>
        <p className="text-xs text-muted-foreground">
          Assign any model from any provider to each layer independently.
        </p>
      </div>

      {/* ── Global Ollama URL ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <label className="text-xs font-medium whitespace-nowrap">Ollama URL:</label>
        <input
          type="text"
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1 flex-1 min-w-40"
          value={ollamaUrl}
          placeholder="http://localhost:11434"
          onChange={(e) => setOllamaUrl(e.target.value)}
        />
        <button
          type="button"
          className="btn-secondary text-xs px-2 py-1 rounded border border-border hover:bg-accent whitespace-nowrap"
          disabled={ollamaStatus === 'checking'}
          onClick={fetchOllamaModels}
        >
          {ollamaStatus === 'checking' ? 'Checking…' : 'Refresh models'}
        </button>
        <span className="text-xs">{ollamaStatusEl}</span>
      </div>

      {/* ── Layer table header ── */}
      <div
        className="grid text-xs font-medium text-muted-foreground pb-1 border-b border-border"
        style={{ gridTemplateColumns: '100px 160px 1fr auto auto' }}
      >
        <div>Layer</div>
        <div>Provider</div>
        <div>Model / Endpoint</div>
        <div />
        <div />
      </div>

      {/* ── Layer rows ── */}
      <div className="flex flex-col">
        {(['fast', 'deep'] as LayerKey[]).map((key) => (
          <ModelLayerRow
            key={key}
            layerKey={key}
            control={control}
            watch={watch}
            setValue={setValue}
            ollamaModels={ollamaModels}
            ollamaUrl={ollamaUrl}
          />
        ))}
      </div>

      {/* ── Default worker model ── */}
      <div className="flex items-center gap-3">
        <label className="text-xs font-medium whitespace-nowrap">Default worker model:</label>
        <Controller
          control={control}
          name="default_worker_model"
          render={({ field }) => (
            <select
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1"
              value={field.value}
              onChange={field.onChange}
            >
              <option value="haiku">Haiku (fast / cheap)</option>
              <option value="sonnet">Sonnet (balanced)</option>
              <option value="opus">Opus (powerful)</option>
            </select>
          )}
        />
        <span className="text-xs text-muted-foreground">
          Model used for background workers and card execution
        </span>
      </div>

      {/* ── Save button ── */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          className="btn-primary text-sm px-4 py-1.5 rounded"
          disabled={saveStatus === 'saving'}
        >
          {saveStatus === 'saving' ? 'Saving…' : 'Save'}
        </button>
        {saveStatus === 'saved'  && <span className="text-xs text-green-400">✓ Saved</span>}
        {saveStatus === 'error'  && <span className="text-xs text-red-400">✗ Save failed</span>}
      </div>

    </form>
  );
}
