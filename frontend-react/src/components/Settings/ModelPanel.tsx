/**
 * ModelPanel — Models & Providers settings panel.
 *
 * Redesigned UX:
 *  - Section 1: "My Machines" — card grid showing each endpoint as a machine card
 *    with real-time status dot, provider type, short URL, available models, edit/delete
 *  - Section 2: Layer configuration — Fast / Deep rows with source dropdown
 *    combining machines + cloud providers, model picker, test button
 *  - Inline form for adding/editing machines (no modal)
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
  endpoint_id: string;
}

/** A named worker class — routes task types to a specific LLM. */
interface WorkerClass {
  id: string;
  name: string;
  description: string;
  endpoint_id: string;
  provider_type: string;
  model: string;
  intent_patterns: string[];
}

interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;

  endpoints: ProviderEndpoint[];
  worker_classes: WorkerClass[];
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

const DEFAULT_WORKER_CLASSES: WorkerClass[] = [
  {
    id: '00000000-0000-0000-0000-000000000001',
    name: 'Quick',
    description: 'Fast, lightweight tasks — summaries, simple Q&A, formatting',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-haiku-4-5-20251001',
    intent_patterns: ['summarize', 'format', 'quick', 'simple', 'short'],
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    name: 'Coding',
    description: 'Code writing, debugging, refactoring, code review',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-sonnet-4-6',
    intent_patterns: ['code', 'debug', 'refactor', 'implement', 'fix', 'test'],
  },
  {
    id: '00000000-0000-0000-0000-000000000003',
    name: 'Research',
    description: 'Deep research, analysis, multi-step investigation',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-opus-4-6',
    intent_patterns: ['research', 'analyze', 'investigate', 'compare', 'explain'],
  },
  {
    id: '00000000-0000-0000-0000-000000000004',
    name: 'Creative',
    description: 'Writing, brainstorming, ideation, narrative',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-sonnet-4-6',
    intent_patterns: ['write', 'brainstorm', 'creative', 'story', 'draft'],
  },
];

const DEFAULT_MODELS: ModelsSettings = {
  fast: { ...DEFAULT_LAYER, model: 'claude-sonnet-4' },
  deep: { ...DEFAULT_LAYER, model: 'claude-opus-4' },

  endpoints: [],
  worker_classes: DEFAULT_WORKER_CLASSES,
};

const LAYER_META: Record<LayerKey, { label: string; icon: string; placeholder: string; showEnabled: boolean }> = {
  fast: { label: 'Fast', icon: '\u26A1', placeholder: 'claude-sonnet-4', showEnabled: false },
  deep: { label: 'Deep', icon: '\uD83E\uDDE0', placeholder: 'claude-opus-4',  showEnabled: true  },
};

const NO_URL_PROVIDERS = new Set(['cli', 'anthropic']);
const NO_KEY_PROVIDERS = new Set(['cli', 'ollama', 'lmstudio']);
const LISTABLE_PROVIDERS = new Set(['ollama', 'openai', 'groq', 'mistral', 'lmstudio', 'gemini', 'anthropic', 'cli', 'openrouter']);
const LOCAL_PROVIDER_TYPES = new Set(['ollama', 'lmstudio']);

// Static fallback model lists for cloud providers (shown when API listing is unavailable)
const STATIC_MODELS: Record<string, string[]> = {
  cli: ['claude-haiku-4-5-20251001', 'claude-sonnet-4-6', 'claude-opus-4-6'],
  anthropic: ['claude-haiku-4-5-20251001', 'claude-sonnet-4-6', 'claude-opus-4-6', 'claude-sonnet-4-5', 'claude-opus-4-5'],
  groq: [
    'llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'llama-3.1-8b-instant',
    'mixtral-8x7b-32768', 'gemma2-9b-it', 'gemma-7b-it',
  ],
  mistral: [
    'mistral-large-latest', 'mistral-medium-latest', 'mistral-small-latest',
    'open-mixtral-8x22b', 'open-mistral-7b', 'codestral-latest',
  ],
  openai: [
    'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4',
    'gpt-3.5-turbo', 'o1', 'o1-mini', 'o3-mini',
  ],
  gemini: [
    'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-pro',
    'gemini-1.5-flash', 'gemini-1.5-flash-8b',
  ],
  openrouter: [
    'openai/gpt-4o', 'openai/gpt-4o-mini', 'anthropic/claude-opus-4-6',
    'anthropic/claude-sonnet-4-6', 'anthropic/claude-haiku-4-5',
    'google/gemini-2.0-flash', 'meta-llama/llama-3.3-70b-instruct',
    'mistralai/mistral-large', 'deepseek/deepseek-chat', 'qwen/qwen-2.5-72b-instruct',
  ],
};

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

/** Extract host:port from a full URL */
function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.host;
  } catch {
    return url;
  }
}

/** Capitalize first letter of provider type for display */
function providerLabel(type: string): string {
  const labels: Record<string, string> = {
    ollama: 'Ollama',
    lmstudio: 'LM Studio',
    openai: 'OpenAI-compat',
    cli: 'Claude CLI',
    anthropic: 'Anthropic',
    groq: 'Groq',
    mistral: 'Mistral',
    gemini: 'Gemini',
    openrouter: 'OpenRouter',
  };
  return labels[type] || type;
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── StatusDot ──────────────────────────────────────────────────────────────

function StatusDot({ reachable, size = 'sm' }: { reachable: boolean | null; size?: 'sm' | 'md' }) {
  const dim = size === 'md' ? 'w-2.5 h-2.5' : 'w-2 h-2';
  if (reachable === null) return <span className={`${dim} rounded-full bg-gray-500 inline-block shrink-0`} />;
  return (
    <span
      className={`${dim} rounded-full inline-block shrink-0`}
      style={{ background: reachable ? '#22c55e' : '#ef4444' }}
      title={reachable ? 'Online' : 'Offline'}
    />
  );
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
          tools
        </span>
      )}
      {caps.supports_vision && (
        <span className="text-xs px-1 rounded" style={{ background: 'var(--color-accent)', color: '#fff', opacity: 0.85 }}>
          vision
        </span>
      )}
      {caps.context_window > 0 && (
        <span className="text-xs px-1 rounded bg-muted text-muted-foreground">
          {formatContext(caps.context_window)}
        </span>
      )}
      {!caps.supports_tools && (
        <span className="text-xs px-1 rounded bg-muted text-yellow-400">
          no tools
        </span>
      )}
    </div>
  );
}

// ── MachineForm ───────────────────────────────────────────────────────────

const CLOUD_PROVIDER_TYPES = new Set(['anthropic', 'groq', 'mistral', 'gemini', 'openrouter', 'openai']);
const CLOUD_DEFAULT_URLS: Record<string, string> = {
  anthropic: 'https://api.anthropic.com',
  groq: 'https://api.groq.com/openai/v1',
  mistral: 'https://api.mistral.ai/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  openrouter: 'https://openrouter.ai/api/v1',
  openai: 'https://api.openai.com/v1',
};

interface MachineFormProps {
  draft: ProviderEndpoint;
  allProviders: ProviderMeta[];
  onChange: (ep: ProviderEndpoint) => void;
  onSave: () => void;
  onCancel: () => void;
  isNew?: boolean;
}

function MachineForm({ draft, allProviders, onChange, onSave, onCancel, isNew }: MachineFormProps) {
  const set = (key: keyof ProviderEndpoint, value: string) => onChange({ ...draft, [key]: value });
  const localProviders = allProviders.filter(p => LOCAL_PROVIDER_TYPES.has(p.type));
  const cloudProviders = allProviders.filter(p => CLOUD_PROVIDER_TYPES.has(p.type));

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3">
      <div className="text-sm font-medium text-foreground">
        {isNew ? 'Add a machine' : 'Edit machine'}
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Machine name</label>
        <input
          type="text"
          className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
          placeholder='e.g. "Mac Studio"'
          value={draft.name}
          onChange={e => set('name', e.target.value)}
          autoFocus
        />
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Server type</label>
        <select
          className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
          value={draft.provider_type}
          onChange={e => {
            const pt = e.target.value;
            const meta = allProviders.find(p => p.type === pt);
            const defaultUrl = CLOUD_DEFAULT_URLS[pt] ?? meta?.default_url ?? draft.url;
            const autoName = !draft.name.trim() ? (meta?.label ?? pt) : draft.name;
            onChange({ ...draft, provider_type: pt, url: defaultUrl, api_key: '', name: autoName });
          }}
        >
          <optgroup label="Local servers">
            {localProviders.map(p => <option key={p.type} value={p.type}>{p.label}</option>)}
          </optgroup>
          <optgroup label="Cloud providers">
            {cloudProviders.map(p => <option key={p.type} value={p.type}>{p.label}</option>)}
          </optgroup>
        </select>
      </div>

      {!CLOUD_PROVIDER_TYPES.has(draft.provider_type) && (
        <div className="flex flex-col gap-2">
          <label className="text-xs text-muted-foreground">Address</label>
          <input
            type="text"
            className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
            placeholder="http://192.168.1.10:11434"
            value={draft.url}
            onChange={e => set('url', e.target.value)}
          />
        </div>
      )}

      {!NO_KEY_PROVIDERS.has(draft.provider_type) && (
        <div className="flex flex-col gap-2">
          <label className="text-xs text-muted-foreground">API key (optional)</label>
          <input
            type="password"
            className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
            placeholder="sk-..."
            value={draft.api_key}
            onChange={e => set('api_key', e.target.value)}
          />
        </div>
      )}

      <div className="flex gap-2 justify-end pt-1">
        <button
          type="button"
          className="text-xs px-3 py-1 rounded border border-border hover:bg-accent text-muted-foreground"
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="text-xs px-4 py-1 rounded border border-border hover:bg-accent font-medium"
          onClick={onSave}
          disabled={!draft.url.trim() || !draft.name.trim()}
        >
          Save
        </button>
      </div>
    </div>
  );
}

// ── MachineCard ───────────────────────────────────────────────────────────

interface MachineCardProps {
  endpoint: ProviderEndpoint;
  status: EndpointStatus | undefined;
  models: string[];
  modelsLoading: boolean;
  onEdit: () => void;
  onDelete: () => void;
}

function MachineCard({ endpoint, status, models, modelsLoading, onEdit, onDelete }: MachineCardProps) {
  const reachable = status ? status.reachable : null;
  const isOnline = reachable === true;

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-2 min-h-[140px]">
      {/* Header: status dot + name */}
      <div className="flex items-center gap-2">
        <StatusDot reachable={reachable} size="md" />
        <span className="text-sm font-semibold truncate flex-1">
          {endpoint.name || shortUrl(endpoint.url)}
        </span>
      </div>

      {/* Provider type + short URL */}
      <div className="text-xs text-muted-foreground">
        {providerLabel(endpoint.provider_type)}
      </div>
      <div className="text-xs text-muted-foreground font-mono truncate">
        {shortUrl(endpoint.url)}
      </div>

      {/* Models or offline */}
      <div className="flex-1 mt-1">
        {modelsLoading ? (
          <div className="text-xs text-muted-foreground italic">Loading...</div>
        ) : isOnline && models.length > 0 ? (
          <div className="flex flex-col gap-0.5">
            {models.slice(0, 4).map(m => (
              <span key={m} className="text-xs text-muted-foreground truncate">{m}</span>
            ))}
            {models.length > 4 && (
              <span className="text-xs text-muted-foreground italic">
                +{models.length - 4} more
              </span>
            )}
          </div>
        ) : reachable === false ? (
          <span className="text-xs font-medium" style={{ color: '#ef4444' }}>Offline</span>
        ) : null}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 mt-auto pt-1 border-t border-border">
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent flex-1"
          onClick={onEdit}
        >
          Edit
        </button>
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent text-red-400"
          onClick={onDelete}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

// ── AddMachineCard ────────────────────────────────────────────────────────

function AddMachineCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="rounded-lg border border-dashed border-border bg-background/50 p-4 flex flex-col items-center justify-center gap-2 min-h-[140px] hover:bg-accent/30 transition-colors cursor-pointer"
      onClick={onClick}
    >
      <span className="text-2xl text-muted-foreground">+</span>
      <span className="text-xs text-muted-foreground">Add a machine</span>
    </button>
  );
}

// ── MachinesGrid ──────────────────────────────────────────────────────────

interface MachinesGridProps {
  endpoints: ProviderEndpoint[];
  onChange: (endpoints: ProviderEndpoint[]) => void;
  providers: ProviderMeta[];
  endpointStatuses: EndpointStatus[];
}

function MachinesGrid({ endpoints, onChange, providers, endpointStatuses }: MachinesGridProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProviderEndpoint | null>(null);
  const [isAdding, setIsAdding] = useState(false);

  // Per-endpoint model lists
  const [modelsByEndpoint, setModelsByEndpoint] = useState<Record<string, string[]>>({});
  const [loadingByEndpoint, setLoadingByEndpoint] = useState<Record<string, boolean>>({});

  const statusById = Object.fromEntries(endpointStatuses.map(s => [s.id, s]));

  // Auto-fetch models for reachable endpoints
  useEffect(() => {
    endpoints.forEach(ep => {
      const status = statusById[ep.id];
      if (status?.reachable && LISTABLE_PROVIDERS.has(ep.provider_type)) {
        // Only fetch if we haven't loaded yet
        if (!(ep.id in modelsByEndpoint) && !loadingByEndpoint[ep.id]) {
          setLoadingByEndpoint(prev => ({ ...prev, [ep.id]: true }));
          apiFetch<string[]>(`/api/models/list?endpoint_id=${encodeURIComponent(ep.id)}`)
            .then(models => {
              setModelsByEndpoint(prev => ({ ...prev, [ep.id]: models }));
            })
            .catch(() => {
              setModelsByEndpoint(prev => ({ ...prev, [ep.id]: [] }));
            })
            .finally(() => {
              setLoadingByEndpoint(prev => ({ ...prev, [ep.id]: false }));
            });
        }
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoints, endpointStatuses]);

  function startAdd() {
    const ep: ProviderEndpoint = {
      id: newId(),
      name: '',
      provider_type: 'ollama',
      url: 'http://192.168.1.x:11434',
      api_key: '',
    };
    setDraft(ep);
    setIsAdding(true);
    setEditingId(ep.id);
  }

  function startEdit(ep: ProviderEndpoint) {
    setDraft({ ...ep });
    setIsAdding(false);
    setEditingId(ep.id);
  }

  function cancelEdit() {
    setDraft(null);
    setEditingId(null);
    setIsAdding(false);
  }

  function saveEdit() {
    if (!draft) return;
    const existing = endpoints.find(e => e.id === draft.id);
    if (existing) {
      onChange(endpoints.map(e => e.id === draft.id ? draft : e));
    } else {
      onChange([...endpoints, draft]);
    }
    // Clear cached models for this endpoint so they get re-fetched
    setModelsByEndpoint(prev => {
      const next = { ...prev };
      delete next[draft.id];
      return next;
    });
    setDraft(null);
    setEditingId(null);
    setIsAdding(false);
  }

  function removeEndpoint(id: string) {
    onChange(endpoints.filter(e => e.id !== id));
    setModelsByEndpoint(prev => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">My Machines</span>
        <span className="text-xs text-muted-foreground">
          Local or remote servers running an LLM
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {endpoints.map(ep => {
          if (editingId === ep.id && draft && !isAdding) {
            return (
              <MachineForm
                key={ep.id}
                draft={draft}
                allProviders={providers}
                onChange={setDraft}
                onSave={saveEdit}
                onCancel={cancelEdit}
              />
            );
          }

          return (
            <MachineCard
              key={ep.id}
              endpoint={ep}
              status={statusById[ep.id]}
              models={modelsByEndpoint[ep.id] ?? []}
              modelsLoading={loadingByEndpoint[ep.id] ?? false}
              onEdit={() => startEdit(ep)}
              onDelete={() => removeEndpoint(ep.id)}
            />
          );
        })}

        {/* Add form or add button */}
        {isAdding && draft ? (
          <MachineForm
            draft={draft}
            allProviders={providers}
            onChange={setDraft}
            onSave={saveEdit}
            onCancel={cancelEdit}
            isNew
          />
        ) : (
          <AddMachineCard onClick={startAdd} />
        )}
      </div>
    </div>
  );
}

// ── LayerRow ─────────────────────────────────────────────────────────────

interface LayerRowProps {
  layerKey: LayerKey;
  control: ReturnType<typeof useForm<ModelsSettings>>['control'];
  watch: ReturnType<typeof useForm<ModelsSettings>>['watch'];
  setValue: ReturnType<typeof useForm<ModelsSettings>>['setValue'];
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
}

function LayerRow({ layerKey, control, watch, setValue, providers, endpoints, endpointStatuses }: LayerRowProps) {
  const meta = LAYER_META[layerKey];
  const prefix = layerKey;

  const providerType = useWatch({ control, name: `${prefix}.provider_type` as const });
  const providerUrl  = useWatch({ control, name: `${prefix}.provider_url`  as const });
  const endpointId   = useWatch({ control, name: `${prefix}.endpoint_id`   as const });
  const modelValue   = useWatch({ control, name: `${prefix}.model`         as const });

  const activeEndpoint = endpoints.find(e => e.id === endpointId);
  const effectiveType  = activeEndpoint ? activeEndpoint.provider_type : providerType;
  const effectiveUrl   = activeEndpoint ? activeEndpoint.url : providerUrl;

  const showUrl       = !endpointId && !NO_URL_PROVIDERS.has(providerType);
  const showKey       = !endpointId && !NO_KEY_PROVIDERS.has(providerType);
  const canListModels = LISTABLE_PROVIDERS.has(effectiveType);
  const thinking      = isThinkingModel(modelValue ?? '');

  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading]     = useState(false);
  const [testState, setTestState]             = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testLatency, setTestLatency]         = useState<number | null>(null);
  const [testError, setTestError]             = useState<string>('');
  const prevSelection = useRef('');

  const selectionValue = endpointId ? `ep:${endpointId}` : `pt:${providerType}`;

  // Endpoint reachability for warning
  const endpointStatus = endpointStatuses.find(s => s.id === endpointId);
  const isEndpointOffline = endpointId && endpointStatus && !endpointStatus.reachable;

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

  useEffect(() => {
    if (selectionValue === prevSelection.current) return;
    prevSelection.current = selectionValue;
    if (canListModels) fetchModels();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionValue, canListModels]);

  const fetchModels = useCallback(async () => {
    if (!canListModels) return;
    setModelsLoading(true);
    // Show static fallback immediately while fetching
    if (!endpointId && STATIC_MODELS[effectiveType]) {
      setAvailableModels(STATIC_MODELS[effectiveType]);
    }
    try {
      let url: string;
      if (endpointId) {
        url = `/api/models/list?endpoint_id=${encodeURIComponent(endpointId)}`;
      } else {
        url = `/api/models/list?provider_type=${encodeURIComponent(effectiveType)}&url=${encodeURIComponent(effectiveUrl || '')}`;
      }
      const models = await apiFetch<string[]>(url);
      setAvailableModels(models.length > 0 ? models : (STATIC_MODELS[effectiveType] ?? []));
    } catch {
      setAvailableModels(STATIC_MODELS[effectiveType] ?? []);
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

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3" data-layer={layerKey}>
      {/* Layer header */}
      <div className="flex items-center gap-2">
        <span className="text-lg">{meta.icon}</span>
        <span className="text-sm font-semibold">{meta.label}</span>
        {meta.showEnabled && (
          <Controller
            control={control}
            name={`${prefix}.enabled`}
            render={({ field }) => (
              <label className="flex items-center gap-1 ml-2 text-xs text-muted-foreground cursor-pointer">
                <input type="checkbox" className="setting-checkbox" checked={field.value} onChange={field.onChange} />
                enabled
              </label>
            )}
          />
        )}
      </div>

      {/* Source + Model + Test in one row */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Source dropdown */}
        <div className="flex flex-col gap-1 min-w-[200px]">
          <label className="text-xs text-muted-foreground">Source</label>
          <div className="flex items-center gap-1.5">
            {endpointId && endpointStatus && (
              <StatusDot reachable={endpointStatus.reachable} />
            )}
            <select
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
              value={selectionValue}
              onChange={e => handleSelectionChange(e.target.value)}
            >
              {endpoints.length > 0 && (
                <optgroup label="My Machines">
                  {endpoints.map(ep => {
                    const st = endpointStatuses.find(s => s.id === ep.id);
                    const dot = st ? (st.reachable ? '\u25CF ' : '\u25CB ') : '  ';
                    return (
                      <option key={ep.id} value={`ep:${ep.id}`}>
                        {dot}{ep.name || shortUrl(ep.url)} ({providerLabel(ep.provider_type)})
                      </option>
                    );
                  })}
                </optgroup>
              )}
              <optgroup label="Cloud Providers">
                {providers.map(p => (
                  <option key={p.type} value={`pt:${p.type}`}>{p.label}</option>
                ))}
              </optgroup>
            </select>
          </div>
        </div>

        {/* Model picker */}
        <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
          <label className="text-xs text-muted-foreground">Model</label>
          <div className="flex items-center gap-1.5">
            {showModelDropdown ? (
              <Controller
                control={control}
                name={`${prefix}.model`}
                render={({ field }) => (
                  <select
                    className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
                    value={field.value}
                    onChange={field.onChange}
                  >
                    <option value="">Select model...</option>
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
                    className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
                    placeholder={meta.placeholder}
                    value={field.value}
                    onChange={field.onChange}
                  />
                )}
              />
            )}
            {canListModels && (
              <button
                type="button"
                className="text-xs px-2 py-1.5 rounded border border-border hover:bg-accent shrink-0"
                disabled={modelsLoading}
                onClick={fetchModels}
                title="Refresh model list"
              >
                {modelsLoading ? '...' : '\u21BB'}
              </button>
            )}
          </div>
        </div>

        {/* Test button + result */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">&nbsp;</label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn-secondary text-xs px-3 py-1.5 rounded border border-border hover:bg-accent shrink-0"
              disabled={testState === 'testing'}
              onClick={handleTest}
            >
              {testState === 'testing' ? '...' : 'Test'}
            </button>
            <div className="text-xs w-20 shrink-0">
              {testState === 'ok'      && <span className="text-green-400">{testLatency != null ? `\u2713 ${testLatency}ms` : '\u2713 OK'}</span>}
              {testState === 'fail'    && <span className="text-red-400" title={testError}>\u2717 Error</span>}
              {testState === 'testing' && <span className="text-muted-foreground">...</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Secondary: URL + API key when using direct provider */}
      {(showUrl || showKey) && (
        <div className="flex gap-2 flex-wrap">
          {showUrl && (
            <Controller
              control={control}
              name={`${prefix}.provider_url`}
              render={({ field }) => (
                <input
                  type="text"
                  className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1 min-w-[200px]"
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
                  className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1 min-w-[200px]"
                  placeholder="Cle API"
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
          )}
        </div>
      )}

      {/* Warnings and badges */}
      {isEndpointOffline && (
        <div className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-400 border border-red-500/20">
          This machine is offline. The layer will not work until it is reachable.
        </div>
      )}

      <div className="flex flex-col gap-0.5">
        <CapabilityBadges model={modelValue ?? ''} />
        {thinking && (
          <div className="text-xs" style={{ color: 'var(--color-accent)' }}>
            Thinking model -- /no_think applied automatically
          </div>
        )}
        {testState === 'fail' && testError && (
          <div className="text-xs text-red-400 truncate max-w-md">{testError}</div>
        )}
      </div>
    </div>
  );
}

// ── WorkerClassesPanel ───────────────────────────────────────────────────

const EMPTY_WORKER_CLASS: WorkerClass = {
  id: '',
  name: '',
  description: '',
  endpoint_id: '',
  provider_type: 'cli',
  model: '',
  intent_patterns: [],
};

interface WorkerClassesPanelProps {
  workerClasses: WorkerClass[];
  onChange: (classes: WorkerClass[]) => void;
  onAutoSave?: () => void;  // trigger parent form submission after inline edit
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
}

function WorkerClassesPanel({ workerClasses, onChange, onAutoSave, providers, endpoints, endpointStatuses }: WorkerClassesPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<WorkerClass | null>(null);
  const [isAdding, setIsAdding] = useState(false);

  // Per-class model lists (fetched when source changes)
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  function startAdd() {
    const wc: WorkerClass = { ...EMPTY_WORKER_CLASS, id: crypto.randomUUID() };
    setDraft(wc);
    setIsAdding(true);
    setEditingId(wc.id);
    setAvailableModels([]);
  }

  function startEdit(wc: WorkerClass) {
    setDraft({ ...wc });
    setIsAdding(false);
    setEditingId(wc.id);
    setAvailableModels([]);
    // Fetch models for current source
    const effectiveType = wc.endpoint_id
      ? endpoints.find(e => e.id === wc.endpoint_id)?.provider_type ?? wc.provider_type
      : wc.provider_type;
    if (LISTABLE_PROVIDERS.has(effectiveType)) {
      fetchModelsForSource(wc.endpoint_id, effectiveType);
    }
  }

  function cancelEdit() {
    setDraft(null);
    setEditingId(null);
    setIsAdding(false);
    setAvailableModels([]);
  }

  function saveEdit() {
    if (!draft || !draft.name.trim()) return;
    const existing = workerClasses.find(c => c.id === draft.id);
    if (existing) {
      onChange(workerClasses.map(c => c.id === draft.id ? draft : c));
    } else {
      onChange([...workerClasses, draft]);
    }
    setDraft(null);
    setEditingId(null);
    setIsAdding(false);
    setAvailableModels([]);
    // field.onChange updates react-hook-form's _formValues synchronously,
    // so we can call onAutoSave immediately — no setTimeout needed.
    // Using setTimeout(0) introduced a race: the useEffect that calls
    // reset(merged) could overwrite _formValues between field.onChange
    // and the deferred handleSubmit read, losing endpoint_id and other fields.
    onAutoSave?.();
  }

  function removeClass(id: string) {
    onChange(workerClasses.filter(c => c.id !== id));
    onAutoSave?.();
  }

  async function fetchModelsForSource(endpointId: string, providerType: string) {
    if (!LISTABLE_PROVIDERS.has(providerType)) {
      setAvailableModels(STATIC_MODELS[providerType] ?? []);
      return;
    }
    // Show static fallback immediately
    if (!endpointId && STATIC_MODELS[providerType]) {
      setAvailableModels(STATIC_MODELS[providerType]);
    }
    setModelsLoading(true);
    try {
      let url: string;
      if (endpointId) {
        url = `/api/models/list?endpoint_id=${encodeURIComponent(endpointId)}`;
      } else {
        const pmeta = providers.find(p => p.type === providerType);
        const baseUrl = pmeta?.default_url ?? '';
        url = `/api/models/list?provider_type=${encodeURIComponent(providerType)}&url=${encodeURIComponent(baseUrl)}`;
      }
      const models = await apiFetch<string[]>(url);
      setAvailableModels(models.length > 0 ? models : (STATIC_MODELS[providerType] ?? []));
    } catch {
      setAvailableModels(STATIC_MODELS[providerType] ?? []);
    } finally {
      setModelsLoading(false);
    }
  }

  function handleSourceChange(value: string) {
    if (!draft) return;
    let updated: WorkerClass;
    if (value.startsWith('ep:')) {
      const id = value.slice(3);
      const ep = endpoints.find(e => e.id === id);
      if (ep) {
        updated = { ...draft, endpoint_id: id, provider_type: ep.provider_type, model: '' };
        fetchModelsForSource(id, ep.provider_type);
      } else {
        return;
      }
    } else {
      const pt = value.slice(3);
      updated = { ...draft, endpoint_id: '', provider_type: pt, model: '' };
      fetchModelsForSource('', pt);
    }
    setDraft(updated);
  }

  function getSourceValue(wc: WorkerClass): string {
    return wc.endpoint_id ? `ep:${wc.endpoint_id}` : `pt:${wc.provider_type}`;
  }

  function getSourceLabel(wc: WorkerClass): string {
    if (wc.endpoint_id) {
      const ep = endpoints.find(e => e.id === wc.endpoint_id);
      return ep ? (ep.name || shortUrl(ep.url)) : 'Unknown machine';
    }
    return providerLabel(wc.provider_type);
  }

  const showModelDropdown = availableModels.length > 0;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">Worker Classes</span>
        <span className="text-xs text-muted-foreground">
          Assign a specific LLM to a named worker type. The dispatcher uses these to route tasks to the right model.
        </span>
      </div>

      {/* Existing worker classes */}
      {workerClasses.map(wc => {
        if (editingId === wc.id) {
          return null; // Rendered below as inline form
        }
        return (
          <div key={wc.id} className="rounded-lg border border-border bg-background p-4 flex items-center gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold">{wc.name}</span>
                <span className="text-xs text-muted-foreground">
                  {getSourceLabel(wc)}
                </span>
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">
                {wc.model && <span className="font-mono">{wc.model}</span>}
                {wc.description && <span className="ml-2">{wc.description}</span>}
              </div>
              {wc.intent_patterns.length > 0 && (
                <div className="flex gap-1 flex-wrap mt-1">
                  {wc.intent_patterns.map((p, i) => (
                    <span key={i} className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                      {p}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button
                type="button"
                className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent"
                onClick={() => startEdit(wc)}
              >
                Edit
              </button>
              <button
                type="button"
                className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent text-red-400"
                onClick={() => removeClass(wc.id)}
              >
                Delete
              </button>
            </div>
          </div>
        );
      })}

      {/* Inline edit/add form */}
      {editingId && draft && (
        <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3">
          <div className="text-sm font-medium text-foreground">
            {isAdding ? 'Add a worker class' : 'Edit worker class'}
          </div>

          {/* Name */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">Name (required)</label>
            <input
              type="text"
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              placeholder='e.g. "Coding", "Research"'
              value={draft.name}
              onChange={e => setDraft({ ...draft, name: e.target.value })}
              autoFocus
            />
          </div>

          {/* Description */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">Description (optional)</label>
            <input
              type="text"
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              placeholder="What this worker class does"
              value={draft.description}
              onChange={e => setDraft({ ...draft, description: e.target.value })}
            />
          </div>

          {/* Source dropdown */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">LLM Source</label>
            <select
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              value={getSourceValue(draft)}
              onChange={e => handleSourceChange(e.target.value)}
            >
              {endpoints.length > 0 && (
                <optgroup label="My Machines">
                  {endpoints.map(ep => {
                    const st = endpointStatuses.find(s => s.id === ep.id);
                    const dot = st ? (st.reachable ? '\u25CF ' : '\u25CB ') : '  ';
                    return (
                      <option key={ep.id} value={`ep:${ep.id}`}>
                        {dot}{ep.name || shortUrl(ep.url)} ({providerLabel(ep.provider_type)})
                      </option>
                    );
                  })}
                </optgroup>
              )}
              <optgroup label="Cloud Providers">
                {providers.map(p => (
                  <option key={p.type} value={`pt:${p.type}`}>{p.label}</option>
                ))}
              </optgroup>
            </select>
          </div>

          {/* Model */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">Model</label>
            <div className="flex items-center gap-1.5">
              {showModelDropdown ? (
                <select
                  className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 flex-1"
                  value={draft.model}
                  onChange={e => setDraft({ ...draft, model: e.target.value })}
                >
                  <option value="">Select model...</option>
                  {availableModels.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 flex-1"
                  placeholder="e.g. claude-sonnet-4, qwen2.5:32b"
                  value={draft.model}
                  onChange={e => setDraft({ ...draft, model: e.target.value })}
                />
              )}
              {modelsLoading && (
                <span className="text-xs text-muted-foreground">Loading...</span>
              )}
            </div>
          </div>

          {/* Intent Patterns */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">Intent Patterns (comma-separated keywords for auto-routing)</label>
            <input
              type="text"
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              placeholder='e.g. "code, implement, refactor" or "research, search, analyze"'
              value={draft.intent_patterns.join(', ')}
              onChange={e => setDraft({
                ...draft,
                intent_patterns: e.target.value
                  .split(',')
                  .map(s => s.trim())
                  .filter(Boolean),
              })}
            />
          </div>

          {/* Save/Cancel */}
          <div className="flex gap-2 justify-end pt-1">
            <button
              type="button"
              className="text-xs px-3 py-1 rounded border border-border hover:bg-accent text-muted-foreground"
              onClick={cancelEdit}
            >
              Cancel
            </button>
            <button
              type="button"
              className="text-xs px-4 py-1 rounded border border-border hover:bg-accent font-medium"
              onClick={saveEdit}
              disabled={!draft.name.trim()}
            >
              Save
            </button>
          </div>
        </div>
      )}

      {/* Add button */}
      {!isAdding && (
        <button
          type="button"
          className="rounded-lg border border-dashed border-border bg-background/50 p-3 flex items-center justify-center gap-2 hover:bg-accent/30 transition-colors cursor-pointer"
          onClick={startAdd}
        >
          <span className="text-lg text-muted-foreground">+</span>
          <span className="text-xs text-muted-foreground">Add a worker class</span>
        </button>
      )}
    </div>
  );
}

// ── ComparisonPanel (Worker Class Benchmark) ──────────────────────────────

interface BenchmarkCriterion {
  name: string;
  score_a: number;
  score_b: number;
}

interface BenchmarkEvaluation {
  winner: 'a' | 'b' | 'tie';
  score_a: number;
  score_b: number;
  criteria: BenchmarkCriterion[];
  summary: string;
  recommendation: string;
}

interface BenchmarkModelResult {
  success: boolean;
  reply: string;
  latency_ms: number;
  model: string;
  provider_type: string;
  error?: string;
}

interface BenchmarkResponse {
  prompt_used: string;
  result_a: BenchmarkModelResult;
  result_b: BenchmarkModelResult;
  evaluation: BenchmarkEvaluation;
}

interface ComparisonSlot {
  sourceValue: string;       // "ep:{id}" or "pt:{type}"
  providerType: string;
  providerUrl: string;
  endpointId: string;
  model: string;
  availableModels: string[];
  modelsLoading: boolean;
}

function emptySlot(): ComparisonSlot {
  return {
    sourceValue: 'pt:cli',
    providerType: 'cli',
    providerUrl: '',
    endpointId: '',
    model: '',
    availableModels: STATIC_MODELS['cli'] ?? [],
    modelsLoading: false,
  };
}

interface ComparisonPanelProps {
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
  workerClasses: WorkerClass[];
  onAssignToClass: (classId: string, config: { provider_type: string; model: string; endpoint_id: string }) => void;
}

function ComparisonPanel({ providers, endpoints, endpointStatuses, workerClasses, onAssignToClass }: ComparisonPanelProps) {
  const [selectedClassId, setSelectedClassId] = useState('');
  const [prompt, setPrompt] = useState('');
  const [promptEdited, setPromptEdited] = useState(false);
  const [promptIndex, setPromptIndex] = useState(-1);
  const [slotA, setSlotA] = useState<ComparisonSlot>(emptySlot());
  const [slotB, setSlotB] = useState<ComparisonSlot>(() => ({ ...emptySlot(), sourceValue: 'pt:anthropic', providerType: 'anthropic' }));
  const [benchmarkResult, setBenchmarkResult] = useState<BenchmarkResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const selectedClass = workerClasses.find(wc => wc.id === selectedClassId);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  }

  // Auto-generate prompt when worker class changes
  function handleClassChange(classId: string) {
    setSelectedClassId(classId);
    setPromptEdited(false);
    setPromptIndex(-1);
    setBenchmarkResult(null);
    const wc = workerClasses.find(c => c.id === classId);
    if (wc) {
      // Fetch a random prompt from the backend pool
      const params = new URLSearchParams({
        worker_class_name: wc.name,
        worker_class_description: wc.description,
        intent_patterns: wc.intent_patterns.join(','),
        prompt_index: '-1',
      });
      apiFetch<{ prompt: string }>(`/api/models/benchmark/prompt?${params}`)
        .then(data => {
          if (!promptEdited) setPrompt(data.prompt);
        })
        .catch(() => {
          // Fallback: generic prompt
          const hint = wc.description || (wc.intent_patterns.slice(0, 3).join(', ') || wc.name);
          setPrompt(`You are a ${wc.name} assistant. Demonstrate your capabilities by completing this task: ${hint}. Provide a clear, well-structured response.`);
        });
    } else {
      setPrompt('');
    }
  }

  async function handleShufflePrompt() {
    const wc = workerClasses.find(c => c.id === selectedClassId);
    if (!wc) return;
    const nextIndex = promptIndex + 1;
    setPromptIndex(nextIndex);
    try {
      const params = new URLSearchParams({
        worker_class_name: wc.name,
        worker_class_description: wc.description,
        intent_patterns: wc.intent_patterns.join(','),
        prompt_index: String(nextIndex),
      });
      const data = await apiFetch<{ prompt: string }>(`/api/models/benchmark/prompt?${params}`);
      setPrompt(data.prompt);
      setPromptEdited(false);
    } catch {
      // Silently ignore — keep current prompt
    }
  }

  async function fetchModelsForSlot(
    endpointId: string,
    providerType: string,
    setSlot: React.Dispatch<React.SetStateAction<ComparisonSlot>>,
  ) {
    const effectiveType = endpointId
      ? endpoints.find(e => e.id === endpointId)?.provider_type ?? providerType
      : providerType;
    const staticFallback = STATIC_MODELS[effectiveType] ?? [];
    if (!LISTABLE_PROVIDERS.has(effectiveType)) {
      setSlot(s => ({ ...s, availableModels: staticFallback, modelsLoading: false }));
      return;
    }
    // Show static fallback immediately while fetching
    if (!endpointId && staticFallback.length > 0) {
      setSlot(s => ({ ...s, availableModels: staticFallback, modelsLoading: true }));
    } else {
      setSlot(s => ({ ...s, modelsLoading: true }));
    }
    try {
      let url: string;
      if (endpointId) {
        url = `/api/models/list?endpoint_id=${encodeURIComponent(endpointId)}`;
      } else {
        const pmeta = providers.find(p => p.type === effectiveType);
        const baseUrl = pmeta?.default_url ?? '';
        url = `/api/models/list?provider_type=${encodeURIComponent(effectiveType)}&url=${encodeURIComponent(baseUrl)}`;
      }
      const models = await apiFetch<string[]>(url);
      setSlot(s => ({ ...s, availableModels: models.length > 0 ? models : staticFallback, modelsLoading: false }));
    } catch {
      setSlot(s => ({ ...s, availableModels: staticFallback, modelsLoading: false }));
    }
  }

  function handleSourceChange(
    value: string,
    setSlot: React.Dispatch<React.SetStateAction<ComparisonSlot>>,
  ) {
    setBenchmarkResult(null);
    if (value.startsWith('ep:')) {
      const id = value.slice(3);
      const ep = endpoints.find(e => e.id === id);
      if (ep) {
        setSlot(s => ({ ...s, sourceValue: value, endpointId: id, providerType: ep.provider_type, providerUrl: ep.url, model: '', availableModels: [] }));
        fetchModelsForSlot(id, ep.provider_type, setSlot);
      }
    } else {
      const pt = value.slice(3);
      const pmeta = providers.find(p => p.type === pt);
      setSlot(s => ({ ...s, sourceValue: value, endpointId: '', providerType: pt, providerUrl: pmeta?.default_url ?? '', model: '', availableModels: [] }));
      fetchModelsForSlot('', pt, setSlot);
    }
  }

  async function runBenchmark() {
    if (!slotA.model || !slotB.model) return;
    setLoading(true);
    setBenchmarkResult(null);
    try {
      const result = await apiFetch<BenchmarkResponse>('/api/models/benchmark', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          worker_class_id: selectedClass?.id ?? '',
          worker_class_name: selectedClass?.name ?? '',
          worker_class_description: selectedClass?.description ?? '',
          intent_patterns: selectedClass?.intent_patterns ?? [],
          model_a: { provider_type: slotA.providerType, provider_url: slotA.providerUrl, model: slotA.model, endpoint_id: slotA.endpointId },
          model_b: { provider_type: slotB.providerType, provider_url: slotB.providerUrl, model: slotB.model, endpoint_id: slotB.endpointId },
          custom_prompt: promptEdited ? prompt : '',
        }),
      });
      setBenchmarkResult(result);
    } catch (e) {
      setBenchmarkResult(null);
      showToast(`Benchmark failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  }

  function latencyColor(ms: number): string {
    if (ms < 500) return 'text-green-400';
    if (ms < 1500) return 'text-yellow-400';
    return 'text-red-400';
  }

  function renderSourcePicker(
    slot: ComparisonSlot,
    setSlot: React.Dispatch<React.SetStateAction<ComparisonSlot>>,
    label: string,
  ) {
    const canList = LISTABLE_PROVIDERS.has(
      slot.endpointId
        ? endpoints.find(e => e.id === slot.endpointId)?.provider_type ?? slot.providerType
        : slot.providerType,
    );
    const showDropdown = canList && slot.availableModels.length > 0;

    return (
      <div className="flex-1 min-w-[220px] flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <select
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 w-full"
          value={slot.sourceValue}
          onChange={e => handleSourceChange(e.target.value, setSlot)}
        >
          {endpoints.length > 0 && (
            <optgroup label="My Machines">
              {endpoints.map(ep => {
                const st = endpointStatuses.find(s => s.id === ep.id);
                const dot = st ? (st.reachable ? '\u25CF ' : '\u25CB ') : '  ';
                return (
                  <option key={ep.id} value={`ep:${ep.id}`}>
                    {dot}{ep.name || shortUrl(ep.url)} ({providerLabel(ep.provider_type)})
                  </option>
                );
              })}
            </optgroup>
          )}
          <optgroup label="Cloud Providers">
            {providers.map(p => (
              <option key={p.type} value={`pt:${p.type}`}>{p.label}</option>
            ))}
          </optgroup>
        </select>
        <div className="flex items-center gap-1.5">
          {showDropdown ? (
            <select
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
              value={slot.model}
              onChange={e => setSlot(s => ({ ...s, model: e.target.value }))}
            >
              <option value="">Select model...</option>
              {slot.availableModels.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          ) : (
            <input
              type="text"
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
              placeholder={slot.providerType === 'cli' ? 'claude-sonnet-4' : slot.providerType === 'anthropic' ? 'claude-sonnet-4' : 'model name'}
              value={slot.model}
              onChange={e => setSlot(s => ({ ...s, model: e.target.value }))}
            />
          )}
          {slot.modelsLoading && (
            <span className="text-xs text-muted-foreground shrink-0">Loading...</span>
          )}
        </div>
      </div>
    );
  }

  function renderScoreBar(score: number, maxScore: number, isWinner: boolean) {
    const pct = Math.round((score / maxScore) * 100);
    return (
      <div className="h-2.5 rounded-full flex-1" style={{ background: 'var(--color-muted, #333)' }}>
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pct}%`,
            background: isWinner ? '#22c55e' : '#6b7280',
          }}
        />
      </div>
    );
  }

  const canRun = !!slotA.model && !!slotB.model && !loading;
  const ev = benchmarkResult?.evaluation;
  const winnerLabel = ev?.winner === 'a' ? 'Model A' : ev?.winner === 'b' ? 'Model B' : null;
  const winnerSlot = ev?.winner === 'a' ? slotA : ev?.winner === 'b' ? slotB : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">LLM Comparison</span>
        <span className="text-xs text-muted-foreground">
          Benchmark two models on a Worker Class task
        </span>
      </div>

      {/* Worker Class selector */}
      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Worker Class</label>
        <select
          className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 w-full"
          value={selectedClassId}
          onChange={e => handleClassChange(e.target.value)}
        >
          <option value="">Select a worker class...</option>
          {workerClasses.map(wc => (
            <option key={wc.id} value={wc.id}>{wc.name} — {wc.description}</option>
          ))}
        </select>
      </div>

      {/* Test prompt */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground">Test Prompt</label>
          {!promptEdited && prompt && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">Auto-generated</span>
          )}
          {!promptEdited && prompt && selectedClassId && (
            <button
              type="button"
              title="Try a different prompt"
              className="text-[10px] px-1.5 py-0.5 rounded bg-muted hover:bg-accent text-muted-foreground transition-colors"
              onClick={handleShufflePrompt}
            >
              🎲 Try another
            </button>
          )}
        </div>
        <textarea
          className="setting-input text-sm rounded border border-input bg-background px-3 py-2 w-full resize-y"
          rows={3}
          value={prompt}
          onChange={e => { setPrompt(e.target.value); setPromptEdited(true); }}
          placeholder="Select a worker class to auto-generate, or type a custom prompt..."
        />
      </div>

      {/* Model A vs Model B pickers */}
      <div className="flex gap-4 items-start flex-wrap">
        {renderSourcePicker(slotA, setSlotA, 'Model A')}
        <span className="text-sm text-muted-foreground self-center pt-5 shrink-0">vs</span>
        {renderSourcePicker(slotB, setSlotB, 'Model B')}
      </div>

      {/* Run button */}
      <div className="flex justify-center">
        <button
          type="button"
          className="btn-secondary text-sm px-5 py-2 rounded border border-border hover:bg-accent font-medium"
          disabled={!canRun}
          onClick={runBenchmark}
        >
          {loading ? 'Running benchmark...' : 'Run Benchmark'}
        </button>
      </div>

      {/* Loading spinner */}
      {loading && (
        <div className="flex items-center justify-center gap-2 py-4">
          <span className="text-sm text-muted-foreground animate-pulse">Running benchmark...</span>
        </div>
      )}

      {/* Results */}
      {benchmarkResult && (
        <div className="flex flex-col gap-4">
          {/* Response cards */}
          <div className="text-xs font-medium text-muted-foreground">Results</div>
          <div className="flex gap-4 items-start flex-wrap">
            {/* Model A result */}
            {(() => {
              const r = benchmarkResult.result_a;
              const isWinner = ev?.winner === 'a';
              const borderStyle = isWinner ? 'border-green-500/60' : r.success ? 'border-border' : 'border-red-500/40';
              return (
                <div className={`flex-1 min-w-[220px] rounded-lg border ${borderStyle} bg-background p-4 flex flex-col gap-2 relative`}>
                  {isWinner && (
                    <span className="absolute -top-2.5 left-3 text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 font-medium">Winner</span>
                  )}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium">Model A</span>
                    {r.success && r.latency_ms != null && (
                      <span className={`text-xs font-semibold ${latencyColor(r.latency_ms)}`}>{r.latency_ms}ms</span>
                    )}
                    {!r.success && <span className="text-xs font-semibold text-red-400">Error</span>}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">{r.model} ({r.provider_type})</div>
                  {r.success && r.reply ? (
                    <pre className="text-xs text-foreground whitespace-pre-wrap break-words overflow-y-auto max-h-[200px] bg-muted/30 rounded p-2">{r.reply}</pre>
                  ) : r.error ? (
                    <p className="text-xs text-red-400">{r.error}</p>
                  ) : null}
                </div>
              );
            })()}
            {/* Model B result */}
            {(() => {
              const r = benchmarkResult.result_b;
              const isWinner = ev?.winner === 'b';
              const borderStyle = isWinner ? 'border-green-500/60' : r.success ? 'border-border' : 'border-red-500/40';
              return (
                <div className={`flex-1 min-w-[220px] rounded-lg border ${borderStyle} bg-background p-4 flex flex-col gap-2 relative`}>
                  {isWinner && (
                    <span className="absolute -top-2.5 left-3 text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 font-medium">Winner</span>
                  )}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium">Model B</span>
                    {r.success && r.latency_ms != null && (
                      <span className={`text-xs font-semibold ${latencyColor(r.latency_ms)}`}>{r.latency_ms}ms</span>
                    )}
                    {!r.success && <span className="text-xs font-semibold text-red-400">Error</span>}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">{r.model} ({r.provider_type})</div>
                  {r.success && r.reply ? (
                    <pre className="text-xs text-foreground whitespace-pre-wrap break-words overflow-y-auto max-h-[200px] bg-muted/30 rounded p-2">{r.reply}</pre>
                  ) : r.error ? (
                    <p className="text-xs text-red-400">{r.error}</p>
                  ) : null}
                </div>
              );
            })()}
          </div>

          {/* Evaluation */}
          {ev && (
            <div className="flex flex-col gap-3">
              <div className="text-xs font-medium text-muted-foreground">Evaluation</div>
              {/* Score bars per criterion */}
              <div className="flex flex-col gap-2 rounded-lg border border-border bg-background p-4">
                {ev.criteria.map(c => (
                  <div key={c.name} className="flex items-center gap-2 text-xs">
                    <span className="w-24 text-muted-foreground shrink-0">{c.name}</span>
                    <span className="w-4 text-right shrink-0">{c.score_a}</span>
                    {renderScoreBar(c.score_a, 10, c.score_a >= c.score_b)}
                    <span className="text-muted-foreground shrink-0 px-1">vs</span>
                    {renderScoreBar(c.score_b, 10, c.score_b >= c.score_a)}
                    <span className="w-4 shrink-0">{c.score_b}</span>
                  </div>
                ))}
                <div className="flex items-center gap-2 text-xs font-semibold border-t border-border pt-2 mt-1">
                  <span className="w-24 text-muted-foreground shrink-0">Total</span>
                  <span className="w-4 text-right shrink-0">{ev.score_a}</span>
                  <div className="flex-1" />
                  <span className="text-muted-foreground shrink-0 px-1">vs</span>
                  <div className="flex-1" />
                  <span className="w-4 shrink-0">{ev.score_b}</span>
                </div>
              </div>

              {/* Summary + recommendation */}
              {ev.summary && (
                <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Summary:</span> {ev.summary}</p>
              )}
              {ev.recommendation && (
                <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Recommendation:</span> {ev.recommendation}</p>
              )}

              {/* Assign winner button */}
              {winnerSlot && selectedClass && (
                <button
                  type="button"
                  className="text-xs px-4 py-1.5 rounded border border-green-500/40 hover:bg-green-500/10 text-green-400 font-medium self-start"
                  onClick={() => {
                    onAssignToClass(selectedClass.id, {
                      provider_type: winnerSlot.providerType,
                      model: winnerSlot.model,
                      endpoint_id: winnerSlot.endpointId,
                    });
                    showToast(`Assigned ${winnerLabel} to "${selectedClass.name}"`);
                  }}
                >
                  Assign {winnerLabel} to &quot;{selectedClass.name}&quot;
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="text-xs text-green-400 text-center animate-pulse">
          {toast}
        </div>
      )}
    </div>
  );
}

// ── ModelPanel ─────────────────────────────────────────────────────────────

export function ModelPanel() {
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const queryClient = useQueryClient();

  const { data: providers = [] } = useQuery<ProviderMeta[]>({
    queryKey: ['providers'],
    queryFn: () => apiFetch<ProviderMeta[]>('/api/models/providers'),
    staleTime: 60_000,
  });

  const { data: availableData } = useQuery<AvailableData>({
    queryKey: ['models-available'],
    queryFn: () => apiFetch<AvailableData>('/api/models/available'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const { data: rawSettings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => apiFetch<AppSettings>('/api/settings'),
  });

  const { control, reset, watch, setValue, handleSubmit } = useForm<ModelsSettings>({
    defaultValues: DEFAULT_MODELS,
  });

  useEffect(() => {
    if (!rawSettings) return;
    const dm = DEFAULT_MODELS;
    const sm = (rawSettings.models || {}) as Partial<ModelsSettings>;
    const merged: ModelsSettings = {
      fast: { ...dm.fast, ...(sm.fast || {}) },
      deep: { ...dm.deep, ...(sm.deep || {}) },

      endpoints: sm.endpoints ?? [],
      worker_classes: sm.worker_classes?.length ? sm.worker_classes : DEFAULT_WORKER_CLASSES,
    };
    reset(merged);
  }, [rawSettings, reset]);

  const saveMutation = useMutation({
    mutationFn: async (modelsData: ModelsSettings) => {
      // Always fetch fresh settings to avoid overwriting changes from other panels
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
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['models-available'] });
      setTimeout(() => setSaveStatus('idle'), 3000);
    },
    onError: () => {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 4000);
    },
  });

  const { mutate: doSave } = saveMutation;
  const onSubmit = useCallback(
    (data: ModelsSettings) => doSave(data),
    [doSave],
  );

  // Programmatic form submission — used by WorkerClassesPanel auto-save
  const triggerSave = useCallback(() => {
    handleSubmit(onSubmit)();
  }, [handleSubmit, onSubmit]);

  const endpointStatuses: EndpointStatus[] = availableData?.endpoints ?? [];
  const endpoints = useWatch({ control, name: 'endpoints' }) ?? [];

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Models & Machines</h3>
        <p className="text-xs text-muted-foreground">
          Add your local or remote machines (Mac Studio, MacBook, server...) then assign them to the Fast and Deep layers.
          Each layer can use a different machine or cloud provider.
        </p>
      </div>

      {/* ── Section 1: Machines Grid ── */}
      <Controller
        control={control}
        name="endpoints"
        render={({ field }) => (
          <MachinesGrid
            endpoints={field.value ?? []}
            onChange={field.onChange}
            providers={providers}
            endpointStatuses={endpointStatuses}
          />
        )}
      />

      {/* ── Section 2: Layers ── */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Layers</span>
          <span className="text-xs text-muted-foreground">
            Assign a source and model to each layer
          </span>
        </div>

        {(['fast', 'deep'] as LayerKey[]).map((key) => (
          <LayerRow
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

      {/* ── Section 3: Worker Classes ── */}
      <Controller
        control={control}
        name="worker_classes"
        render={({ field }) => (
          <WorkerClassesPanel
            workerClasses={field.value ?? []}
            onChange={field.onChange}
            onAutoSave={triggerSave}
            providers={providers}
            endpoints={endpoints}
            endpointStatuses={endpointStatuses}
          />
        )}
      />

      {/* ── Section 4: LLM Comparison ── */}
      <ComparisonPanel
        providers={providers}
        endpoints={endpoints}
        endpointStatuses={endpointStatuses}
        workerClasses={watch('worker_classes') ?? []}
        onAssignToClass={(classId, config) => {
          const current = watch('worker_classes') ?? [];
          setValue('worker_classes', current.map(wc =>
            wc.id === classId ? { ...wc, ...config } : wc
          ));
          triggerSave();
        }}
      />


      {/* ── Save button ── */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          className="btn-primary text-sm px-5 py-2 rounded"
          disabled={saveStatus === 'saving'}
        >
          {saveStatus === 'saving' ? 'Saving...' : 'Save'}
        </button>
        {saveStatus === 'saved' && <span className="text-xs text-green-400">{'\u2713'} Saved</span>}
        {saveStatus === 'error' && <span className="text-xs text-red-400">{'\u2717'} Save failed</span>}
      </div>

    </form>
  );
}
