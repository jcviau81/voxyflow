/**
 * ModelPanel — Models & Providers settings panel.
 *
 * Redesigned UX:
 *  - Section 1: "My Providers" — card grid showing each endpoint as a provider card
 *    with real-time status dot, provider type, short URL, available models, edit/delete
 *  - Section 2: Layer configuration — Fast / Deep rows with source dropdown
 *    combining providers + cloud providers, model picker, test button
 *  - Inline form for adding/editing providers (no modal)
 *
 * This index is the orchestrator: it owns the react-hook-form state, the save
 * mutation and the single `editingSection` lock (see ./types.ts for the
 * contract), and composes the section components from the sibling files.
 */

import { useState, useEffect } from 'react';
import { useForm, Controller, useWatch } from 'react-hook-form';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authFetch } from '@/lib/authClient';
import { modelsApi } from '@/lib/apiClient';
import type { LayerKey, ModelsSettings, AppSettings, ProviderMeta, AvailableData, EndpointStatus } from './types';
import { DEFAULT_MODELS, DEFAULT_WORKER_CLASSES } from './constants';
import { apiFetch } from './utils';
import { MachinesGrid } from './MachinesGrid';
import { LayerRow } from './LayerRow';
import { WorkerClassesPanel } from './WorkerClassesPanel';
import { ComparisonPanel } from './ComparisonPanel';
import { DefaultWorkerModelSection } from './DefaultWorkerModelSection';

// Re-export the shared types other code may want.
export type { ProviderEndpoint, ModelsSettings, ModelLayerConfig, WorkerClass, LayerKey, EditingSection } from './types';

export function ModelPanel() {
  const queryClient = useQueryClient();

  const { data: providers = [] } = useQuery<ProviderMeta[]>({
    queryKey: ['providers'],
    queryFn: () => modelsApi.providers<ProviderMeta[]>(),
    staleTime: 60_000,
  });

  const { data: availableData } = useQuery<AvailableData>({
    queryKey: ['models-available'],
    queryFn: () => modelsApi.available<AvailableData>(),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });

  const { data: rawSettings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => apiFetch<AppSettings>('/api/settings'),
  });

  const { control, reset, watch, setValue, getValues } = useForm<ModelsSettings>({
    defaultValues: DEFAULT_MODELS,
  });

  useEffect(() => {
    if (!rawSettings) return;
    const dm = DEFAULT_MODELS;
    const sm = (rawSettings.models || {}) as Partial<ModelsSettings>;
    const merged: ModelsSettings = {
      fast: { ...dm.fast, ...(sm.fast || {}) },
      deep: { ...dm.deep, ...(sm.deep || {}) },
      haiku: { ...dm.haiku, ...(sm.haiku || {}) },
      default_worker_model: sm.default_worker_model ?? dm.default_worker_model,
      default_worker_provider_type: sm.default_worker_provider_type ?? dm.default_worker_provider_type,
      default_worker_endpoint_id: sm.default_worker_endpoint_id ?? dm.default_worker_endpoint_id,
      default_worker_effort: sm.default_worker_effort ?? dm.default_worker_effort,
      endpoints: sm.endpoints ?? [],
      worker_classes: sm.worker_classes?.length ? sm.worker_classes : DEFAULT_WORKER_CLASSES,
    };
    reset(merged);
  }, [rawSettings, reset]);

  // Backfill empty provider_type from /api/models/available without resetting
  // the whole form (which would wipe unsaved worker_class changes).
  useEffect(() => {
    if (!availableData) return;
    const liveLayers = (availableData.layers ?? {}) as Record<string, { provider_type?: string }>;
    for (const key of ['fast', 'deep', 'haiku'] as const) {
      const current = (getValues(`${key}.provider_type`) || '').trim();
      if (!current) {
        const inferred = (liveLayers[key]?.provider_type || '').trim();
        if (inferred) setValue(`${key}.provider_type`, inferred);
      }
    }
  }, [availableData, getValues, setValue]);

  const saveMutation = useMutation({
    mutationFn: async (modelsData: ModelsSettings) => {
      // Always fetch fresh settings to avoid overwriting changes from other panels
      const current = await apiFetch<AppSettings>('/api/settings');
      const res = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...current, models: modelsData }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${res.status}`);
      }
      return res.json() as Promise<AppSettings>;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['models-available'] });
    },
  });

  // ── Single editing-section state ───────────────────────────────────────
  // Only one section (Fast/Deep/Default/WorkerClass:<id>/Endpoint:<id>) can be
  // in edit mode at a time. Edit buttons on other sections are disabled while
  // editingSection is non-null. Save persists then clears it; Cancel just clears.
  const [editingSection, setEditingSection] = useState<string | null>(null);

  // Persist the form state, optionally overriding fields with fresh values that
  // may not have propagated through react-hook-form yet (avoids onChange race).
  async function saveAll(overrides?: Partial<ModelsSettings>): Promise<void> {
    const merged = { ...(getValues() as ModelsSettings), ...(overrides ?? {}) };
    await saveMutation.mutateAsync(merged);
    setEditingSection(null);
  }

  const endpointStatuses: EndpointStatus[] = availableData?.endpoints ?? [];
  const endpoints = useWatch({ control, name: 'endpoints' }) ?? [];

  return (
    <div className="p-6 flex flex-col gap-6" data-testid="settings-models">

      {/* ── Header ── */}
      <div>
        <h3 className="text-base font-semibold mb-1">Models & Providers</h3>
        <p className="text-xs text-muted-foreground">
          Add your local or remote providers (Mac Studio, MacBook, server...) then assign them to the Fast and Deep layers.
          Each layer can use a different provider.
        </p>
      </div>

      {/* ── Section 1: Providers Grid ── */}
      <div data-section="my-providers">
        <Controller
          control={control}
          name="endpoints"
          render={({ field }) => (
            <MachinesGrid
              endpoints={field.value ?? []}
              onChange={field.onChange}
              providers={providers}
              endpointStatuses={endpointStatuses}
              editingSection={editingSection}
              setEditingSection={setEditingSection}
              saveAll={saveAll}
            />
          )}
        />
      </div>

      {/* ── Section 2: Layers ── */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Layers</span>
          <span className="text-xs text-muted-foreground">
            Assign a source and model to each layer
          </span>
        </div>

        {(['fast', 'deep', 'haiku'] as LayerKey[]).map((key) => (
          <LayerRow
            key={key}
            layerKey={key}
            control={control}
            watch={watch}
            setValue={setValue}
            providers={providers}
            endpoints={endpoints}
            endpointStatuses={endpointStatuses}
            editingSection={editingSection}
            setEditingSection={setEditingSection}
            saveAll={saveAll}
            isSaving={saveMutation.isPending}
          />
        ))}
      </div>

      {/* ── Default Worker Model ── */}
      <DefaultWorkerModelSection
        control={control}
        watch={watch}
        setValue={setValue}
        providers={providers}
        endpoints={endpoints}
        endpointStatuses={endpointStatuses}
        editingSection={editingSection}
        setEditingSection={setEditingSection}
        saveAll={saveAll}
        isSaving={saveMutation.isPending}
      />

      {/* ── Section 3: Worker Classes ── */}
      <div data-section="worker-classes">
        <Controller
          control={control}
          name="worker_classes"
          render={({ field }) => (
            <WorkerClassesPanel
              workerClasses={field.value ?? []}
              onChange={field.onChange}
              providers={providers}
              endpoints={endpoints}
              endpointStatuses={endpointStatuses}
              editingSection={editingSection}
              setEditingSection={setEditingSection}
              saveAll={saveAll}
              isSaving={saveMutation.isPending}
            />
          )}
        />
      </div>

      {/* ── Section 4: LLM Comparison ── */}
      <ComparisonPanel
        providers={providers}
        endpoints={endpoints}
        endpointStatuses={endpointStatuses}
        workerClasses={watch('worker_classes') ?? []}
        onAssignToClass={(classId, config) => {
          const current = watch('worker_classes') ?? [];
          const updated = current.map(wc =>
            wc.id === classId ? { ...wc, ...config } : wc
          );
          setValue('worker_classes', updated);
          saveAll({ worker_classes: updated }).catch(() => {});
        }}
      />

    </div>
  );
}
