/**
 * WorkerOutputModal — Real-time output viewer for worker tasks.
 *
 * Running tasks:  streams tool:executed WS events as a live log.
 * Completed tasks: fetches the full artifact from the REST API.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import { X, Send, Terminal } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWS } from '../../providers/WebSocketProvider';
import type { WorkerInfo } from '../../stores/useWorkerStore';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ToolEvent {
  tool: string;
  args?: Record<string, unknown>;
  result?: string;
  toolCount: number;
  timestamp: number;
}

const TERMINAL_STATUSES = new Set(['done', 'failed', 'cancelled']);

// ── Helpers ───────────────────────────────────────────────────────────────────

function elapsed(startMs: number, endMs?: number): string {
  const ms = (endMs ?? Date.now()) - startMs;
  if (ms < 1000) return '<1s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function modelEmoji(model?: string): string {
  switch (model) {
    case 'haiku': return '\u{1F7E1}';
    case 'sonnet': return '\u{1F535}';
    case 'opus': return '\u{1F7E3}';
    default: return '\u26AA';
  }
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Extract readable text from an MCP tool result. */
function extractToolResult(result: unknown): string {
  if (!result) return '';
  if (typeof result === 'string') return result;

  // MCP format: { content: "<json_string>" }
  if (typeof result === 'object' && result !== null) {
    const r = result as Record<string, unknown>;
    const content = r.content ?? r.stdout ?? r.output ?? r.text ?? '';

    if (typeof content === 'string') {
      // Try to parse nested JSON (MCP serialized response)
      try {
        const parsed = JSON.parse(content);
        if (typeof parsed === 'object' && parsed !== null) {
          return parsed.content ?? parsed.stdout ?? parsed.output ?? parsed.text ?? content;
        }
        return content;
      } catch {
        return content;
      }
    }
    // Fallback: JSON.stringify the whole thing
    try {
      return JSON.stringify(result, null, 2);
    } catch {
      return String(result);
    }
  }
  return String(result);
}

// ── Component ─────────────────────────────────────────────────────────────────

export function WorkerOutputModal({ worker, onClose }: { worker: WorkerInfo; onClose: () => void }) {
  const { subscribe, send } = useWS();
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([]);
  const [artifact, setArtifact] = useState<string | null>(null);
  const [loadingArtifact, setLoadingArtifact] = useState(false);
  const [completed, setCompleted] = useState(TERMINAL_STATUSES.has(worker.status));
  const [steerInput, setSteerInput] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const steerRef = useRef<HTMLInputElement>(null);
  const [tick, setTick] = useState(0);

  const isActive = !completed;

  // Tick for elapsed time
  useEffect(() => {
    if (!isActive) return;
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, [isActive]);

  // Fetch full artifact
  const fetchArtifact = useCallback(async () => {
    setLoadingArtifact(true);
    try {
      const res = await fetch(`/api/worker-tasks/${worker.taskId}/artifact`);
      if (res.ok) {
        const data = await res.json();
        setArtifact(data.content ?? null);
      }
    } catch { /* ignore */ }
    setLoadingArtifact(false);
  }, [worker.taskId]);

  // Subscribe to live events for running tasks
  useEffect(() => {
    if (!isActive) return;
    const unsubs = [
      subscribe('tool:executed', (payload: Record<string, unknown>) => {
        if (payload.taskId !== worker.taskId) return;
        setToolEvents((prev) => [
          ...prev,
          {
            tool: (payload.tool as string) || 'unknown',
            args: payload.args as Record<string, unknown> | undefined,
            result: extractToolResult(payload.result),
            toolCount: (payload.toolCount as number) || 0,
            timestamp: Date.now(),
          },
        ]);
      }),
      subscribe('task:completed', (payload: Record<string, unknown>) => {
        if (payload.taskId !== worker.taskId) return;
        setCompleted(true);
      }),
      subscribe('task:cancelled', (payload: Record<string, unknown>) => {
        if (payload.taskId !== worker.taskId) return;
        setCompleted(true);
      }),
    ];
    return () => unsubs.forEach((u) => u());
  }, [subscribe, worker.taskId, isActive]);

  // Load artifact when completed
  useEffect(() => {
    if (completed) fetchArtifact();
  }, [completed, fetchArtifact]);

  // Auto-scroll on new events
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    // Only auto-scroll if already near bottom
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (atBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
  }, [toolEvents, artifact]);

  // Steer
  const handleSteer = () => {
    const msg = steerInput.trim();
    if (!msg) return;
    send('task:steer', { taskId: worker.taskId, message: msg });
    setSteerInput('');
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSteer();
    if (e.key === 'Escape') onClose();
  };

  // Close on Escape
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Suppress unused var warning for tick
  void tick;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-lg shadow-2xl w-[750px] max-w-[90vw] max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
          <div className="flex items-center gap-2">
            {isActive ? (
              <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse shrink-0" />
            ) : (
              <Terminal size={14} className="text-muted-foreground shrink-0" />
            )}
            <span className="font-semibold text-sm">{formatAction(worker.action)}</span>
            <span className="text-xs shrink-0">{modelEmoji(worker.model)}</span>
            <span className="text-xs text-muted-foreground">{worker.model}</span>
            <span className="text-xs text-muted-foreground tabular-nums">
              {elapsed(worker.startedAt, worker.completedAt)}
            </span>
            {!isActive && (
              <span
                className={cn(
                  'text-[10px] font-medium px-1.5 py-0.5 rounded',
                  worker.status === 'done'
                    ? 'bg-green-500/15 text-green-500'
                    : worker.status === 'failed'
                      ? 'bg-red-500/15 text-red-500'
                      : 'bg-muted text-muted-foreground',
                )}
              >
                {worker.status}
              </span>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-3 min-h-[200px]">
          {/* Live tool events */}
          {toolEvents.map((evt, i) => (
            <div key={i} className="border-l-2 border-accent/40 pl-3">
              <div className="flex items-center gap-2">
                <span className="text-accent font-semibold">{evt.tool}</span>
                <span className="text-muted-foreground/60 text-[10px] tabular-nums">
                  #{evt.toolCount}
                </span>
              </div>
              {evt.args && Object.keys(evt.args).length > 0 && (
                <div className="text-muted-foreground/70 mt-0.5 truncate max-w-full">
                  {Object.entries(evt.args)
                    .filter(([, v]) => v !== undefined && v !== null)
                    .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
                    .join(' ')
                    .slice(0, 200)}
                </div>
              )}
              {evt.result && (
                <pre className="text-muted-foreground whitespace-pre-wrap mt-1 max-h-[300px] overflow-y-auto bg-muted/30 rounded p-2 text-[11px] leading-relaxed">
                  {evt.result.slice(0, 5000)}
                  {evt.result.length > 5000 ? '\n\n... (truncated)' : ''}
                </pre>
              )}
            </div>
          ))}

          {/* Artifact for completed tasks */}
          {artifact !== null && (
            <div className="border-t border-border/30 pt-3">
              <div className="text-muted-foreground/60 text-[10px] uppercase tracking-wider mb-2">
                Full output
              </div>
              <pre className="text-foreground whitespace-pre-wrap text-[11px] leading-relaxed">
                {artifact}
              </pre>
            </div>
          )}

          {/* Loading / empty states */}
          {isActive && toolEvents.length === 0 && (
            <div className="text-muted-foreground text-center py-8 flex flex-col items-center gap-2">
              <div className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
              <span>Waiting for tool activity...</span>
            </div>
          )}
          {loadingArtifact && (
            <div className="text-muted-foreground text-center py-4">Loading output...</div>
          )}
          {!isActive && !loadingArtifact && artifact === null && toolEvents.length === 0 && (
            <div className="text-muted-foreground text-center py-8">No output available</div>
          )}
        </div>

        {/* Footer — steer input for active tasks */}
        {isActive && (
          <div className="border-t border-border px-4 py-2 flex items-center gap-2 shrink-0">
            <input
              ref={steerRef}
              type="text"
              value={steerInput}
              onChange={(e) => setSteerInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Steer worker..."
              className="flex-1 text-sm bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
            />
            <button
              className="text-accent hover:text-accent/80 disabled:opacity-40 transition-colors"
              disabled={!steerInput.trim()}
              onClick={handleSteer}
            >
              <Send size={14} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
