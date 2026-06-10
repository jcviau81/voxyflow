/**
 * ModelPanel — WorkerClassesPanel: worker class CRUD, per-class
 * endpoint/model/effort editing.
 */

import { useState } from 'react';
import type { WorkerClass, ProviderMeta, ProviderEndpoint, EndpointStatus, ModelsSettings } from './types';
import { EMPTY_WORKER_CLASS, EFFORT_OPTIONS, LISTABLE_PROVIDERS, STATIC_MODELS } from './constants';
import { newId, shortUrl, providerLabel, apiFetch } from './utils';
import { SourceOptions } from './shared';

interface WorkerClassesPanelProps {
  workerClasses: WorkerClass[];
  onChange: (classes: WorkerClass[]) => void;
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
  editingSection: string | null;
  setEditingSection: (s: string | null) => void;
  saveAll: (overrides?: Partial<ModelsSettings>) => Promise<void>;
  isSaving: boolean;
}

export function WorkerClassesPanel({
  workerClasses, onChange, providers, endpoints, endpointStatuses,
  editingSection, setEditingSection, saveAll, isSaving,
}: WorkerClassesPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<WorkerClass | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // A different section is currently being edited → lock our buttons.
  const lockedByOther = editingSection !== null && !editingSection.startsWith('worker-class:');

  // Per-class model lists (fetched when source changes)
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);

  function startAdd() {
    if (editingSection !== null) return;
    const wc: WorkerClass = { ...EMPTY_WORKER_CLASS, id: newId() };
    setDraft(wc);
    setIsAdding(true);
    setEditingId(wc.id);
    setAvailableModels([]);
    setSaveError(null);
    setEditingSection(`worker-class:${wc.id}`);
  }

  function startEdit(wc: WorkerClass) {
    if (editingSection !== null) return;
    setDraft({ ...wc });
    setIsAdding(false);
    setEditingId(wc.id);
    setAvailableModels([]);
    setSaveError(null);
    setEditingSection(`worker-class:${wc.id}`);
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
    setSaveError(null);
    setEditingSection(null);
  }

  async function saveEdit() {
    if (!draft || !draft.name.trim()) return;
    const existing = workerClasses.find(c => c.id === draft.id);
    const newClasses = existing
      ? workerClasses.map(c => c.id === draft.id ? draft : c)
      : [...workerClasses, draft];
    // Update form state first (keeps Controller in sync) then persist.
    onChange(newClasses);
    setSaveError(null);
    try {
      await saveAll({ worker_classes: newClasses });
      setDraft(null);
      setEditingId(null);
      setIsAdding(false);
      setAvailableModels([]);
      // saveAll() clears editingSection on success.
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  async function removeClass(id: string) {
    if (editingSection !== null) return;
    const newClasses = workerClasses.filter(c => c.id !== id);
    onChange(newClasses);
    try {
      await saveAll({ worker_classes: newClasses });
    } catch {
      // Revert on failure
      onChange(workerClasses);
    }
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
      return ep ? (ep.name || shortUrl(ep.url)) : 'Unknown provider';
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
                {wc.effort && (
                  <span className="ml-2 px-1.5 py-0.5 rounded bg-muted font-mono" title="Reasoning effort (CLI workers)">
                    effort: {wc.effort}
                  </span>
                )}
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
                className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => startEdit(wc)}
                disabled={editingSection !== null}
              >
                Edit
              </button>
              <button
                type="button"
                className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent text-red-400 disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={() => removeClass(wc.id)}
                disabled={editingSection !== null}
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
              <SourceOptions
                providers={providers}
                endpoints={endpoints}
                endpointStatuses={endpointStatuses}
              />
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

          {/* Reasoning effort */}
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">Reasoning effort</label>
            <select
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              value={draft.effort ?? ''}
              onChange={e => setDraft({ ...draft, effort: e.target.value })}
            >
              {EFFORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <span className="text-[11px] text-muted-foreground">
              CLI workers only — Claude <code>--effort</code>, Codex <code>model_reasoning_effort</code> (max → high).
              Default = the model's own effort.
            </span>
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
              disabled={!draft.name.trim() || isSaving}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      )}

      {/* Add button */}
      {!isAdding && (
        <button
          type="button"
          className="rounded-lg border border-dashed border-border bg-background/50 p-3 flex items-center justify-center gap-2 hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          onClick={startAdd}
          disabled={lockedByOther || (editingSection !== null && !isAdding)}
        >
          <span className="text-lg text-muted-foreground">+</span>
          <span className="text-xs text-muted-foreground">Add a worker class</span>
        </button>
      )}
    </div>
  );
}
