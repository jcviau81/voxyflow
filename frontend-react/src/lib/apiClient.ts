/**
 * apiClient — shared typed HTTP helpers.
 *
 * Wraps `fetch` with JSON parsing and error normalisation. For destructive /
 * secret-writing routes, call `authFetch` directly (from `authClient.ts`).
 * This module is for the public/idempotent routes that everyone uses.
 */

/** JSON fetch with error normalisation. Throws `Error(detail)` on non-2xx. */
export async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── /api/models/ helpers ────────────────────────────────────────────────────

export type ModelCapabilities = {
  model: string;
  provider: string;
  supports_tools: boolean;
  supports_vision: boolean;
  context_window: number;
  max_output_tokens: number;
};

export const modelsApi = {
  providers: <T>() => apiFetch<T>('/api/models/providers'),
  available: <T>() => apiFetch<T>('/api/models/available'),

  /** List models by saved endpoint id, OR by (provider_type, url). */
  list(params: { endpointId: string } | { providerType: string; url: string }): Promise<string[]> {
    let url: string;
    if ('endpointId' in params) {
      url = `/api/models/list?endpoint_id=${encodeURIComponent(params.endpointId)}`;
    } else {
      url = `/api/models/list?provider_type=${encodeURIComponent(params.providerType)}&url=${encodeURIComponent(params.url)}`;
    }
    return apiFetch<string[]>(url);
  },

  capabilities(model: string, init?: RequestInit): Promise<ModelCapabilities> {
    return apiFetch<ModelCapabilities>(
      `/api/models/capabilities?model=${encodeURIComponent(model)}`,
      init,
    );
  },

  test<T>(body: unknown): Promise<T> {
    return apiFetch<T>('/api/models/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },

  benchmark<T>(body: unknown): Promise<T> {
    return apiFetch<T>('/api/models/benchmark', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
};
