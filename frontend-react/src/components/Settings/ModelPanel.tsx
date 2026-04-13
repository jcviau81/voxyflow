/**
 * ModelPanel — Models & Providers settings panel.
 *
 * Features:
 *  - Named endpoints: add any machine/URL as a reusable endpoint with a friendly name
 *  - Two model layers: Fast ⚡, Deep 🧠
 *  - Per-layer: choose from named endpoints OR generic cloud provider
 *  - Dynamic model listing per endpoint/provider
 *  - Capability badges per model (tools, vision, context window)
 *  - Test button per layer with latency feedback
 *  - Provider status indicators (reachable / unreachable)
 *  - Save button (PUT /api/settings)
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

// ── Types ──────────────────────────────────────────────────────────────────

type LayerKey = 'fast' | 'deep';

/** A named, saved endpoint (a machine or remote server). */
interface ProviderEndpoint {
  id: string;
  name: string;
  provider_type: string;
  url: string;
  api_key: string;
}

interface ModelLayerConfig {
  enabled: boolean;
  provider_type: string;
  provider_url: string;
  api_key: string;
  model: string;
  endpoint_id: string;    // if set, use the saved endpoint with this id
}

interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;
  default_worker_model: string;
  endpoints: ProviderEndpoint[];
}

interface AppSettings {
  models?: Partial<ModelsSettings>;
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

interface EndpointStatus {
  id: string;
  name: string;
  provider_type: string;
  url: string;
  reachable: boolean;
}

interface AvailableData {
  layers: unknown;
  providers: Record<string, { reachable: boolean; label: string }>;
  endpoints: EndpointStatus[];
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
  endpoint_id: '',
};

const DEFAULT_MODELS: ModelsSettings = {
  fast: { ...DEFAULT_LAYER, model: 'claude-sonnet-4' },
  deep: { ...DEFAULT_LAYER, model: 'claude-opus-4' },
  default_worker_model: 'sonnet',
  endpoints: [],
};

const LAYER_META: Record<LayerKey, { label: string; placeholder: string; showEnabled: boolean }> = {
  fast: { label: '⚡ Fast',  placeholder: 'claude-sonnet-4', showEnabled: false },
  deep: { label: '🧠 Deep',  placeholder: 'claude-opus-4',  showEnabled: true  },
};

// Cloud providers that don't need a URL field
const NO_URL_PROVIDERS = new Set(['cli', 'anthropic']);
// Local providers that don't need an API key
const NO_KEY_PROVIDERS = new Set(['cli', 'ollama', 'lmstudio']);
// Providers that support dynamic model listing
const LISTABLE_PROVIDERS = new Set(['ollama', 'openai', 'groq', 'mistral', 'lmstudio', 'gemini']);
// Local provider types (shown in endpoint type picker)
const LOCAL_PROVIDER_TYPES = new Set(['ollama', 'lmstudio', 'openai']);

function newId() {
  return crypto.randomUUID();
}

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

// ── StatusDot ──────────────────────────────────────────────────────────────

function StatusDot({ reachable }: { reachable: boolean | null }) {
  if (reachable === null) return <span className="w-2 h-2 rounded-full bg-muted inline-block" />;
  return (
    <span
      className="w-2 h-2 rounded-full inline-block shrink-0"
      style={{ background: reachable ? '#22c55e' : '#ef4444' }}
      title={reachable ? 'Reachable' : 'Unreachable'}
    />
  );
}

// ── EndpointsManager ───────────────────────────────────────────────────────

interface EndpointsManagerProps {
  endpoints: ProviderEndpoint[];
  onChange: (endpoints: ProviderEndpoint[]) => void;
  providers: ProviderMeta[];
  endpointStatuses: EndpointStatus[];
}

function EndpointsManager({ endpoints, onChange, providers, endpointStatuses }: EndpointsManagerProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProviderEndpoint | null>(null);
  const [pingState, setPingState] = useState<Record<string, 'idle' | 'testing' | 'ok' | 'fail'>>({});

  const localProviders = providers.filter(p => LOCAL_PROVIDER_TYPES.has(p.type));

  function startAdd() {
    const ep: ProviderEndpoint = {
      id: newId(),
      name: '',
      provider_type: 'ollama',
      url: 'http://192.168.1.x:11434',
      api_key: '',
    };
    setDraft(ep);
    setEditingId(ep.id);
  }

  function startEdit(ep: ProviderEndpoint) {
    setDraft({ ...ep });
    setEditingId(ep.id);
  }

  function cancelEdit() {
    setDraft(null);
    setEditingId(null);
  }

  function saveEdit() {
    if (!draft) return;
    const existing = endpoints.find(e => e.id === draft.id);
    if (existing) {
      onChange(endpoints.map(e => e.id === draft.id ? draft : e));
    } else {
      onChange([...endpoints, draft]);
    }
    setDraft(null);
    setEditingId(null);
  }

  function removeEndpoint(id: string) {
    onChange(endpoints.filter(e => e.id !== id));
  }

  async function pingEndpoint(ep: ProviderEndpoint) {
    setPingState(s => ({ ...s, [ep.id]: 'testing' }));
    try {
      const result = await apiFetch<TestResult>('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: ep.provider_type,
          provider_url: ep.url,
          api_key: ep.api_key,
          model: '',  // just reachability check — backend will return error on empty model but we only care about success/error type
        }),
      });
      // A "model is required" error still means the server is up
      const up = result.success || (result.error ?? '').toLowerCase().includes('model');
      setPingState(s => ({ ...s, [ep.id]: up ? 'ok' : 'fail' }));
    } catch {
      setPingState(s => ({ ...s, [ep.id]: 'fail' }));
    } finally {
      setTimeout(() => setPingState(s => ({ ...s, [ep.id]: 'idle' })), 5000);
    }
  }

  const statusById = Object.fromEntries(endpointStatuses.map(s => [s.id, s]));

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">My Endpoints</span>
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent"
          onClick={startAdd}
        >
          + Add endpoint
        </button>
      </div>

      {endpoints.length === 0 && editingId === null && (
        <p className="text-xs text-muted-foreground italic">
          No endpoints yet. Add a machine running Ollama, LM Studio, or any OpenAI-compatible server.
        </p>
      )}

      {/* Existing endpoints list */}
      {endpoints.map(ep => {
        const isEditing = editingId === ep.id;
        const status = statusById[ep.id];
        const ping = pingState[ep.id] ?? 'idle';

        if (isEditing && draft) {
          return (
            <EndpointEditor
              key={ep.id}
              draft={draft}
              localProviders={localProviders}
              onChange={setDraft}
              onSave={saveEdit}
              onCancel={cancelEdit}
            />
          );
        }

        return (
          <div key={ep.id} className="flex items-center gap-2 text-sm px-2 py-1.5 rounded border border-border bg-background/50">
            <StatusDot reachable={status ? status.reachable : null} />
            <span className="font-medium min-w-0 truncate flex-1">{ep.name || ep.url}</span>
            <span className="text-xs text-muted-foreground shrink-0">{ep.provider_type}</span>
            <span className="text-xs text-muted-foreground shrink-0 truncate max-w-[160px]">{ep.url}</span>

            {/* Ping button */}
            <button
              type="button"
              className="text-xs px-1.5 py-0.5 rounded border border-border hover:bg-accent shrink-0"
              onClick={() => pingEndpoint(ep)}
              disabled={ping === 'testing'}
              title="Test reachability"
            >
              {ping === 'testing' ? '…' : ping === 'ok' ? '✓' : ping === 'fail' ? '✗' : '⚡'}
            </button>

            <button
              type="button"
              className="text-xs px-1.5 py-0.5 rounded border border-border hover:bg-accent shrink-0"
              onClick={() => startEdit(ep)}
            >
              Edit
            </button>
            <button
              type="button"
              className="text-xs px-1.5 py-0.5 rounded border border-border hover:bg-accent text-red-400 shrink-0"
              onClick={() => removeEndpoint(ep.id)}
            >
              ✕
            </button>
          </div>
        );
      })}

      {/* New endpoint form (no existing id) */}
      {editingId !== null && draft && !endpoints.find(e => e.id === editingId) && (
        <EndpointEditor
          draft={draft}
          localProviders={localProviders}
          onChange={setDraft}
          onSave={saveEdit}
          onCancel={cancelEdit}
        />
      )}
    </div>
  );
}

// ── EndpointEditor ─────────────────────────────────────────────────────────

interface EndpointEditorProps {
  draft: ProviderEndpoint;
  localProviders: ProviderMeta[];
  onChange: (ep: ProviderEndpoint) => void;
  onSave: () => void;
  onCancel: () => void;
}

function EndpointEditor({ draft, localProviders, onChange, onSave, onCancel }: EndpointEditorProps) {
  const set = (key: keyof ProviderEndpoint, value: string) => onChange({ ...draft, [key]: value });

  return (
    <div className="flex flex-col gap-1.5 p-2.5 rounded border border-border bg-background shadow-sm">
      <div className="flex gap-2 flex-wrap">
        {/* Name */}
        <input
          type="text"
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1 flex-1 min-w-32"
          placeholder='Name, e.g. "Mac Studio — Ollama"'
          value={draft.name}
          onChange={e => set('name', e.target.value)}
          autoFocus
        />
        {/* Provider type */}
        <select
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-36 shrink-0"
          value={draft.provider_type}
          onChange={e => {
            const pt = e.target.value;
            const meta = localProviders.find(p => p.type === pt);
            onChange({ ...draft, provider_type: pt, url: meta?.default_url ?? draft.url });
          }}
        >
          {localProviders.map(p => <option key={p.type} value={p.type}>{p.label}</option>)}
          <option value="openai">OpenAI-compatible</option>
        </select>
      </div>

      {/* URL */}
      <input
        type="text"
        className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-full"
        placeholder="http://192.168.1.x:11434"
        value={draft.url}
        onChange={e => set('url', e.target.value)}
      />

      {/* API key (only for openai-compat that needs it) */}
      {!NO_KEY_PROVIDERS.has(draft.provider_type) && (
        <input
          type="password"
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-full"
          placeholder="API key (optional)"
          value={draft.api_key}
          onChange={e => set('api_key', e.target.value)}
        />
      )}

      <div className="flex gap-2 justify-end mt-0.5">
        <button type="button" className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="text-xs px-3 py-0.5 rounded border border-border hover:bg-accent font-medium"
          onClick={onSave}
          disabled={!draft.url.trim()}
        >
          Save endpoint
        </button>
      </div>
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
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
}

function ModelLayerRow({ layerKey, control, watch, setValue, providers, endpoints, endpointStatuses }: ModelLayerRowProps) {
  const meta = LAYER_META[layerKey];
  const prefix = layerKey;

  const providerType = useWatch({ control, name: `${prefix}.provider_type` as const });
  const providerUrl  = useWatch({ control, name: `${prefix}.provider_url`  as const });
  const endpointId   = useWatch({ control, name: `${prefix}.endpoint_id`   as const });
  const modelValue   = useWatch({ control, name: `${prefix}.model`         as const });

  // Resolve effective provider type and URL (from endpoint or direct config)
  const activeEndpoint = endpoints.find(e => e.id === endpointId);
  const effectiveType  = activeEndpoint ? activeEndpoint.provider_type : providerType;
  const effectiveUrl   = activeEndpoint ? activeEndpoint.url : providerUrl;

  const providerMeta  = providers.find(p => p.type === effectiveType);
  const showUrl       = !endpointId && !NO_URL_PROVIDERS.has(providerType);
  const showKey       = !endpointId && !NO_KEY_PROVIDERS.has(providerType) && providerMeta?.requires_key !== false;
  const canListModels = LISTABLE_PROVIDERS.has(effectiveType);
  const thinking      = isThinkingModel(modelValue ?? '');

  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading]     = useState(false);
  const [testState, setTestState]             = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testLatency, setTestLatency]         = useState<number | null>(null);
  const [testError, setTestError]             = useState<string>('');
  const prevSelection = useRef('');

  // The "selection key" — either endpoint id or provider type
  const selectionValue = endpointId ? `ep:${endpointId}` : `pt:${providerType}`;

  // Handle selection dropdown change
  function handleSelectionChange(value: string) {
    if (value.startsWith('ep:')) {
      const id = value.slice(3);
      const ep = endpoints.find(e => e.id === id);
      if (ep) {
        setValue(`${prefix}.endpoint_id`, id);
        setValue(`${prefix}.provider_type`, ep.provider_type);
        setValue(`${prefix}.provider_url`, ep.url);
        setValue(`${prefix}.api_key`, ep.api_key);
        setValue(`${prefix}.model`, '');
        setAvailableModels([]);
      }
    } else {
      const pt = value.slice(3);
      const pmeta = providers.find(p => p.type === pt);
      setValue(`${prefix}.endpoint_id`, '');
      setValue(`${prefix}.provider_type`, pt);
      setValue(`${prefix}.provider_url`, pmeta?.default_url ?? '');
      if (NO_KEY_PROVIDERS.has(pt)) setValue(`${prefix}.api_key`, '');
      setValue(`${prefix}.model`, '');
      setAvailableModels([]);
    }
  }

  // Auto-fetch models when selection changes
  useEffect(() => {
    if (selectionValue === prevSelection.current) return;
    prevSelection.current = selectionValue;
    if (canListModels) fetchModels();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionValue, canListModels]);

  const fetchModels = useCallback(async () => {
    if (!canListModels) return;
    setModelsLoading(true);
    try {
      let url: string;
      if (endpointId) {
        url = `/api/models/list?endpoint_id=${encodeURIComponent(endpointId)}`;
      } else {
        url = `/api/models/list?provider_type=${encodeURIComponent(effectiveType)}&url=${encodeURIComponent(effectiveUrl || '')}`;
      }
      const models = await apiFetch<string[]>(url);
      setAvailableModels(models);
    } catch {
      setAvailableModels([]);
    } finally {
      setModelsLoading(false);
    }
  }, [canListModels, endpointId, effectiveType, effectiveUrl]);

  async function handleTest() {
    setTestState('testing');
    setTestLatency(null);
    setTestError('');
    const vals = watch();
    const layer = vals[prefix];
    const ep = endpoints.find(e => e.id === layer.endpoint_id);
    try {
      const data = await apiFetch<TestResult>('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_type: ep ? ep.provider_type : layer.provider_type,
          provider_url: ep ? ep.url : layer.provider_url,
          api_key: ep ? ep.api_key : layer.api_key,
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

  // Reachability for active endpoint
  const endpointStatus = endpointStatuses.find(s => s.id === endpointId);

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

        {/* Provider / endpoint select */}
        <div className="flex items-center gap-1 shrink-0">
          {endpointId && endpointStatus && (
            <StatusDot reachable={endpointStatus.reachable} />
          )}
          <select
            className="setting-input text-sm rounded border border-input bg-background px-2 py-1 w-52"
            value={selectionValue}
            onChange={e => handleSelectionChange(e.target.value)}
          >
            {/* Named endpoints */}
            {endpoints.length > 0 && (
              <optgroup label="My Endpoints">
                {endpoints.map(ep => (
                  <option key={ep.id} value={`ep:${ep.id}`}>
                    {ep.name || ep.url} ({ep.provider_type})
                  </option>
                ))}
              </optgroup>
            )}
            {/* Generic provider types */}
            <optgroup label="Providers">
              {providers.map(p => (
                <option key={p.type} value={`pt:${p.type}`}>{p.label}</option>
              ))}
            </optgroup>
          </select>
        </div>

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

        {/* Refresh models button */}
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
          {testState === 'ok'      && <span className="text-green-400">{testLatency != null ? `✓ ${testLatency}ms` : '✓ OK'}</span>}
          {testState === 'fail'    && <span className="text-red-400" title={testError}>✗ Failed</span>}
          {testState === 'testing' && <span className="text-muted-foreground">…</span>}
        </div>
      </div>

      {/* Secondary fields: URL + API key (only when using direct provider, not endpoint) */}
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

// ── ModelPanel ─────────────────────────────────────────────────────────────

export function ModelPanel() {
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const queryClient = useQueryClient();

  // Fetch provider list from backend
  const { data: providers = [] } = useQuery<ProviderMeta[]>({
    queryKey: ['providers'],
    queryFn: () => apiFetch<ProviderMeta[]>('/api/models/providers'),
    staleTime: 60_000,
  });

  // Fetch provider reachability + endpoint statuses
  const { data: availableData } = useQuery<AvailableData>({
    queryKey: ['models-available'],
    queryFn: () => apiFetch<AvailableData>('/api/models/available'),
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
      endpoints: sm.endpoints ?? [],
    };
    reset(merged);
  }, [rawSettings, reset]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async (modelsData: ModelsSettings) => {
      // Use cached settings from queryClient instead of re-fetching (avoids race condition)
      const current = queryClient.getQueryData<AppSettings>(['settings']) ?? {};
      return apiFetch<AppSettings>('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, models: modelsData }),
      });
    },
    onMutate: () => setSaveStatus('saving'),
    onSuccess: () => {
      setSaveStatus('saved');
      queryClient.invalidateQueries({ queryKey: ['models-available'] });
      setTimeout(() => setSaveStatus('idle'), 3000);
    },
    onError: () => {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 4000);
    },
  });

  const onSubmit = (data: ModelsSettings) => saveMutation.mutate(data);

  const reachabilityMap = availableData?.providers ?? {};
  const endpointStatuses: EndpointStatus[] = availableData?.endpoints ?? [];

  // Watch endpoints to pass to layer rows
  const endpoints = useWatch({ control, name: 'endpoints' }) ?? [];

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Models & Providers</h3>
        <p className="text-xs text-muted-foreground">
          Save named endpoints for each machine running a local LLM, then assign any model to each layer.
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
                <StatusDot reachable={status?.reachable ?? null} />
                <span>{p.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Named Endpoints ── */}
      <div className="flex flex-col gap-2 p-3 rounded border border-border bg-muted/30">
        <Controller
          control={control}
          name="endpoints"
          render={({ field }) => (
            <EndpointsManager
              endpoints={field.value ?? []}
              onChange={field.onChange}
              providers={providers}
              endpointStatuses={endpointStatuses}
            />
          )}
        />
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
            providers={providers}
            endpoints={endpoints}
            endpointStatuses={endpointStatuses}
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
