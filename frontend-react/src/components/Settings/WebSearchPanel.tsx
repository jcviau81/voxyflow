/**
 * WebSearchPanel — Web Search settings & comparison.
 *
 * Currently exposes the SearXNG vs DuckDuckGo side-by-side comparison.
 * Lives in its own settings tab (separate from Models) since it doesn't
 * depend on layer/provider config.
 */

import { useState } from 'react';
import { Search } from 'lucide-react';
import { apiFetch } from '../../lib/apiClient';

interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
}

interface WebSearchEngineResult {
  success: boolean;
  engine: string;
  results: WebSearchResult[];
  count: number;
  latency_ms: number;
  error?: string;
}

interface WebSearchCompareResponse {
  query: string;
  searxng: WebSearchEngineResult;
  duckduckgo: WebSearchEngineResult;
}

function renderEngine(res: WebSearchEngineResult) {
  const latencyColor = res.latency_ms < 800
    ? 'text-green-400'
    : res.latency_ms < 2000
      ? 'text-yellow-400'
      : 'text-red-400';
  return (
    <div className="flex-1 min-w-[280px] flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold">{res.engine}</span>
        {res.success ? (
          <>
            <span className={`text-xs font-medium ${latencyColor}`}>{res.latency_ms}ms</span>
            <span className="text-xs text-muted-foreground">{res.count} results</span>
          </>
        ) : (
          <span className="text-xs text-red-400">Failed</span>
        )}
      </div>
      {!res.success && res.error && (
        <p className="text-xs text-red-400 bg-red-500/10 rounded p-2">{res.error}</p>
      )}
      {res.success && res.results.length === 0 && (
        <p className="text-xs text-muted-foreground">No results returned.</p>
      )}
      <div className="flex flex-col gap-2">
        {res.results.map((r, i) => (
          <div key={i} className="rounded border border-border bg-background p-2 flex flex-col gap-0.5">
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-medium text-blue-400 hover:underline truncate block"
            >
              {r.title}
            </a>
            <span className="text-[10px] text-muted-foreground truncate">{r.url}</span>
            {r.snippet && (
              <p className="text-xs text-foreground/80 mt-0.5 line-clamp-2">{r.snippet}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function WebSearchPanel() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<WebSearchCompareResponse | null>(null);
  const [error, setError] = useState('');

  async function runCompare() {
    if (!query.trim()) return;
    setLoading(true);
    setResult(null);
    setError('');
    try {
      const data = await apiFetch<WebSearchCompareResponse>('/api/models/websearch-compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: query.trim(), count: 5 }),
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Request failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-websearch">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Search size={16} />
        Web Search
      </h3>

      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Web Search Comparison</span>
          <span className="text-xs text-muted-foreground">SearXNG vs DuckDuckGo — same query, side-by-side</span>
        </div>

        <div className="flex gap-2 items-end">
          <div className="flex flex-col gap-1 flex-1">
            <label className="text-xs text-muted-foreground">Search query</label>
            <input
              type="text"
              className="setting-input text-sm rounded border border-input bg-background px-3 py-1.5 w-full"
              placeholder="e.g. best practices for RAG 2025"
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !loading) runCompare(); }}
            />
          </div>
          <button
            type="button"
            className="btn-secondary text-sm px-4 py-1.5 rounded border border-border hover:bg-accent font-medium shrink-0"
            disabled={!query.trim() || loading}
            onClick={runCompare}
          >
            {loading ? 'Searching...' : 'Compare'}
          </button>
        </div>

        {error && <p className="text-xs text-red-400">{error}</p>}

        {loading && (
          <div className="flex items-center gap-2 py-2">
            <span className="text-sm text-muted-foreground animate-pulse">Running both searches in parallel...</span>
          </div>
        )}

        {result && (
          <div className="flex gap-4 items-start flex-wrap">
            {renderEngine(result.searxng)}
            <div className="w-px bg-border self-stretch shrink-0" />
            {renderEngine(result.duckduckgo)}
          </div>
        )}
      </div>
    </div>
  );
}
