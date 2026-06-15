/**
 * DelegateBadge — collapsable inline badge for voxyflow.delegate tool_use blocks.
 *
 * Collapsed: shows action · complexity · first 80 chars of description
 * Expanded:  full JSON payload + status (queued/running/done/failed) + artifact link
 *
 * Decision locked (JC, 2026-05-27):
 * - Badge render is systematic — no settings toggle.
 * - Artifact link shown when worker.complete has been called.
 *
 * Status source (2026-06-07): derived from useWorkerStore, which useWorkerSync
 * keeps live via the WS task:* events. No per-badge polling — a single REST
 * hydrate runs only when the task isn't in the live store (e.g. reload of an
 * old conversation). Terminal state is retained locally so a badge keeps
 * showing "done" after the store TTL-purges the task.
 */

import { memo, useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronRight, Loader2, CheckCircle, XCircle, Clock, ExternalLink } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useWorkerStore, type WorkerInfo } from '../../stores/useWorkerStore';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DelegatePayload {
  action: string;
  description: string;
  complexity?: 'simple' | 'standard' | 'complex';
  card_id?: string;
  context?: string;
  // Runtime fields injected by the orchestrator (not part of schema)
  _task_id?: string;
}

type WorkerStatus = 'queued' | 'running' | 'done' | 'failed' | 'timed_out' | 'cancelled' | 'unknown';

interface WorkerState {
  status: WorkerStatus;
  artifactUrl?: string;
  summary?: string;
}

// ---------------------------------------------------------------------------
// Status badge helpers
// ---------------------------------------------------------------------------

function statusIcon(status: WorkerStatus) {
  switch (status) {
    case 'queued':   return <Clock className="w-3 h-3 text-yellow-400" />;
    case 'running':  return <Loader2 className="w-3 h-3 text-blue-400 animate-spin" />;
    case 'done':     return <CheckCircle className="w-3 h-3 text-green-400" />;
    case 'failed':   return <XCircle className="w-3 h-3 text-red-400" />;
    case 'timed_out':return <XCircle className="w-3 h-3 text-orange-400" />;
    case 'cancelled':return <XCircle className="w-3 h-3 text-gray-400" />;
    default:         return <Clock className="w-3 h-3 text-muted-foreground" />;
  }
}

function statusLabel(status: WorkerStatus): string {
  switch (status) {
    case 'queued':    return 'queued';
    case 'running':   return 'running…';
    case 'done':      return 'done';
    case 'failed':    return 'failed';
    case 'timed_out': return 'timed out';
    case 'cancelled': return 'cancelled';
    default:          return status;
  }
}

function complexityColor(complexity?: string): string {
  switch (complexity) {
    case 'simple':   return 'text-green-400';
    case 'complex':  return 'text-orange-400';
    default:         return 'text-blue-400'; // standard or undefined
  }
}

// ---------------------------------------------------------------------------
// Worker status hook — store-derived, no polling
// ---------------------------------------------------------------------------

/** Map the worker store's status vocabulary to the badge's. */
function mapStoreStatus(s: WorkerInfo['status']): WorkerStatus {
  switch (s) {
    case 'pending':   return 'queued';
    case 'running':   return 'running';
    case 'done':      return 'done';
    case 'failed':    return 'failed';
    case 'cancelled': return 'cancelled';
    case 'crashed':   return 'failed';
    default:          return 'unknown';
  }
}

function useWorkerStatus(taskId: string | undefined): WorkerState {
  // Live entry from the WS-fed store (undefined until task:started, or after
  // the store TTL-purges a completed task).
  const stored = useWorkerStore((s) => (taskId ? s.workers[taskId] : undefined));
  const [state, setState] = useState<WorkerState>({ status: 'unknown' });
  // One-shot hydrate guard, keyed by taskId.
  const hydratedRef = useRef<string | null>(null);

  // Mirror the live store entry into local state. Local state is retained when
  // the store purges the task, so the badge keeps its terminal label.
  useEffect(() => {
    if (!taskId || !stored) return;
    hydratedRef.current = taskId; // store had it — skip the REST hydrate
    setState({
      status: mapStoreStatus(stored.status),
      summary: stored.resultSummary,
      artifactUrl: stored.completedAt
        ? `/api/worker-tasks/${encodeURIComponent(taskId)}/artifact`
        : undefined,
    });
  }, [taskId, stored]);

  // One-shot REST hydrate when the task isn't in the live store (e.g. reload of
  // an old conversation whose worker finished long ago). No interval.
  useEffect(() => {
    if (!taskId || stored || hydratedRef.current === taskId) return;
    hydratedRef.current = taskId;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/worker-tasks/${encodeURIComponent(taskId)}`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        const rawStatus: string = data.status ?? 'unknown';
        const status: WorkerStatus = rawStatus === 'pending' ? 'queued' : (rawStatus as WorkerStatus);
        setState({
          status,
          summary: data.result_summary ?? undefined,
          artifactUrl: data.completed_at
            ? `/api/worker-tasks/${encodeURIComponent(taskId)}/artifact`
            : undefined,
        });
      } catch {
        // ignore transient errors
      }
    })();
    return () => { cancelled = true; };
  }, [taskId, stored]);

  return state;
}

// ---------------------------------------------------------------------------
// DelegateBadge component
// ---------------------------------------------------------------------------

interface DelegateBadgeProps {
  payload: DelegatePayload;
  className?: string;
}

export const DelegateBadge = memo(function DelegateBadge({ payload, className }: DelegateBadgeProps) {
  const [expanded, setExpanded] = useState(false);
  const worker = useWorkerStatus(payload._task_id);

  const {
    action,
    description,
    complexity,
    _task_id: taskId,
  } = payload;

  // Truncate description to 80 chars for collapsed view
  const descPreview = description.length > 80
    ? description.slice(0, 77) + '…'
    : description;

  // Build display payload (strip internal fields)
  const displayPayload = Object.fromEntries(
    Object.entries(payload).filter(([k]) => !k.startsWith('_'))
  );

  const effectiveStatus: WorkerStatus = taskId ? (worker.status === 'unknown' ? 'queued' : worker.status) : 'queued';

  return (
    <div
      className={cn(
        'inline-flex flex-col w-full rounded border border-border/50 bg-muted/30',
        'text-xs my-1 overflow-hidden select-none',
        className,
      )}
    >
      {/* Collapsed header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded(e => !e)}
        className={cn(
          'flex items-center gap-1.5 px-2 py-1 hover:bg-muted/50 transition-colors',
          'text-left w-full',
        )}
        aria-expanded={expanded}
        title={expanded ? 'Collapse delegate details' : 'Expand delegate details'}
      >
        {/* Chevron */}
        {expanded
          ? <ChevronDown className="w-3 h-3 shrink-0 text-muted-foreground" />
          : <ChevronRight className="w-3 h-3 shrink-0 text-muted-foreground" />
        }

        {/* Status icon */}
        {statusIcon(effectiveStatus)}

        {/* Action badge */}
        <span className="font-mono font-semibold text-amber-400 shrink-0">{action}</span>

        {/* Complexity badge (optional) */}
        {complexity && (
          <span className={cn('font-mono shrink-0', complexityColor(complexity))}>
            ·{complexity}
          </span>
        )}

        {/* Description preview */}
        <span className="text-muted-foreground truncate min-w-0">
          · {descPreview}
        </span>

        {/* Status label (right-aligned) */}
        <span className="ml-auto shrink-0 text-muted-foreground">
          {statusLabel(effectiveStatus)}
        </span>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-3 py-2 border-t border-border/30 space-y-2">
          {/* JSON payload */}
          <div>
            <span className="text-muted-foreground font-semibold uppercase tracking-wide text-[10px]">Payload</span>
            <pre className="mt-1 text-[11px] text-foreground/80 bg-muted/50 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
              {JSON.stringify(displayPayload, null, 2)}
            </pre>
          </div>

          {/* Status + task ID */}
          {taskId && (
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground font-semibold uppercase tracking-wide text-[10px]">Worker</span>
              <code className="text-[10px] text-foreground/60 font-mono">{taskId}</code>
              <div className="flex items-center gap-1">
                {statusIcon(effectiveStatus)}
                <span className="text-foreground/60">{statusLabel(effectiveStatus)}</span>
              </div>
            </div>
          )}

          {/* Worker summary (when done) */}
          {worker.summary && (
            <div>
              <span className="text-muted-foreground font-semibold uppercase tracking-wide text-[10px]">Result</span>
              <p className="mt-1 text-[11px] text-foreground/70 whitespace-pre-wrap">{worker.summary}</p>
            </div>
          )}

          {/* Artifact link (when available) */}
          {worker.artifactUrl && (
            <a
              href={worker.artifactUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 transition-colors"
            >
              <ExternalLink className="w-3 h-3" />
              <span>View artifact</span>
            </a>
          )}
        </div>
      )}
    </div>
  );
});

export default DelegateBadge;
