/**
 * WorkerPanel — Hierarchical live view of worker tasks.
 *
 * Pure view over useWorkerStore — no local state, no polling.
 * Groups workers by project, then by card/chat context.
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { KeyboardEvent } from 'react';
import { Loader2, MessageSquare, Send, ExternalLink, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWS } from '../../providers/WebSocketProvider';
import { useProjectStore } from '../../stores/useProjectStore';
import { useWorkerStore, type WorkerInfo, type CliSessionInfo } from '../../stores/useWorkerStore';

// ── Constants ────────────────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set<WorkerInfo['status']>(['done', 'failed', 'cancelled']);

// ── Helpers ──────────────────────────────────────────────────────────────────

function getElapsed(startedAt: number, completedAt?: number): string {
  const end = completedAt ?? Date.now();
  const ms = end - startedAt;
  if (ms < 1000) return '<1s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function getModelEmoji(model?: string): string {
  switch (model) {
    case 'haiku': return '\u{1F7E1}';   // yellow circle
    case 'sonnet': return '\u{1F535}';   // blue circle
    case 'opus': return '\u{1F7E3}';     // purple circle
    default: return '\u{1F535}';
  }
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StatusIndicator({ status }: { status: WorkerInfo['status'] }) {
  switch (status) {
    case 'pending':
      return <Loader2 size={14} className="text-muted-foreground animate-spin" />;
    case 'running':
      return <div className="w-3.5 h-3.5 border-2 border-accent border-t-transparent rounded-full animate-spin [animation-duration:0.5s]" />;
    case 'done':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-green-500">{'\u2713'}</span>;
    case 'failed':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-red-500">{'\u2715'}</span>;
    case 'cancelled':
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold text-muted-foreground">{'\u2298'}</span>;
    default:
      return <span className="inline-flex items-center justify-center w-3.5 h-3.5 text-[10px] font-bold" />;
  }
}

interface TaskRowProps {
  worker: WorkerInfo;
  cliSession?: CliSessionInfo;
  onCancel: (taskId: string) => void;
  onDismiss: (taskId: string) => void;
  onSteer: (taskId: string, message: string) => void;
}

function TaskRow({ worker, cliSession, onCancel, onDismiss, onSteer }: TaskRowProps) {
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerInput, setSteerInput] = useState('');
  const [expanded, setExpanded] = useState(false);
  const steerRef = useRef<HTMLInputElement>(null);
  const selectCard = useProjectStore((s) => s.selectCard);

  const handleSteerSubmit = () => {
    const msg = steerInput.trim();
    if (!msg) return;
    onSteer(worker.taskId, msg);
    setSteerInput('');
    setSteerOpen(false);
  };

  const handleSteerKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSteerSubmit();
    if (e.key === 'Escape') { setSteerOpen(false); setSteerInput(''); }
  };

  useEffect(() => {
    if (steerOpen) steerRef.current?.focus();
  }, [steerOpen]);

  const elapsed = getElapsed(worker.startedAt, worker.completedAt);

  const statusClasses =
    worker.status === 'running' ? 'border-accent border-l-[3px]'
    : worker.status === 'done' ? 'opacity-65 border-green-500 border-l-[3px]'
    : worker.status === 'failed' ? 'opacity-75 border-red-500 border-l-[3px]'
    : worker.status === 'cancelled' ? 'opacity-65 border-muted-foreground border-l-[3px]'
    : '';

  const modelBgClass =
    worker.model === 'haiku' ? 'bg-yellow-500/20'
    : worker.model === 'opus' ? 'bg-purple-500/20'
    : 'bg-blue-500/20';

  return (
    <div
      className={cn(
        'relative flex items-start gap-2 p-2 bg-muted/50 rounded-lg border border-border transition-all duration-200',
        statusClasses,
      )}
      data-task-id={worker.taskId}
    >
      <div className="shrink-0"><StatusIndicator status={worker.status} /></div>

      <span className={cn('inline-flex items-center justify-center w-5 h-5 rounded text-xs shrink-0 mt-px', modelBgClass)}>
        {getModelEmoji(worker.model)}
      </span>

      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold text-foreground truncate">{formatAction(worker.action)}</div>
        <div className="text-xs text-muted-foreground truncate">{worker.description.substring(0, 60)}</div>

        {/* Tool count */}
        {worker.toolCount > 0 && (
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {worker.toolCount} tool{worker.toolCount !== 1 ? 's' : ''}
            {worker.lastTool ? ` — ${worker.lastTool}` : ''}
          </div>
        )}

        {/* CLI session info */}
        {cliSession && (
          <div className="text-[10px] text-muted-foreground mt-0.5">
            pid {cliSession.pid} | {cliSession.model}
          </div>
        )}

        {/* Card link */}
        {worker.cardId && (
          <button
            className="inline-flex items-center gap-1 mt-0.5 text-[10px] text-accent hover:text-accent/80 transition-colors"
            title="Open linked card"
            onClick={(e) => { e.stopPropagation(); selectCard(worker.cardId!); }}
          >
            <ExternalLink size={9} />
            <span>card</span>
          </button>
        )}

        {/* Error */}
        {worker.status === 'failed' && worker.error && (
          <div className="text-xs mt-1 text-red-400">{worker.error.substring(0, 200)}</div>
        )}

        {/* Result summary */}
        {worker.completedAt && worker.resultSummary && worker.status !== 'failed' && (
          <div
            className={cn(
              'text-xs mt-1 text-muted-foreground',
              worker.resultSummary.length > 60 && 'cursor-pointer hover:text-foreground',
            )}
            onClick={
              worker.resultSummary.length > 60
                ? (e) => { e.stopPropagation(); setExpanded((v) => !v); }
                : undefined
            }
          >
            {expanded
              ? worker.resultSummary.substring(0, 200)
              : worker.resultSummary.substring(0, 60) + (worker.resultSummary.length > 60 ? '\u2026' : '')}
          </div>
        )}
      </div>

      {/* Elapsed */}
      <div className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
        {worker.completedAt ? elapsed : `${elapsed}\u2026`}
      </div>

      {/* Steer + Cancel for active */}
      {!worker.completedAt && (
        <div className="shrink-0 flex items-center gap-1">
          <button
            className="text-xs text-muted-foreground hover:text-accent transition-colors"
            title="Steer this worker"
            onClick={(e) => { e.stopPropagation(); setSteerOpen((o) => !o); }}
          >
            <MessageSquare size={11} />
          </button>
          <button
            className="text-xs text-muted-foreground hover:text-red-400 transition-colors"
            title="Cancel task"
            onClick={(e) => { e.stopPropagation(); onCancel(worker.taskId); }}
          >
            &times;
          </button>
        </div>
      )}

      {/* Dismiss for terminal */}
      {(worker.status === 'failed' || worker.status === 'cancelled') && (
        <button
          className="shrink-0 text-xs text-muted-foreground hover:text-red-400 transition-colors"
          title="Dismiss"
          onClick={(e) => { e.stopPropagation(); onDismiss(worker.taskId); }}
        >
          {'\u2715'}
        </button>
      )}

      {/* Steering mini-chat */}
      {steerOpen && !worker.completedAt && (
        <div
          className="absolute left-0 right-0 top-full mt-1 z-10 flex items-center gap-1 bg-card border border-border rounded-md px-2 py-1 shadow-md"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            ref={steerRef}
            type="text"
            value={steerInput}
            onChange={(e) => setSteerInput(e.target.value)}
            onKeyDown={handleSteerKey}
            placeholder="Steer worker\u2026"
            className="flex-1 text-xs bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
          />
          <button
            className="text-accent hover:text-accent/80 transition-colors disabled:opacity-40"
            disabled={!steerInput.trim()}
            onClick={handleSteerSubmit}
          >
            <Send size={12} />
          </button>
        </div>
      )}
    </div>
  );
}

// ── Group header ─────────────────────────────────────────────────────────────

interface GroupProps {
  label: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}

function Group({ label, children, defaultOpen = true }: GroupProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="mb-1">
      <button
        className="flex items-center gap-1 w-full px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronRight size={10} className={cn('transition-transform', open && 'rotate-90')} />
        {label}
      </button>
      {open && <div className="flex flex-col gap-1.5 mt-1">{children}</div>}
    </div>
  );
}

// ── Grouping logic ───────────────────────────────────────────────────────────

interface WorkerGroup {
  label: string;
  workers: WorkerInfo[];
}

function groupWorkers(workers: WorkerInfo[], projects: Record<string, string>): WorkerGroup[] {
  // Group by projectId
  const byProject: Record<string, WorkerInfo[]> = {};
  const general: WorkerInfo[] = [];

  for (const w of workers) {
    if (w.projectId) {
      (byProject[w.projectId] ??= []).push(w);
    } else {
      general.push(w);
    }
  }

  const groups: WorkerGroup[] = [];

  // Project groups
  for (const [pid, projectWorkers] of Object.entries(byProject)) {
    const projectName = projects[pid] || pid.slice(0, 12);
    groups.push({
      label: `Project: ${projectName}`,
      workers: sortWorkers(projectWorkers),
    });
  }

  // General group
  if (general.length > 0) {
    groups.push({
      label: 'General',
      workers: sortWorkers(general),
    });
  }

  return groups;
}

function sortWorkers(workers: WorkerInfo[]): WorkerInfo[] {
  return [...workers].sort((a, b) => {
    const aActive = !a.completedAt ? 0 : 1;
    const bActive = !b.completedAt ? 0 : 1;
    if (aActive !== bActive) return aActive - bActive;
    return b.startedAt - a.startedAt;
  });
}

// ── CLI Session Row ─────────────────────────────────────────────────────────

function CliSessionRow({ session }: { session: CliSessionInfo }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, []);
  const elapsed = getElapsed(session.startedAt * 1000);
  const typeLabel = session.type === 'chat' ? 'Chat' : 'Worker';
  return (
    <div className="flex items-center gap-1.5 px-1.5 py-1 rounded bg-muted/40 text-[11px]">
      <div className="w-3.5 h-3.5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin [animation-duration:1.5s]" />
      <span className="font-medium truncate flex-1">
        {getModelEmoji(session.model)} {session.model} — {typeLabel}
      </span>
      <span className="text-muted-foreground tabular-nums shrink-0">{elapsed}</span>
      <span className="text-muted-foreground text-[9px] shrink-0">pid:{session.pid}</span>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export function WorkerPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const [, setTick] = useState(0);

  const { send } = useWS();
  const workers = useWorkerStore((s) => s.workers);
  const cliSessions = useWorkerStore((s) => s.cliSessions);
  const dismissTask = useWorkerStore((s) => s.dismissTask);
  const clearTerminal = useWorkerStore((s) => s.clearTerminal);
  const projects = useProjectStore((s) => s.projects);

  // Map project IDs to names for grouping labels
  const projectNames = useMemo(() => {
    const names: Record<string, string> = {};
    for (const p of projects) {
      names[p.id] = p.name || p.id.slice(0, 12);
    }
    return names;
  }, [projects]);

  // Build CLI session lookup by taskId
  const cliByTask = useMemo(() => {
    const map: Record<string, CliSessionInfo> = {};
    for (const cs of Object.values(cliSessions)) {
      if (cs.taskId) map[cs.taskId] = cs;
    }
    return map;
  }, [cliSessions]);

  // ── Elapsed time ticker ───────────────────────────────────────────────
  useEffect(() => {
    const timer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  // ── Actions ───────────────────────────────────────────────────────────
  const cancelTask = useCallback(
    (taskId: string) => {
      // Find the CLI session for this task to get sessionId
      const cs = cliByTask[taskId];
      send('task:cancel', { taskId, sessionId: cs?.id });
    },
    [send, cliByTask],
  );

  const steerTask = useCallback(
    (taskId: string, message: string) => {
      if (!message.trim()) return;
      const cs = cliByTask[taskId];
      send('task:steer', { taskId, sessionId: cs?.id, message: message.trim() });
    },
    [send, cliByTask],
  );

  // ── Derived ───────────────────────────────────────────────────────────
  const allWorkers = useMemo(() => Object.values(workers), [workers]);
  const groups = useMemo(() => groupWorkers(allWorkers, projectNames), [allWorkers, projectNames]);
  const activeCount = allWorkers.filter((w) => !TERMINAL_STATUSES.has(w.status)).length;
  const terminalCount = allWorkers.filter((w) => TERMINAL_STATUSES.has(w.status)).length;

  // CLI sessions not linked to any worker task (persistent chats, etc.)
  const orphanCliSessions = useMemo(() => {
    const taskLinked = new Set(Object.values(cliSessions).filter((cs) => cs.taskId).map((cs) => cs.id));
    return Object.values(cliSessions).filter((cs) => !taskLinked.has(cs.id) || !cs.taskId);
  }, [cliSessions]);

  // Group orphan CLI sessions by project
  const cliGroups = useMemo(() => {
    const byProject: Record<string, CliSessionInfo[]> = {};
    const general: CliSessionInfo[] = [];
    for (const cs of orphanCliSessions) {
      if (cs.projectId) {
        (byProject[cs.projectId] ??= []).push(cs);
      } else {
        general.push(cs);
      }
    }
    const result: { label: string; sessions: CliSessionInfo[] }[] = [];
    for (const [pid, sessions] of Object.entries(byProject)) {
      result.push({ label: projectNames[pid] || pid.slice(0, 12), sessions });
    }
    if (general.length > 0) {
      result.push({ label: 'General', sessions: general });
    }
    return result;
  }, [orphanCliSessions, projectNames]);

  const totalActive = activeCount + orphanCliSessions.length;

  // ── Render ────────────────────────────────────────────────────────────
  return (
    <div
      className={cn(
        'flex flex-col h-full bg-secondary border-l border-r border-border shrink-0 overflow-hidden transition-all duration-200',
        collapsed ? 'w-[42px]' : 'w-60',
      )}
      data-testid="worker-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Workers</span>
          {totalActive > 0 && (
            <span className="bg-primary text-primary-foreground text-xs font-bold px-1.5 rounded-full min-w-[18px] text-center">{totalActive}</span>
          )}
        </div>

        {terminalCount > 0 && !collapsed && (
          <button
            className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            title="Clear finished tasks"
            onClick={clearTerminal}
          >
            Clear ({terminalCount})
          </button>
        )}

        <button
          className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          title={collapsed ? 'Expand' : 'Collapse'}
          onClick={() => setCollapsed((c) => !c)}
        >
          {collapsed ? '\u25C0' : '\u25B6'}
        </button>
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
          {/* CLI Sessions */}
          {cliGroups.length > 0 && (
            <Group label="CLI Sessions" defaultOpen>
              {cliGroups.map((cg) => (
                <div key={cg.label}>
                  <div className="text-[9px] uppercase tracking-wider text-muted-foreground px-1 mb-0.5">{cg.label}</div>
                  {cg.sessions.map((cs) => (
                    <CliSessionRow key={cs.id} session={cs} />
                  ))}
                </div>
              ))}
            </Group>
          )}

          {/* Worker Tasks */}
          {groups.length > 0 ? (
            groups.map((group) => (
              <Group key={group.label} label={group.label}>
                {group.workers.map((w) => (
                  <TaskRow
                    key={w.taskId}
                    worker={w}
                    cliSession={cliByTask[w.taskId]}
                    onCancel={cancelTask}
                    onDismiss={dismissTask}
                    onSteer={steerTask}
                  />
                ))}
              </Group>
            ))
          ) : orphanCliSessions.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-8">No active workers</div>
          ) : null}
        </div>
      )}
    </div>
  );
}
