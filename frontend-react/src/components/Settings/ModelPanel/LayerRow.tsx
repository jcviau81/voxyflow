/**
 * ModelPanel — LayerRow: per-layer (fast/deep/haiku) source + model selection,
 * model listing, ping test state machine.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import type {
  LayerKey, ModelLayerConfig, ModelsSettings, ProviderMeta,
  ProviderEndpoint, EndpointStatus, TestResult,
} from './types';
import { LAYER_META, NO_URL_PROVIDERS, NO_KEY_PROVIDERS, LISTABLE_PROVIDERS, STATIC_MODELS } from './constants';
import { isThinkingModel, shortUrl, providerLabel, apiFetch } from './utils';
import { SourceOptions, StatusDot, CapabilityBadges } from './shared';

interface LayerRowProps {
  layerKey: LayerKey;
  control: ReturnType<typeof useForm<ModelsSettings>>['control'];
  watch: ReturnType<typeof useForm<ModelsSettings>>['watch'];
  setValue: ReturnType<typeof useForm<ModelsSettings>>['setValue'];
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
  editingSection: string | null;
  setEditingSection: (s: string | null) => void;
  saveAll: (overrides?: Partial<ModelsSettings>) => Promise<void>;
  isSaving: boolean;
}

export function LayerRow({
  layerKey, control, watch, setValue, providers, endpoints, endpointStatuses,
  editingSection, setEditingSection, saveAll, isSaving,
}: LayerRowProps) {
  const meta = LAYER_META[layerKey];
  const prefix = layerKey;

  const sectionKey = `layer:${layerKey}`;
  const isEditing = editingSection === sectionKey;
  const lockedByOther = editingSection !== null && !isEditing;
  const snapshotRef = useRef<ModelLayerConfig | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  // 1M context beta — only offered for Sonnet 4+ models.
  // Takes effect via Anthropic SDK (provider_type="anthropic"); no-op for CLI
  // since Claude Code negotiates its own context via the Max subscription.
  const is_sonnet_4 = (modelValue ?? '').toLowerCase().includes('sonnet-4');
  const is_cli_layer = effectiveType === 'cli';

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
          // Saved endpoint: send endpoint_id only — the backend resolves the real
          // url/api_key server-side (the frontend only ever sees redacted '***' keys).
          // Ad-hoc layer: backend resolves a '***' api_key from saved settings.
          ...(ep
            ? { endpoint_id: ep.id }
            : {
                provider_type: layer.provider_type,
                provider_url: layer.provider_url,
                api_key: layer.api_key,
              }),
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

  // ── View/Edit mode handlers ─────────────────────────────────────────────
  const layerEnabled = useWatch({ control, name: `${prefix}.enabled` as const });

  function startEdit() {
    if (editingSection !== null) return;
    snapshotRef.current = { ...(watch(prefix) as ModelLayerConfig) };
    setSaveError(null);
    setEditingSection(sectionKey);
  }

  function cancelEdit() {
    if (snapshotRef.current) {
      const snap = snapshotRef.current;
      setValue(`${prefix}.enabled`,       snap.enabled);
      setValue(`${prefix}.provider_type`, snap.provider_type);
      setValue(`${prefix}.provider_url`,  snap.provider_url);
      setValue(`${prefix}.api_key`,       snap.api_key);
      setValue(`${prefix}.model`,         snap.model);
      setValue(`${prefix}.endpoint_id`,   snap.endpoint_id);
      setValue(`${prefix}.context_1m`,    snap.context_1m);
    }
    snapshotRef.current = null;
    setSaveError(null);
    setEditingSection(null);
  }

  async function saveEdit() {
    setSaveError(null);
    try {
      const layerVals = watch(prefix) as ModelLayerConfig;
      await saveAll({ [layerKey]: layerVals } as Partial<ModelsSettings>);
      snapshotRef.current = null;
      // saveAll() clears editingSection on success.
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  // ── View mode ───────────────────────────────────────────────────────────
  if (!isEditing) {
    const sourceLabel = activeEndpoint
      ? (activeEndpoint.name || shortUrl(activeEndpoint.url))
      : providerLabel(providerType ?? '');
    return (
      <div className="rounded-lg border border-border bg-background p-4 flex items-center gap-4" data-layer={layerKey}>
        <span className="text-lg">{meta.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{meta.label}</span>
            {endpointId && endpointStatus && (
              <StatusDot reachable={endpointStatus.reachable} />
            )}
            <span className="text-xs text-muted-foreground">{sourceLabel}</span>
            {meta.showEnabled && layerEnabled === false && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-muted text-muted-foreground">disabled</span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {modelValue
              ? <span className="font-mono">{modelValue}</span>
              : <span className="italic">{meta.placeholder ? meta.placeholder : 'No model selected'}</span>}
          </div>
          {meta.description && (
            <div className="text-xs text-muted-foreground mt-0.5 italic">{meta.description}</div>
          )}
          <CapabilityBadges model={modelValue ?? ''} />
          {isEndpointOffline && (
            <div className="text-xs text-red-400 mt-1">{'⚠'} Provider offline</div>
          )}
        </div>
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          onClick={startEdit}
          disabled={lockedByOther}
        >
          Edit
        </button>
      </div>
    );
  }

  // ── Edit mode ───────────────────────────────────────────────────────────
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
              <SourceOptions
                providers={providers}
                endpoints={endpoints}
                endpointStatuses={endpointStatuses}
              />
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
                {modelsLoading ? '...' : '↻'}
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
              {testState === 'ok'      && <span className="text-green-400">{testLatency != null ? `✓ ${testLatency}ms` : '✓ OK'}</span>}
              {testState === 'fail'    && <span className="text-red-400" title={testError}>{'✗'} Error</span>}
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
          This provider is offline. The layer will not work until it is reachable.
        </div>
      )}

      <div className="flex flex-col gap-0.5">
        <CapabilityBadges model={modelValue ?? ''} />
        {thinking && (
          <div className="text-xs" style={{ color: 'var(--color-accent)' }}>
            Thinking model -- /no_think applied automatically
          </div>
        )}
        {is_sonnet_4 && (
          <Controller
            control={control}
            name={`${prefix}.context_1m`}
            render={({ field }) => (
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer mt-1">
                <input
                  type="checkbox"
                  className="setting-checkbox"
                  checked={!!field.value}
                  onChange={(e) => field.onChange(e.target.checked)}
                />
                <span>1M context (Sonnet 4 beta)</span>
                {is_cli_layer && (
                  <span className="text-[10px] opacity-70">
                    — CLI mode: managed by Anthropic, toggle is a no-op
                  </span>
                )}
              </label>
            )}
          />
        )}
        {testState === 'fail' && testError && (
          <div className="text-xs text-red-400 truncate max-w-md">{testError}</div>
        )}
      </div>

      {/* Save/Cancel */}
      <div className="flex gap-2 justify-end items-center pt-1">
        {saveError && (
          <span className="text-xs text-red-400 mr-auto">{saveError}</span>
        )}
        <button
          type="button"
          className="text-xs px-3 py-1 rounded border border-border hover:bg-accent text-muted-foreground"
          onClick={cancelEdit}
          disabled={isSaving}
        >
          Cancel
        </button>
        <button
          type="button"
          className="text-xs px-4 py-1 rounded border border-border hover:bg-accent font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={saveEdit}
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </div>
  );
}
