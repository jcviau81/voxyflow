/**
 * ModelPanel — Models & Providers settings panel.
 *
 * Redesigned UX:
 *  - Section 1: "Mes machines" — card grid showing each endpoint as a machine card
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

const LAYER_META: Record<LayerKey, { label: string; icon: string; placeholder: string; showEnabled: boolean }> = {
  fast: { label: 'Fast', icon: '\u26A1', placeholder: 'claude-sonnet-4', showEnabled: false },
  deep: { label: 'Deep', icon: '\uD83E\uDDE0', placeholder: 'claude-opus-4',  showEnabled: true  },
};

const NO_URL_PROVIDERS = new Set(['cli', 'anthropic']);
const NO_KEY_PROVIDERS = new Set(['cli', 'ollama', 'lmstudio']);
const LISTABLE_PROVIDERS = new Set(['ollama', 'openai', 'groq', 'mistral', 'lmstudio', 'gemini']);
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
      title={reachable ? 'En ligne' : 'Hors ligne'}
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

interface MachineFormProps {
  draft: ProviderEndpoint;
  localProviders: ProviderMeta[];
  onChange: (ep: ProviderEndpoint) => void;
  onSave: () => void;
  onCancel: () => void;
  isNew?: boolean;
}

function MachineForm({ draft, localProviders, onChange, onSave, onCancel, isNew }: MachineFormProps) {
  const set = (key: keyof ProviderEndpoint, value: string) => onChange({ ...draft, [key]: value });

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3">
      <div className="text-sm font-medium text-foreground">
        {isNew ? 'Ajouter une machine' : 'Modifier la machine'}
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Nom de la machine</label>
        <input
          type="text"
          className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
          placeholder='Ex: "Mac Studio"'
          value={draft.name}
          onChange={e => set('name', e.target.value)}
          autoFocus
        />
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Type de serveur</label>
        <select
          className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
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

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Adresse</label>
        <input
          type="text"
          className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
          placeholder="http://192.168.1.10:11434"
          value={draft.url}
          onChange={e => set('url', e.target.value)}
        />
      </div>

      {!NO_KEY_PROVIDERS.has(draft.provider_type) && (
        <div className="flex flex-col gap-2">
          <label className="text-xs text-muted-foreground">Cle API (optionnel)</label>
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
          Annuler
        </button>
        <button
          type="button"
          className="text-xs px-4 py-1 rounded border border-border hover:bg-accent font-medium"
          onClick={onSave}
          disabled={!draft.url.trim() || !draft.name.trim()}
        >
          Enregistrer
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
          <div className="text-xs text-muted-foreground italic">Chargement...</div>
        ) : isOnline && models.length > 0 ? (
          <div className="flex flex-col gap-0.5">
            {models.slice(0, 4).map(m => (
              <span key={m} className="text-xs text-muted-foreground truncate">{m}</span>
            ))}
            {models.length > 4 && (
              <span className="text-xs text-muted-foreground italic">
                +{models.length - 4} autres
              </span>
            )}
          </div>
        ) : reachable === false ? (
          <span className="text-xs font-medium" style={{ color: '#ef4444' }}>Hors ligne</span>
        ) : null}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 mt-auto pt-1 border-t border-border">
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent flex-1"
          onClick={onEdit}
        >
          Editer
        </button>
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent text-red-400"
          onClick={onDelete}
        >
          Supprimer
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
      <span className="text-xs text-muted-foreground">Ajouter une machine</span>
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

  const localProviders = providers.filter(p => LOCAL_PROVIDER_TYPES.has(p.type));
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
        <span className="text-sm font-semibold">Mes machines</span>
        <span className="text-xs text-muted-foreground">
          Serveurs locaux ou distants executant un LLM
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {endpoints.map(ep => {
          if (editingId === ep.id && draft && !isAdding) {
            return (
              <MachineForm
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
            localProviders={localProviders}
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
                actif
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
                <optgroup label="Mes machines">
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
              <optgroup label="Providers cloud">
                {providers.map(p => (
                  <option key={p.type} value={`pt:${p.type}`}>{p.label}</option>
                ))}
              </optgroup>
            </select>
          </div>
        </div>

        {/* Model picker */}
        <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
          <label className="text-xs text-muted-foreground">Modele</label>
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
                    <option value="">Choisir un modele...</option>
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
                title="Rafraichir la liste des modeles"
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
              {testState === 'fail'    && <span className="text-red-400" title={testError}>\u2717 Erreur</span>}
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
          Cette machine est hors ligne. Le layer ne fonctionnera pas tant qu'elle n'est pas accessible.
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
      default_worker_model: sm.default_worker_model ?? dm.default_worker_model,
      endpoints: sm.endpoints ?? [],
    };
    reset(merged);
  }, [rawSettings, reset]);

  const saveMutation = useMutation({
    mutationFn: async (modelsData: ModelsSettings) => {
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

  const endpointStatuses: EndpointStatus[] = availableData?.endpoints ?? [];
  const endpoints = useWatch({ control, name: 'endpoints' }) ?? [];

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Modeles & Machines</h3>
        <p className="text-xs text-muted-foreground">
          Ajoutez vos machines locales ou distantes (Mac Studio, MacBook, serveur...) puis assignez-les aux layers Fast et Deep.
          Chaque layer peut utiliser une machine differente ou un provider cloud.
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
            Assignez une source et un modele a chaque layer
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

      {/* ── Default worker model ── */}
      <div className="rounded-lg border border-border bg-background p-4 flex items-center gap-3 flex-wrap">
        <label className="text-xs font-medium whitespace-nowrap">Modele worker par defaut :</label>
        <Controller
          control={control}
          name="default_worker_model"
          render={({ field }) => (
            <select
              className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5"
              value={field.value}
              onChange={field.onChange}
            >
              <option value="haiku">Haiku (rapide / economique)</option>
              <option value="sonnet">Sonnet (equilibre)</option>
              <option value="opus">Opus (puissant)</option>
            </select>
          )}
        />
        <span className="text-xs text-muted-foreground">
          Utilise pour les workers en arriere-plan et l'execution des cartes
        </span>
      </div>

      {/* ── Save button ── */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          className="btn-primary text-sm px-5 py-2 rounded"
          disabled={saveStatus === 'saving'}
        >
          {saveStatus === 'saving' ? 'Enregistrement...' : 'Enregistrer'}
        </button>
        {saveStatus === 'saved' && <span className="text-xs text-green-400">{'\u2713'} Enregistre</span>}
        {saveStatus === 'error' && <span className="text-xs text-red-400">{'\u2717'} Erreur</span>}
      </div>

    </form>
  );
}
