/**
 * ModelPanel — "My Providers" section: named endpoints (machines) management.
 * MachineForm, MachineCard, AddMachineCard and the MachinesGrid container.
 */

import { useState, useEffect, useRef } from 'react';
import type { ProviderEndpoint, ProviderMeta, EndpointStatus, ModelsSettings } from './types';
import {
  NO_KEY_PROVIDERS, LISTABLE_PROVIDERS, LOCAL_PROVIDER_TYPES,
  CLOUD_PROVIDER_TYPES, CLOUD_DEFAULT_URLS,
} from './constants';
import { newId, shortUrl, providerLabel, apiFetch } from './utils';
import { StatusDot } from './shared';

// ── MachineForm ───────────────────────────────────────────────────────────

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
  // Snapshot of the endpoint as it was when the form opened — used to restore the
  // saved ('***'-redacted) api_key if the user toggles the type away and back.
  const original = useRef(draft).current;
  const localProviders = allProviders.filter(p => LOCAL_PROVIDER_TYPES.has(p.type));
  const cloudProviders = allProviders.filter(p => CLOUD_PROVIDER_TYPES.has(p.type));

  return (
    <div className="rounded-lg border border-border bg-background p-4 flex flex-col gap-3">
      <div className="text-sm font-medium text-foreground">
        {isNew ? 'Add a provider' : 'Edit provider'}
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-muted-foreground">Provider name</label>
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
            // Keep the original key when returning to the original type —
            // clearing it would overwrite the saved key with '' on save.
            const apiKey = pt === original.provider_type ? original.api_key : '';
            onChange({ ...draft, provider_type: pt, url: defaultUrl, api_key: apiKey, name: autoName });
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
  disabled?: boolean;
}

function MachineCard({ endpoint, status, models, modelsLoading, onEdit, onDelete, disabled }: MachineCardProps) {
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
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent flex-1 disabled:opacity-40 disabled:cursor-not-allowed"
          onClick={onEdit}
          disabled={disabled}
        >
          Edit
        </button>
        <button
          type="button"
          className="text-xs px-2 py-0.5 rounded border border-border hover:bg-accent text-red-400 disabled:opacity-40 disabled:cursor-not-allowed"
          onClick={onDelete}
          disabled={disabled}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

// ── AddMachineCard ────────────────────────────────────────────────────────

function AddMachineCard({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      className="rounded-lg border border-dashed border-border bg-background/50 p-4 flex flex-col items-center justify-center gap-2 min-h-[140px] hover:bg-accent/30 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
      onClick={onClick}
      disabled={disabled}
    >
      <span className="text-2xl text-muted-foreground">+</span>
      <span className="text-xs text-muted-foreground">Add a provider</span>
    </button>
  );
}

// ── MachinesGrid ──────────────────────────────────────────────────────────

interface MachinesGridProps {
  endpoints: ProviderEndpoint[];
  onChange: (endpoints: ProviderEndpoint[]) => void;
  providers: ProviderMeta[];
  endpointStatuses: EndpointStatus[];
  editingSection: string | null;
  setEditingSection: (s: string | null) => void;
  saveAll: (overrides?: Partial<ModelsSettings>) => Promise<void>;
}

export function MachinesGrid({
  endpoints, onChange, providers, endpointStatuses,
  editingSection, setEditingSection, saveAll,
}: MachinesGridProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<ProviderEndpoint | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const lockedByOther = editingSection !== null && !editingSection.startsWith('endpoint:');

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
    if (editingSection !== null) return;
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
    setSaveError(null);
    setEditingSection(`endpoint:${ep.id}`);
  }

  function startEdit(ep: ProviderEndpoint) {
    if (editingSection !== null) return;
    setDraft({ ...ep });
    setIsAdding(false);
    setEditingId(ep.id);
    setSaveError(null);
    setEditingSection(`endpoint:${ep.id}`);
  }

  function cancelEdit() {
    setDraft(null);
    setEditingId(null);
    setIsAdding(false);
    setSaveError(null);
    setEditingSection(null);
  }

  async function saveEdit() {
    if (!draft) return;
    const existing = endpoints.find(e => e.id === draft.id);
    const newEndpoints = existing
      ? endpoints.map(e => e.id === draft.id ? draft : e)
      : [...endpoints, draft];
    onChange(newEndpoints);
    setSaveError(null);
    try {
      await saveAll({ endpoints: newEndpoints });
      // Clear cached models for this endpoint so they get re-fetched
      setModelsByEndpoint(prev => {
        const next = { ...prev };
        delete next[draft.id];
        return next;
      });
      setDraft(null);
      setEditingId(null);
      setIsAdding(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    }
  }

  async function removeEndpoint(id: string) {
    if (editingSection !== null) return;
    const newEndpoints = endpoints.filter(e => e.id !== id);
    onChange(newEndpoints);
    try {
      await saveAll({ endpoints: newEndpoints });
      setModelsByEndpoint(prev => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } catch {
      onChange(endpoints);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">My Providers</span>
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
              disabled={editingSection !== null}
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
          <AddMachineCard onClick={startAdd} disabled={lockedByOther || editingSection !== null} />
        )}
      </div>
      {saveError && (
        <div className="text-xs text-red-400">{saveError}</div>
      )}
    </div>
  );
}
