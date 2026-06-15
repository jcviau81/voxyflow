/**
 * ModelPanel — ComparisonPanel (Worker Class Benchmark): A/B model benchmark UI.
 * The Benchmark* types are only used here, so they stay local to this file.
 */

import { useState } from 'react';
import type { ProviderMeta, ProviderEndpoint, EndpointStatus, WorkerClass } from './types';
import { LISTABLE_PROVIDERS, STATIC_MODELS } from './constants';
import { apiFetch } from './utils';
import { SourceOptions } from './shared';

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

export function ComparisonPanel({ providers, endpoints, endpointStatuses, workerClasses, onAssignToClass }: ComparisonPanelProps) {
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
          setPrompt(data.prompt);
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
          <SourceOptions
            providers={providers}
            endpoints={endpoints}
            endpointStatuses={endpointStatuses}
          />
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
              placeholder={slot.providerType === 'cli' ? 'claude-sonnet-4' : slot.providerType === 'codex' ? 'gpt-5.5' : slot.providerType === 'anthropic' ? 'claude-sonnet-4' : 'model name'}
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
