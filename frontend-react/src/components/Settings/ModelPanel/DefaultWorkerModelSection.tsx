/**
 * ModelPanel — DefaultWorkerModelSection: default worker model/provider/effort
 * settings (fallback when no worker class matches the dispatched intent).
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import type { ModelsSettings, ProviderMeta, ProviderEndpoint, EndpointStatus, TestResult } from './types';
import {
  LISTABLE_PROVIDERS, STATIC_MODELS, EFFORT_OPTIONS,
  LAYER_ALIAS_OPTIONS, LAYER_ALIAS_VALUES,
} from './constants';
import { isThinkingModel, shortUrl, providerLabel, apiFetch } from './utils';
import { SourceOptions, StatusDot, CapabilityBadges } from './shared';

interface DefaultWorkerModelSectionProps {
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

export function DefaultWorkerModelSection({
  control, watch, setValue, providers, endpoints, endpointStatuses,
  editingSection, setEditingSection, saveAll, isSaving,
}: DefaultWorkerModelSectionProps) {
  const sectionKey = 'default-worker-model';
  const isEditing = editingSection === sectionKey;
  const lockedByOther = editingSection !== null && !isEditing;

  const model        = useWatch({ control, name: 'default_worker_model' }) ?? 'sonnet';
  const providerType = useWatch({ control, name: 'default_worker_provider_type' }) ?? '';
  const endpointId   = useWatch({ control, name: 'default_worker_endpoint_id' }) ?? '';
  const effort       = useWatch({ control, name: 'default_worker_effort' }) ?? '';

  // Snapshot for cancel
  const snapshotRef = useRef<{ model: string; providerType: string; endpointId: string; effort: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Source = "alias:<sonnet|haiku|opus>" | "ep:<id>" | "pt:<provider_type>"
  const isAlias = !providerType && !endpointId && LAYER_ALIAS_VALUES.has(model);
  const selectionValue = isAlias
    ? `alias:${model}`
    : (endpointId ? `ep:${endpointId}` : (providerType ? `pt:${providerType}` : 'alias:sonnet'));

  const activeEndpoint = endpoints.find(e => e.id === endpointId);
  const effectiveType  = activeEndpoint ? activeEndpoint.provider_type : providerType;
  const endpointStatus = endpointStatuses.find(s => s.id === endpointId);
  const isEndpointOffline = endpointId && endpointStatus && !endpointStatus.reachable;
  const thinking = !isAlias && isThinkingModel(model ?? '');

  const canListModels = !isAlias && LISTABLE_PROVIDERS.has(effectiveType);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading]     = useState(false);
  const [testState, setTestState]             = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testLatency, setTestLatency]         = useState<number | null>(null);
  const [testError, setTestError]             = useState<string>('');
  const prevSelection = useRef('');

  const fetchModels = useCallback(async () => {
    if (!canListModels) return;
    setModelsLoading(true);
    if (!endpointId && STATIC_MODELS[effectiveType]) {
      setAvailableModels(STATIC_MODELS[effectiveType]);
    }
    try {
      const pmeta = providers.find(p => p.type === effectiveType);
      const baseUrl = activeEndpoint?.url ?? pmeta?.default_url ?? '';
      const url = endpointId
        ? `/api/models/list?endpoint_id=${encodeURIComponent(endpointId)}`
        : `/api/models/list?provider_type=${encodeURIComponent(effectiveType)}&url=${encodeURIComponent(baseUrl)}`;
      const models = await apiFetch<string[]>(url);
      setAvailableModels(models.length > 0 ? models : (STATIC_MODELS[effectiveType] ?? []));
    } catch {
      setAvailableModels(STATIC_MODELS[effectiveType] ?? []);
    } finally {
      setModelsLoading(false);
    }
  }, [canListModels, endpointId, effectiveType, providers, activeEndpoint]);

  useEffect(() => {
    if (selectionValue === prevSelection.current) return;
    prevSelection.current = selectionValue;
    if (canListModels) fetchModels();
    else setAvailableModels([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectionValue, canListModels]);

  function handleSelectionChange(value: string) {
    if (value.startsWith('alias:')) {
      const alias = value.slice('alias:'.length);
      setValue('default_worker_model', alias);
      setValue('default_worker_provider_type', '');
      setValue('default_worker_endpoint_id', '');
      setAvailableModels([]);
      return;
    }
    if (value.startsWith('ep:')) {
      const id = value.slice(3);
      const ep = endpoints.find(e => e.id === id);
      if (!ep) return;
      setValue('default_worker_endpoint_id', id);
      setValue('default_worker_provider_type', ep.provider_type);
      setValue('default_worker_model', '');
      setAvailableModels([]);
      return;
    }
    if (value.startsWith('pt:')) {
      const pt = value.slice(3);
      setValue('default_worker_endpoint_id', '');
      setValue('default_worker_provider_type', pt);
      setValue('default_worker_model', '');
      setAvailableModels([]);
    }
  }

  async function handleTest() {
    setTestState('testing');
    setTestLatency(null);
    setTestError('');
    const ep = activeEndpoint;
    const pmeta = providers.find(p => p.type === effectiveType);
    try {
      const data = await apiFetch<TestResult>('/api/models/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // Saved endpoint: send endpoint_id only — the backend resolves the real
          // url/api_key server-side (the frontend only ever sees redacted '***' keys).
          ...(ep
            ? { endpoint_id: ep.id }
            : {
                provider_type: providerType,
                provider_url:  pmeta?.default_url ?? '',
                api_key:       '',
              }),
          model,
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

  function startEdit() {
    if (editingSection !== null) return;
    snapshotRef.current = {
      model: (watch('default_worker_model') ?? 'sonnet') as string,
      providerType: (watch('default_worker_provider_type') ?? '') as string,
      endpointId: (watch('default_worker_endpoint_id') ?? '') as string,
      effort: (watch('default_worker_effort') ?? '') as string,
    };
    setSaveError(null);
    setEditingSection(sectionKey);
  }

  function cancelEdit() {
    if (snapshotRef.current) {
      setValue('default_worker_model',         snapshotRef.current.model);
      setValue('default_worker_provider_type', snapshotRef.current.providerType);
      setValue('default_worker_endpoint_id',   snapshotRef.current.endpointId);
      setValue('default_worker_effort',        snapshotRef.current.effort);
    }
    snapshotRef.current = null;
    setSaveError(null);
    setEditingSection(null);
  }

  async function saveEdit() {
    setSaveError(null);
    try {
      await saveAll({
        default_worker_model:         (watch('default_worker_model') ?? '') as string,
        default_worker_provider_type: (watch('default_worker_provider_type') ?? '') as string,
        default_worker_endpoint_id:   (watch('default_worker_endpoint_id') ?? '') as string,
        default_worker_effort:        (watch('default_worker_effort') ?? '') as string,
      });
      snapshotRef.current = null;
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  const sourceLabel = isAlias
    ? (LAYER_ALIAS_OPTIONS.find(o => o.value === model)?.label ?? `Layer alias: ${model}`)
    : (activeEndpoint
        ? (activeEndpoint.name || shortUrl(activeEndpoint.url))
        : providerLabel(providerType));

  const showModelDropdown = canListModels && availableModels.length > 0;

  const ICON  = '🤖'; // 🤖
  const LABEL = 'Default Worker';
  const DESCRIPTION = 'Used by workers when no worker class matches the dispatched intent.';

  // ── View mode ───────────────────────────────────────────────────────────
  if (!isEditing) {
    return (
      <div className="rounded-lg border border-border bg-background p-4 flex items-center gap-4">
        <span className="text-lg">{ICON}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{LABEL}</span>
            {endpointId && endpointStatus && (
              <StatusDot reachable={endpointStatus.reachable} />
            )}
            <span className="text-xs text-muted-foreground">{sourceLabel}</span>
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            {isAlias
              ? <span className="italic">Routes through the layer alias</span>
              : (model
                  ? <span className="font-mono">{model}</span>
                  : <span className="italic">No model selected</span>)}
            {effort && (
              <span className="ml-2 px-1.5 py-0.5 rounded bg-muted font-mono" title="Reasoning effort (CLI workers)">
                effort: {effort}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 italic">{DESCRIPTION}</div>
          {!isAlias && <CapabilityBadges model={model ?? ''} />}
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
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <span className="text-lg">{ICON}</span>
        <span className="text-sm font-semibold">{LABEL}</span>
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
                aliasOptions={LAYER_ALIAS_OPTIONS}
              />
            </select>
          </div>
        </div>

        {/* Model picker — hidden in alias mode */}
        {!isAlias && (
          <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
            <label className="text-xs text-muted-foreground">Model</label>
            <div className="flex items-center gap-1.5">
              {showModelDropdown ? (
                <Controller
                  control={control}
                  name="default_worker_model"
                  render={({ field }) => (
                    <select
                      className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
                      value={field.value ?? ''}
                      onChange={field.onChange}
                    >
                      <option value="">Select model...</option>
                      {availableModels.map(m => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  )}
                />
              ) : (
                <Controller
                  control={control}
                  name="default_worker_model"
                  render={({ field }) => (
                    <input
                      type="text"
                      className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
                      placeholder="e.g. claude-sonnet-4-6, qwen2.5:32b"
                      value={field.value ?? ''}
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
        )}

        {/* Reasoning effort — applies to CLI workers (alias or explicit provider) */}
        <div className="flex flex-col gap-1 min-w-[150px]">
          <label className="text-xs text-muted-foreground">Effort</label>
          <Controller
            control={control}
            name="default_worker_effort"
            render={({ field }) => (
              <select
                className="setting-input text-sm rounded border border-input bg-background px-2 py-1.5 flex-1"
                value={field.value ?? ''}
                onChange={field.onChange}
              >
                {EFFORT_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            )}
          />
        </div>

        {/* Test button + result — only when a real provider is selected */}
        {!isAlias && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">&nbsp;</label>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-secondary text-xs px-3 py-1.5 rounded border border-border hover:bg-accent shrink-0"
                disabled={testState === 'testing' || !model}
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
        )}
      </div>

      {/* Warnings and badges */}
      {isEndpointOffline && (
        <div className="text-xs px-2 py-1 rounded bg-red-500/10 text-red-400 border border-red-500/20">
          This provider is offline. The default worker will not work until it is reachable.
        </div>
      )}

      <div className="flex flex-col gap-0.5">
        {!isAlias && <CapabilityBadges model={model ?? ''} />}
        {thinking && (
          <div className="text-xs" style={{ color: 'var(--color-accent)' }}>
            Thinking model -- /no_think applied automatically
          </div>
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
