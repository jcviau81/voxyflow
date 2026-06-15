/**
 * ModelPanel — small presentational pieces shared by LayerRow, MachinesGrid,
 * WorkerClassesPanel, DefaultWorkerModelSection and ComparisonPanel.
 */

import { useState, useEffect } from 'react';
import { modelsApi } from '@/lib/apiClient';
import type { ProviderMeta, ProviderEndpoint, EndpointStatus, ModelCapabilities } from './types';
import { shortUrl, providerLabel, formatContext } from './utils';

// ── SourceOptions ────────────────────────────────────────────────────────────
// Shared <optgroup> contents for every source picker (Layers, Worker Classes,
// Default Worker, Comparison). Renders the optional "Layer Aliases" group, then
// "My Providers" (saved endpoints, with a reachability bullet) and "Cloud
// Providers". Extracted to keep all pickers in sync — previously this JSX was
// duplicated 4x and the reachability bullets had already diverged (escaped
// ● vs literal ● glyphs).

interface SourceOptionsProps {
  providers: ProviderMeta[];
  endpoints: ProviderEndpoint[];
  endpointStatuses: EndpointStatus[];
  aliasOptions?: { value: string; label: string }[];
}

export function SourceOptions({ providers, endpoints, endpointStatuses, aliasOptions }: SourceOptionsProps) {
  return (
    <>
      {aliasOptions && aliasOptions.length > 0 && (
        <optgroup label="Layer Aliases">
          {aliasOptions.map(o => (
            <option key={o.value} value={`alias:${o.value}`}>{o.label}</option>
          ))}
        </optgroup>
      )}
      {endpoints.length > 0 && (
        <optgroup label="My Providers">
          {endpoints.map(ep => {
            const st = endpointStatuses.find(s => s.id === ep.id);
            const dot = st ? (st.reachable ? '● ' : '○ ') : '  ';
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
    </>
  );
}

// ── StatusDot ──────────────────────────────────────────────────────────────

export function StatusDot({ reachable, size = 'sm' }: { reachable: boolean | null; size?: 'sm' | 'md' }) {
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

export function CapabilityBadges({ model }: { model: string }) {
  const [caps, setCaps] = useState<ModelCapabilities | null>(null);

  useEffect(() => {
    if (!model) { setCaps(null); return; }
    const controller = new AbortController();
    modelsApi.capabilities(model, { signal: controller.signal })
      .then(d => setCaps(d))
      .catch((e) => {
        if ((e as { name?: string })?.name !== 'AbortError') {
          console.warn('[ModelPanel] capabilities fetch failed', model, e);
        }
      });
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
