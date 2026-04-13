/**
 * ModelPanel — Models & Providers settings panel.
 *
 * Features:
 *  - Two model layers: Fast ⚡, Deep 🧠
 *  - Per-layer: provider selection, URL, API key, model (with dynamic listing)
 *  - Dynamic provider list fetched from /api/models/providers
 *  - Model listing for Ollama, OpenAI, Groq, etc. via /api/models/list
 *  - Capability badges per model (tools, vision, context window)
 *  - Test button per layer with latency feedback
 *  - Provider status indicators (reachable / unreachable)
 *  - Save button (PUT /api/settings)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { useQuery, useMutation } from '@tanstack/react-query';

// ── Types ──────────────────────────────────────────────────────────────────

type LayerKey = 'fast' | 'deep';

interface ModelLayerConfig {
  enabled: boolean;
  provider_type: string;  // "cli" | "anthropic" | "ollama" | "openai" | "groq" | ...
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

interface ProviderMeta {
  type: string;
  label: string;
  requires_key: boolean;
  local: boolean;
  default_url: string;
}

interface ModelCapabilities {
  model: string;
  provider: string;
  supports_tools: boolean;
  supports_vision: boolean;
  context_window: number;
  max_output_tokens: number;
}

interface TestResult {
  success: boolean;
  latency_ms?: number;
  reply?: string;
  error?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────

const THINKING_MODELS = ['claude-sonnet-4', 'claude-opus-4', 'deepseek-r', 'qwq', 'o1', 'o3'];

const DEFAULT_LAYER: ModelLayerConfig = {
  enabled: true,
  provider_type: 'cli',
  provider_url: '',
  api_key: '',
  model: '',
};

const DEFAULT_MODELS: ModelsSettings = {
  fast: { ...DEFAULT_LAYER, model: 'claude-sonnet-4' },
  deep: { ...DEFAULT_LAYER, model: 'claude-opus-4' },
  default_worker_model: 'sonnet',
};

const LAYER_META: Record<LayerKey, { label: string; placeholder: string; showEnabled: boolean }> = {
  fast: { label: '⚡ Fast',  placeholder: 'claude-sonnet-4', showEnabled: false },
  deep: { label: '🧠 Deep',  placeholder: 'claude-opus-4',  showEnabled: true  },
};

// Providers that don't need a URL field (managed internally or CLI-based)
const NO_URL_PROVIDERS = new Set(['cli', 'anthropic']);
// Providers that don't need an API key
const NO_KEY_PROVIDERS = new Set(['cli', 'ollama', 'lmstudio']);
// Providers that support dynamic model listing
const LISTABLE_PROVIDERS = new Set(['ollama', 'openai', 'groq', 'mistral', 'lmstudio', 'gemini']);

// ── Helpers ────────────────────────────────────────────────────────────────

function isThinkingModel(model: string): boolean {
  const lower = (model || '').toLowerCase();
  return THINKING_MODELS.some((t) => lower.includes(t.toLowerCase()));
}

function formatContext(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M ctx`;
  if (tokens >= 1_000)     return `${(tokens / 1_000).toFixed(0)}k ctx`;
  return `${tokens} ctx`;
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── CapabilityBadges ───────────────────────────────────────────────────────

function CapabilityBadges({ model }: { model: string }) {
  const [caps, setCaps] = useState<ModelCapabilities | null>(null);

  useEffect(() => {
    if (!model) { setCaps(null); return; }
    const controller = new AbortController();
    fetch(`/api/models/capabilities?model=${encodeURIComponent(model)}`, { signal: controller.signal })
      .then(r => r.ok ? r.json() : null)
      .then(d => setCaps(d))
      .catch(() => {});
    return () => controller.abort();
  }, [model]);

  if (!caps || !model) return null;

  return (
    <div className="flex gap-1 flex-wrap mt-0.5">
      {caps.supports_tools && (
        <span className="text-xs px-1 rounded" style={{ background: 'var(--color-accent)', color: '#fff', opacity: 0.85 }}>
          🔧 tools
        </span>
      )}
      {caps.supports_vision && (
        <span className="text-xs px-1 rounded" style={{ background: 'var(--color-accent)', color: '#fff', opacity: 0.85 }}>
          👁 vision
        </span>
      )}
      {caps.context_window > 0 && (
        <span className="text-xs px-1 rounded bg-muted text-muted-foreground">
          {formatContext(caps.context_window)}
        </span>
      )}
      {!caps.supports_tools && (
        <span className="text-xs px-1 rounded bg-muted text-yellow-400">
          ⚠ no tools
        </span>
      )}
    </div>
  );
}

// ── ModelLayerRow ──────────────────────────────────────────────────────────

interface ModelLayerRowProps {
  layerKey: LayerKey;
  control: ReturnType<typeof useForm<ModelsSettings>>['control'];
  watch: ReturnType<typeof useForm<ModelsSettings>>['watch'];
  setValue: ReturnType<typeof useForm<ModelsSettings>>['setValue'];
  providers: ProviderMeta[];
}

function ModelLayerRow({ layerKey, control, watch, setValue, providers }: ModelLayerRowProps) {
  const meta = LAYER_META[layerKey];
  const prefix = layerKey;

  const providerType = useWatch({ control, name: `${prefix}.provider_type` as const });
  const providerUrl  = useWatch({ control, name: `${prefix}.provider_url`  as const });
  const modelValue   = useWatch({ control, name: `${prefix}.model`         as const });

  const providerMeta  = providers.find(p => p.type === providerType);
  const showUrl       = !NO_URL_PROVIDERS.has(providerType);
  const showKey       = !NO_KEY_PROVIDERS.has(providerType) && providerMeta?.requires_key !== false;
  const canListModels = LISTABLE_PROVIDERS.has(providerType);
  const thinking      = isThinkingModel(modelValue ?? '');

  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading]     = useState(false);
  const [testState, setTestState]             = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testLatency, setTestLatency]         = useState<number | null>(null);
  const [testError, setTestError]             = useState<string>('');
  const prevProviderType = useRef(providerType);

  // Auto-fill URL when provider changes
  useEffect(() => {
    if (providerType === prevProviderType.current) return;
    prevProviderType.current = providerType;

    const meta = providers.find(p => p.type === providerType);
    if (meta?.default_url) {
      setValue(`${prefix}.provider_url`, meta.default_url);
    } else {
      setValue(`${prefix}.provider_url`, '');
    }
    // Clear key for no-key providers
    if (NO_KEY_PROVIDERS.has(providerType)) {
      setValue(`${prefix}.api_key`, providerType === 'ollama' ? 'ollama' : '');
    }
    // Clear model when switching provider
    setValue(`${prefix}.model`, '');
    setAvailableModels([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerType]);

  // Fetch model list when provider or URL changes
  const fetchModels = useCallback(async () => {
    if (!canListModels) return;
    setModelsLoading(true);
    try {
      const url = `/api/models/list?provider_type=${encodeURIComponent(providerType)}&url=${encodeURIComponent(providerUrl || '')}`;
      const models = await apiFetch<string[]>(url);
      setAvailableModels(models);
    } catch {
      setAvailableModels([]);
    } finally {
      setModelsLoading(false);
    }
  }, [canListModels, providerType, providerUrl]);

  // Auto-fetch for local providers (Ollama, LM Studio) on mount
  useEffect(() => {
    if (canListModels && (providerType === 'ollama' || providerType === 'lmstudio')) {
      fetchModels();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerType]);

  async function handleTest() {
    setTestState('testing');
    setTestLatency(null);
    setTestError('');
    const vals = watch();
    const layer = vals[prefix];
    try {
      const data = await apiFetch<TestResult>('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: layer.provider_type,
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
        setTestError(data.error?.slice(0, 80) || 'Failed');
      }
    } catch (e) {
      setTestState('fail');
      setTestError(String(e).slice(0, 80));
    } finally {
      setTimeout(() => { setTestState('idle'); setTestError(''); }, 6000);
    }
  }

  const showModelDropdown = canListModels && availableModels.length > 0;

  return (
    <div className="py-3 border-b border-border last:border-0 flex flex-col gap-2" data-layer={layerKey}>
      {/* Row header */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Layer label + enabled toggle */}
        <div className="flex items-center gap-1.5 w-16 shrink-0">
          {meta.showEnabled && (
            <Controller
              control={control}
              name={`${prefix}.enabled`}
              render={({ field }) => (
                <input type="checkbox" className="setting-checkbox" checked={field.value} onChange={field.onChange} />
              )}
            />
          )}
          <span className="text-sm font-medium">{meta.label}</span>
        </div>

        {/* Provider select */}
        <Controller
          control={control}
          name={`${prefix}.provider_type`}
          render={({ field }) => (
            <select
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-44 shrink-0"
              value={field.value}
              onChange={field.onChange}
            >
              {providers.length === 0 && <option value="">Loading…</option>}
              {providers.map((p) => (
                <option key={p.type} value={p.type}>{p.label}</option>
              ))}
            </select>
          )}
        />

        {/* Model field */}
        <div className="flex-1 min-w-36">
          {showModelDropdown ? (
            <Controller
              control={control}
              name={`${prefix}.model`}
              render={({ field }) => (
                <select
                  className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-full"
                  value={field.value}
                  onChange={field.onChange}
                >
                  <option value="">Select model…</option>
                  {availableModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
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
                  className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-full"
                  placeholder={meta.placeholder}
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
          )}
        </div>

        {/* Refresh models button (listable providers) */}
        {canListModels && (
          <button
            type="button"
            className="btn-secondary text-xs px-2 py-1 rounded border border-border hover:bg-accent shrink-0"
            disabled={modelsLoading}
            onClick={fetchModels}
            title="Refresh model list"
          >
            {modelsLoading ? '…' : '↻'}
          </button>
        )}

        {/* Test button */}
        <button
          type="button"
          className="btn-secondary text-xs px-2 py-1 rounded border border-border hover:bg-accent shrink-0"
          disabled={testState === 'testing'}
          onClick={handleTest}
        >
          {testState === 'testing' ? 'Testing…' : 'Test'}
        </button>

        {/* Test result */}
        <div className="text-xs w-20 shrink-0">
          {testState === 'ok'   && <span className="text-green-400">{testLatency != null ? `✓ ${testLatency}ms` : '✓ OK'}</span>}
          {testState === 'fail' && <span className="text-red-400" title={testError}>✗ Failed</span>}
          {testState === 'testing' && <span className="text-muted-foreground">…</span>}
        </div>
      </div>

      {/* Secondary fields: URL + API key */}
      {(showUrl || showKey) && (
        <div className="ml-20 flex flex-col gap-1">
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
      )}

      {/* Capability badges + thinking model note */}
      <div className="ml-20 flex flex-col gap-0.5">
        <CapabilityBadges model={modelValue ?? ''} />
        {thinking && (
          <div className="text-xs" style={{ color: 'var(--color-accent)' }}>
            ⚡ Thinking model — /no_think applied automatically
          </div>
        )}
        {testState === 'fail' && testError && (
          <div className="text-xs text-red-400 truncate max-w-md">{testError}</div>
        )}
      </div>
    </div>
  );
}

// ── ProviderStatusDot ──────────────────────────────────────────────────────

function ProviderStatusDot({ reachable }: { reachable: boolean | null }) {
  if (reachable === null) return <span className="w-2 h-2 rounded-full bg-muted inline-block" />;
  return (
    <span
      className="w-2 h-2 rounded-full inline-block"
      style={{ background: reachable ? '#22c55e' : '#ef4444' }}
      title={reachable ? 'Reachable' : 'Unreachable'}
    />
  );
}

// ── ModelPanel ─────────────────────────────────────────────────────────────

export function ModelPanel() {
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  // Fetch provider list from backend
  const { data: providers = [] } = useQuery<ProviderMeta[]>({
    queryKey: ['providers'],
    queryFn: () => apiFetch<ProviderMeta[]>('/api/models/providers'),
    staleTime: 60_000,
  });

  // Fetch provider reachability
  const { data: availableData } = useQuery({
    queryKey: ['models-available'],
    queryFn: () => apiFetch<{ layers: unknown; providers: Record<string, { reachable: boolean; label: string }> }>('/api/models/available'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

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
      fast: { ...dm.fast, ...(sm.fast || {}) },
      deep: { ...dm.deep, ...(sm.deep || {}) },
      default_worker_model: sm.default_worker_model ?? dm.default_worker_model,
    };
    reset(merged);
  }, [rawSettings, reset]);

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

  // Build reachability map from available data
  const reachabilityMap = availableData?.providers ?? {};

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Models & Providers</h3>
        <p className="text-xs text-muted-foreground">
          Assign any model from any provider to each layer independently.
          Supports Claude (CLI or API), Ollama, OpenAI, Groq, Mistral, Gemini, LM Studio, and any OpenAI-compatible endpoint.
        </p>
      </div>

      {/* ── Provider status overview ── */}
      {providers.filter(p => p.type !== 'cli').length > 0 && (
        <div className="flex flex-wrap gap-3">
          {providers.filter(p => p.type !== 'cli').map((p) => {
            const status = reachabilityMap[p.type];
            return (
              <div key={p.type} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ProviderStatusDot reachable={status?.reachable ?? null} />
                <span>{p.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Layer rows ── */}
      <div className="flex flex-col">
        {(['fast', 'deep'] as LayerKey[]).map((key) => (
          <ModelLayerRow
            key={key}
            layerKey={key}
            control={control}
            watch={watch}
            setValue={setValue}
            providers={providers}
          />
        ))}
      </div>

      {/* ── Default worker model ── */}
      <div className="flex items-center gap-3 flex-wrap">
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
        {saveStatus === 'saved' && <span className="text-xs text-green-400">✓ Saved</span>}
        {saveStatus === 'error' && <span className="text-xs text-red-400">✗ Save failed</span>}
      </div>

    </form>
  );
}
