/**
 * WorkerPanel — Hierarchical session/worker view.
 *
 * Structure:
 *   SESSIONS
 *   └── Project Name
 *       ├── Project Chat - 🔵 Fast Session
 *       │   └── 🔵 sonnet — action — 45s… [steer][cancel]
 *       ├── Project Chat - 🟣 Deep Session
 *       │   └── 🟣 opus — action — 2m… [steer][cancel]
 *       └── Card: Title
 *           └── 🔵 sonnet — action — 1m… [steer][cancel]
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { KeyboardEvent, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Send, ExternalLink, ChevronRight, ChevronDown, Eye, Clock, X as XIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWS } from '../../providers/WebSocketProvider';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore } from '../../stores/useCardStore';
import { useWorkerStore, type WorkerInfo, type CliSessionInfo, type JobMeta } from '../../stores/useWorkerStore';
import { SYSTEM_PROJECT_ID } from '../../lib/constants';
import { WorkerOutputModal } from './WorkerOutputModal';

// ── Peek types ─────────────────────────────────────────────────────────────

interface PeekResult {
  task_id: string;
  action: string;
  model: string;
  status: string;
  tool_count: number;
  last_tool: string | null;
  recent_tools: string[];
  running_seconds: number;
  source: 'live' | 'db';
}

// ── Constants & Helpers ─────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set<WorkerInfo['status']>(['done', 'failed', 'cancelled', 'crashed']);

function elapsed(startMs: number, endMs?: number): string {
  const ms = (endMs ?? Date.now()) - startMs;
  if (ms < 1000) return '<1s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

function modelTier(model?: string): 'haiku' | 'sonnet' | 'opus' | null {
  if (!model) return null;
  const m = model.toLowerCase();
  if (m.includes('haiku')) return 'haiku';
  if (m.includes('opus')) return 'opus';
  if (m.includes('sonnet')) return 'sonnet';
  return null;
}

function modelEmoji(model?: string): string {
  switch (modelTier(model)) {
    case 'haiku': return '\u{1F7E1}';
    case 'sonnet': return '\u{1F535}';
    case 'opus': return '\u{1F7E3}';
    default: return '\u26AA';
  }
}

function modelLabel(model?: string): string {
  switch (modelTier(model)) {
    case 'haiku': return 'Fast';
    case 'sonnet': return 'sonnet';
    case 'opus': return 'Deep';
    default: return model ?? 'unknown';
  }
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Parse a canonical chatId ("project:<uuid>" / "card:<uuid>" / "job:<id>") into a label. */
function parseSessionLabel(chatId: string | null, cardTitles: Record<string, string>, jobMeta: Record<string, JobMeta>): string {
  if (!chatId) return 'Direct';
  if (chatId.startsWith('job:')) {
    const meta = jobMeta[chatId];
    return meta?.jobName || 'Scheduled Job';
  }
  if (chatId.startsWith('card:')) {
    const cardId = chatId.slice('card:'.length).split(':')[0];
    const title = cardTitles[cardId];
    return title ? `Card: ${title}` : `Card: ${cardId.slice(0, 8)}`;
  }
  return 'Project Chat';
}

// ── Session tree types ──────────────────────────────────────────────────────

interface SessionNode {
  chatId: string;
  label: string;
  cliSession?: CliSessionInfo;
  workers: WorkerInfo[];
  isAnalyzer?: boolean;
}

interface ProjectNode {
  projectId: string;
  projectName: string;
  sessions: SessionNode[];
}

// ── Build hierarchy ─────────────────────────────────────────────────────────

const SCHEDULER_GROUP_ID = '_scheduler';

function buildTree(
  allCli: CliSessionInfo[],
  allWorkers: WorkerInfo[],
  projectNames: Record<string, string>,
  cardTitles: Record<string, string>,
  jobMeta: Record<string, JobMeta>,
): ProjectNode[] {
  // Index workers by chatId (skip workers with no chatId)
  const workersByChatId: Record<string, WorkerInfo[]> = {};
  for (const w of allWorkers) {
    if (w.chatId) {
      (workersByChatId[w.chatId] ??= []).push(w);
    }
  }

  // Index CLI sessions by chatId
  const cliByChatId: Record<string, CliSessionInfo> = {};
  for (const cs of allCli) {
    if (cs.chatId) cliByChatId[cs.chatId] = cs;
  }

  // Collect all unique chatIds (from both CLI sessions and workers)
  const allChatIds = new Set<string>();
  for (const cs of allCli) if (cs.chatId) allChatIds.add(cs.chatId);
  for (const w of allWorkers) if (w.chatId) allChatIds.add(w.chatId);

  // Group chatIds by project — scheduler sessions go under _scheduler
  const chatIdsByProject: Record<string, Set<string>> = {};
  for (const chatId of allChatIds) {
    if (chatId.startsWith('job:')) {
      (chatIdsByProject[SCHEDULER_GROUP_ID] ??= new Set()).add(chatId);
      continue;
    }
    const cli = cliByChatId[chatId];
    const ws = workersByChatId[chatId];
    const pid = cli?.projectId || ws?.[0]?.projectId || '_general';
    (chatIdsByProject[pid] ??= new Set()).add(chatId);
  }

  // Build project nodes
  const projects: ProjectNode[] = [];
  for (const [pid, chatIds] of Object.entries(chatIdsByProject)) {
    const sessions: SessionNode[] = [];
    for (const chatId of chatIds) {
      const cli = cliByChatId[chatId];
      const ws = workersByChatId[chatId] || [];
      const label = parseSessionLabel(chatId, cardTitles, jobMeta);
      const sessionLabel = cli
        ? `${label} - ${modelEmoji(cli.model)} ${modelLabel(cli.model)}`
        : label;

      sessions.push({
        chatId,
        label: sessionLabel,
        cliSession: cli,
        workers: ws.sort((a, b) => {
          const aActive = TERMINAL_STATUSES.has(a.status) ? 1 : 0;
          const bActive = TERMINAL_STATUSES.has(b.status) ? 1 : 0;
          if (aActive !== bActive) return aActive - bActive;
          return b.startedAt - a.startedAt;
        }),
      });
    }

    // Sort sessions: active first
    sessions.sort((a, b) => {
      const aActive = a.cliSession || a.workers.some((w) => !TERMINAL_STATUSES.has(w.status)) ? 0 : 1;
      const bActive = b.cliSession || b.workers.some((w) => !TERMINAL_STATUSES.has(w.status)) ? 0 : 1;
      return aActive - bActive;
    });

    projects.push({
      projectId: pid,
      projectName: pid === SCHEDULER_GROUP_ID ? 'Scheduler' : pid === '_general' ? 'General' : pid === SYSTEM_PROJECT_ID ? 'Home' : (projectNames[pid] || pid.slice(0, 12)),
      sessions,
    });
  }

  // Sort: _scheduler always first, then active sessions, then inactive
  projects.sort((a, b) => {
    if (a.projectId === SCHEDULER_GROUP_ID) return -1;
    if (b.projectId === SCHEDULER_GROUP_ID) return 1;
    const aActive = a.sessions.some((s) => s.cliSession || s.workers.some((w) => !TERMINAL_STATUSES.has(w.status))) ? 0 : 1;
    const bActive = b.sessions.some((s) => s.cliSession || s.workers.some((w) => !TERMINAL_STATUSES.has(w.status))) ? 0 : 1;
    return aActive - bActive;
  });

  return projects;
}

// ── Worker row ──────────────────────────────────────────────────────────────

function WorkerRow({ worker, onCancel, onSteer, onSelect, isLast, peekData, peekExpanded, onTogglePeek, cardTitles, cliPid, parentChatId, projectId }: {
  worker: WorkerInfo;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  isLast?: boolean;
  peekData: PeekResult | null;
  peekExpanded: boolean;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
  cliPid?: number;
  parentChatId: string;
  projectId: string;
}) {
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerInput, setSteerInput] = useState('');
  const steerRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const msg = steerInput.trim();
    if (!msg) return;
    onSteer(worker.taskId, msg);
    setSteerInput('');
    setSteerOpen(false);
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') submit();
    if (e.key === 'Escape') { setSteerOpen(false); setSteerInput(''); }
  };

  useEffect(() => { if (steerOpen) steerRef.current?.focus(); }, [steerOpen]);

  const isActive = !TERMINAL_STATUSES.has(worker.status);
  const e = elapsed(worker.startedAt, worker.completedAt);

  // Show a card pill when the worker targets a card but the parent session
  // isn't the card's own chat (i.e., spawned from project-scope chat).
  const parentIsCardSession =
    worker.cardId != null && parentChatId === `card:${worker.cardId}`;
  const showCardPill = !!worker.cardId && !parentIsCardSession;
  const cardLabel = worker.cardId
    ? cardTitles[worker.cardId] || worker.cardId.slice(0, 8)
    : '';

  const selectCard = useProjectStore((s) => s.selectCard);
  const navigate = useNavigate();

  const handleRowClick = () => {
    onSelect(worker);
  };

  const handleCardPillClick = (ev: MouseEvent) => {
    ev.stopPropagation();
    if (!worker.cardId) return;
    if (projectId && projectId !== '_general' && projectId !== SCHEDULER_GROUP_ID) {
      navigate(projectId === SYSTEM_PROJECT_ID ? '/' : `/project/${projectId}`);
    }
    selectCard(worker.cardId);
  };

  const statusLabel =
    worker.status === 'running'   ? 'running'   :
    worker.status === 'pending'   ? 'pending'   :
    worker.status === 'done'      ? 'done'      :
    worker.status === 'failed'    ? 'failed'    :
    worker.status === 'crashed'   ? 'crashed'   : 'cancelled';

  const statusChipClasses = cn(
    'text-[9px] font-semibold uppercase px-1.5 py-0.5 rounded tracking-wider shrink-0',
    isActive && 'bg-accent/15 text-accent',
    worker.status === 'done' && 'bg-green-500/15 text-green-500',
    worker.status === 'failed' && 'bg-red-500/15 text-red-500',
    worker.status === 'crashed' && 'bg-orange-500/15 text-orange-500',
    worker.status === 'cancelled' && 'bg-muted text-muted-foreground',
  );

  return (
    <div className="relative group/worker">
      {/* Tree connector lines */}
      <div className={cn(
        'absolute left-0 top-0 w-px bg-border/40',
        isLast ? 'h-[18px]' : 'h-full',
      )} />
      <div className="absolute left-0 top-[18px] w-3 h-px bg-border/40" />

      <div
        className={cn(
          'ml-3 px-2 py-1.5 rounded cursor-pointer transition-colors',
          'hover:bg-accent/10 focus-within:bg-accent/10',
          !isActive && 'opacity-60',
        )}
        onClick={handleRowClick}
        role="button"
        tabIndex={0}
        aria-label={`Worker ${worker.model} — ${formatAction(worker.action)} — ${statusLabel}`}
        onKeyDown={(ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            handleRowClick();
          }
        }}
      >
        {/* ── Line 1: identity (model + card + pid) ─────────────────────── */}
        <div className="flex items-center gap-1.5 text-[12px] leading-tight">
          {isActive ? (
            <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin [animation-duration:0.6s] shrink-0" aria-label="running" />
          ) : (
            <span className={cn(
              'w-3 h-3 flex items-center justify-center text-[10px] font-bold shrink-0',
              worker.status === 'done' ? 'text-green-500' : worker.status === 'failed' ? 'text-red-500' : 'text-muted-foreground',
            )} aria-label={statusLabel}>
              {worker.status === 'done' ? '\u2713' : worker.status === 'failed' ? '\u2715' : '\u2298'}
            </span>
          )}

          <span className="shrink-0" aria-hidden="true">{modelEmoji(worker.model)}</span>
          <span className="font-semibold text-foreground truncate">{worker.model}</span>

          {showCardPill && (
            <>
              <span className="text-muted-foreground/50 shrink-0" aria-hidden="true">{'\u2022'}</span>
              <button
                className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-500 hover:bg-amber-500/25 focus-visible:ring-2 focus-visible:ring-amber-500/40 focus:outline-none shrink-0 max-w-[140px] truncate"
                title={`Open card: ${cardLabel}`}
                aria-label={`Open card ${cardLabel}`}
                onClick={handleCardPillClick}
              >
                Card: {cardLabel}
              </button>
            </>
          )}

          {cliPid != null && (
            <>
              <span className="text-muted-foreground/50 shrink-0" aria-hidden="true">{'\u2022'}</span>
              <span className="text-[10px] text-muted-foreground tabular-nums shrink-0" title="CLI subprocess pid">
                pid:{cliPid}
              </span>
            </>
          )}

          <span className={cn(statusChipClasses, 'ml-auto')}>{statusLabel}</span>
        </div>

        {/* ── Line 2: action + elapsed + tool progress ─────────────────── */}
        <div className="flex items-baseline gap-2 mt-0.5 text-[11px] text-muted-foreground">
          <span className="truncate flex-1">{formatAction(worker.action)}</span>
          <span className="tabular-nums shrink-0">{isActive ? `${e}\u2026` : e}</span>
        </div>

        {worker.toolCount > 0 && (
          <div className="mt-0.5 text-[10px] text-muted-foreground/80 truncate">
            {worker.toolCount} tool{worker.toolCount !== 1 ? 's' : ''}
            {worker.lastTool ? ` \u2014 ${worker.lastTool}` : ''}
          </div>
        )}

        {/* ── Action bar: hover / focus-within ──────────────────────────── */}
        {isActive && (
          <div
            className={cn(
              'flex items-center gap-1 mt-1 -mb-0.5 transition-opacity',
              'opacity-0 group-hover/worker:opacity-100 group-focus-within/worker:opacity-100',
              steerOpen && 'opacity-100',
            )}
            onClick={(ev) => ev.stopPropagation()}
          >
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-muted-foreground hover:text-accent hover:bg-accent/10 focus-visible:ring-2 focus-visible:ring-accent/40 focus:outline-none transition-colors"
              aria-label="Peek at tool calls"
              aria-expanded={peekExpanded}
              onClick={() => onTogglePeek(worker.taskId)}
            >
              <Eye size={12} aria-hidden="true" />
              <span>Peek</span>
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-muted-foreground hover:text-accent hover:bg-accent/10 focus-visible:ring-2 focus-visible:ring-accent/40 focus:outline-none transition-colors"
              aria-label="Steer worker"
              aria-expanded={steerOpen}
              onClick={() => setSteerOpen((o) => !o)}
            >
              <MessageSquare size={12} aria-hidden="true" />
              <span>Steer</span>
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-muted-foreground hover:text-red-400 hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-red-400/40 focus:outline-none transition-colors ml-auto"
              aria-label="Cancel worker"
              onClick={() => onCancel(worker.taskId)}
            >
              <XIcon size={12} aria-hidden="true" />
              <span>Cancel</span>
            </button>
          </div>
        )}

        {/* ── Peek panel ────────────────────────────────────────────────── */}
        {peekExpanded && peekData && (
          <div className="mt-1.5 p-2 rounded bg-muted/50 border border-border/30 text-[10px] text-muted-foreground space-y-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-foreground">{peekData.action}</span>
              <span>{peekData.model}</span>
              <span className="tabular-nums">{Math.round(peekData.running_seconds)}s</span>
            </div>
            <div>{peekData.tool_count} tool{peekData.tool_count !== 1 ? 's' : ''} called{peekData.last_tool ? ` \u2014 last: ${peekData.last_tool}` : ''}</div>
            {peekData.recent_tools.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-0.5">
                {peekData.recent_tools.map((t, i) => (
                  <span key={i} className="px-1 py-0.5 rounded bg-background border border-border/40 text-[9px]">{t}</span>
                ))}
              </div>
            )}
          </div>
        )}
        {peekExpanded && !peekData && (
          <div className="mt-1.5 text-[10px] text-muted-foreground">Loading{'\u2026'}</div>
        )}

        {/* ── Result summary (terminal tasks) ──────────────────────────── */}
        {worker.resultSummary && TERMINAL_STATUSES.has(worker.status) && (
          <div
            className="mt-1 text-[10px] text-muted-foreground hover:text-foreground line-clamp-2"
            title={worker.resultSummary}
            onClick={(ev) => { ev.stopPropagation(); onSelect(worker); }}
          >
            {worker.resultSummary}
          </div>
        )}

        {/* ── Steer input ──────────────────────────────────────────────── */}
        {steerOpen && isActive && (
          <div
            className="flex items-center gap-1 mt-1 bg-card border border-border rounded px-2 py-1 focus-within:ring-2 focus-within:ring-accent/40"
            onClick={(ev) => ev.stopPropagation()}
          >
            <input
              ref={steerRef}
              type="text"
              value={steerInput}
              onChange={(ev) => setSteerInput(ev.target.value)}
              onKeyDown={onKey}
              placeholder={'Send steer message\u2026'}
              aria-label="Steering message"
              className="flex-1 text-[11px] bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
            />
            <button
              type="button"
              className="inline-flex items-center gap-1 text-[10px] text-accent hover:text-accent/80 disabled:opacity-40 px-1"
              disabled={!steerInput.trim()}
              aria-label="Send steer message"
              onClick={submit}
            >
              <Send size={12} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Session row (a CLI session with its child workers) ──────────────────────

function SessionRow({ session, projectId, onCancel, onSteer, onSelect, peekData, expandedPeek, onTogglePeek, cardTitles, cliByTask }: {
  session: SessionNode;
  projectId: string;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  peekData: Record<string, PeekResult | null>;
  expandedPeek: Set<string>;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
  cliByTask: Record<string, CliSessionInfo>;
}) {
  const hasChildren = session.workers.length > 0;
  const [open, setOpen] = useState(true);
  const selectCard = useProjectStore((s) => s.selectCard);
  const navigate = useNavigate();

  const isActive = !!session.cliSession || session.workers.some((w) => !TERMINAL_STATUSES.has(w.status));

  const isJobSession = session.chatId.startsWith('job:');

  // Detect dispatcher: CLI session of type "chat" or canonical chatId
  const isDispatcher = !isJobSession && !!(
    session.cliSession?.type === 'chat' ||
    session.chatId.startsWith('project:') ||
    session.chatId.startsWith('card:')
  );

  // Extract cardId from a canonical "card:<uuid>" chat_id (used to deep-link the card)
  const cardId = session.chatId.startsWith('card:')
    ? session.chatId.slice('card:'.length).split(':')[0]
    : undefined;

  const handleSessionClick = () => {
    if (!isJobSession) {
      if (cardId && projectId !== '_general') {
        navigate(projectId === SYSTEM_PROJECT_ID ? '/' : `/project/${projectId}`);
        selectCard(cardId);
      } else if (projectId !== '_general') {
        navigate(projectId === SYSTEM_PROJECT_ID ? '/' : `/project/${projectId}`);
      }
    }
    if (hasChildren) setOpen((o) => !o);
  };

  return (
    <div>
      <button
        className={cn(
          'flex items-center gap-1 w-full text-left py-0.5 text-[11px] transition-colors cursor-pointer rounded hover:bg-accent/10',
          isActive ? 'text-foreground' : 'text-muted-foreground',
        )}
        onClick={handleSessionClick}
      >
        {hasChildren ? (
          open ? <ChevronDown size={10} className="shrink-0" /> : <ChevronRight size={10} className="shrink-0" />
        ) : (
          <span className="w-[10px] shrink-0" />
        )}

        {isActive && (
          <div className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
        )}

        {isJobSession && (
          <Clock size={9} className="shrink-0 text-muted-foreground" />
        )}

        {isDispatcher && hasChildren && (
          <span className="text-[9px] font-semibold px-1 py-0.5 rounded bg-accent/15 text-accent shrink-0">
            Voxy
          </span>
        )}

        <span className="truncate font-medium">{session.label}</span>

        {session.cliSession && (
          <span className="text-[9px] text-muted-foreground shrink-0 ml-auto">
            pid:{session.cliSession.pid}
          </span>
        )}

        {cardId && (
          <button
            className="text-accent hover:text-accent/80 shrink-0 ml-1"
            title="Open card"
            onClick={(e) => { e.stopPropagation(); navigate(`/project/${projectId}`); selectCard(cardId); }}
          >
            <ExternalLink size={9} />
          </button>
        )}
      </button>

      {open && hasChildren && (
        <div className="flex flex-col">
          {session.workers.map((w, idx) => (
            <WorkerRow
              key={w.taskId}
              worker={w}
              onCancel={onCancel}
              onSteer={onSteer}
              onSelect={onSelect}
              isLast={idx === session.workers.length - 1}
              peekData={peekData[w.taskId] ?? null}
              peekExpanded={expandedPeek.has(w.taskId)}
              onTogglePeek={onTogglePeek}
              cardTitles={cardTitles}
              cliPid={cliByTask[w.taskId]?.pid}
              parentChatId={session.chatId}
              projectId={projectId}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export function WorkerPanel() {
  const [, setTick] = useState(0);
  const [peekData, setPeekData] = useState<Record<string, PeekResult | null>>({});
  const [expandedPeek, setExpandedPeek] = useState<Set<string>>(new Set());

  const { send } = useWS();
  const workers = useWorkerStore((s) => s.workers);
  const cliSessions = useWorkerStore((s) => s.cliSessions);
  const jobMeta = useWorkerStore((s) => s.jobMeta);
  const clearTerminal = useWorkerStore((s) => s.clearTerminal);
  const projects = useProjectStore((s) => s.projects);
  const cards = useCardStore((s) => s.cardsById);

  const projectNames = useMemo(() => {
    const m: Record<string, string> = {};
    for (const p of projects) m[p.id] = p.name || p.id.slice(0, 12);
    return m;
  }, [projects]);

  const cardTitles = useMemo(() => {
    const m: Record<string, string> = {};
    for (const [id, c] of Object.entries(cards)) m[id] = c.title;
    return m;
  }, [cards]);

  const cliByTask = useMemo(() => {
    const m: Record<string, CliSessionInfo> = {};
    for (const cs of Object.values(cliSessions)) if (cs.taskId) m[cs.taskId] = cs;
    return m;
  }, [cliSessions]);

  // Tick for elapsed time
  useEffect(() => {
    const t = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(t);
  }, []);

  // Actions
  const cancelTask = useCallback((taskId: string) => {
    const cs = cliByTask[taskId];
    send('task:cancel', { taskId, sessionId: cs?.id });
  }, [send, cliByTask]);

  const steerTask = useCallback((taskId: string, message: string) => {
    if (!message.trim()) return;
    const cs = cliByTask[taskId];
    send('task:steer', { taskId, sessionId: cs?.id, message: message.trim() });
  }, [send, cliByTask]);

  const togglePeek = useCallback((taskId: string) => {
    setExpandedPeek((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) {
        next.delete(taskId);
      } else {
        next.add(taskId);
        // Fetch peek data if not already loaded
        if (!peekData[taskId]) {
          setPeekData((pd) => ({ ...pd, [taskId]: null }));
          fetch(`/api/worker-tasks/${taskId}/peek`)
            .then((r) => r.ok ? r.json() : null)
            .then((data) => {
              if (data) setPeekData((pd) => ({ ...pd, [taskId]: data }));
            })
            .catch(() => {/* ignore */});
        }
      }
      return next;
    });
  }, [peekData]);

  // Build tree
  const allCli = useMemo(() => Object.values(cliSessions), [cliSessions]);
  const allWorkers = useMemo(() => Object.values(workers), [workers]);
  const tree = useMemo(() => buildTree(allCli, allWorkers, projectNames, cardTitles, jobMeta), [allCli, allWorkers, projectNames, cardTitles, jobMeta]);

  const activeCount = allCli.length + allWorkers.filter((w) => !TERMINAL_STATUSES.has(w.status)).length;
  const terminalCount = allWorkers.filter((w) => TERMINAL_STATUSES.has(w.status)).length;

  // Output modal state
  const [selectedWorker, setSelectedWorker] = useState<WorkerInfo | null>(null);

  const selectWorker = useCallback((w: WorkerInfo) => {
    // Get the latest version from store (status may have changed)
    setSelectedWorker(w);
  }, []);

  // Keep selected worker in sync with store updates
  const selectedLive = selectedWorker ? workers[selectedWorker.taskId] ?? selectedWorker : null;

  return (
    <div className="flex flex-col h-full" data-testid="session-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Sessions</span>
          {activeCount > 0 && (
            <span className="bg-primary text-primary-foreground text-xs font-bold px-1.5 rounded-full min-w-[18px] text-center">{activeCount}</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {terminalCount > 0 && (
            <button
              className="text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              title="Clear finished"
              onClick={clearTerminal}
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-1.5 flex flex-col gap-1">
        {tree.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-8">No active sessions</div>
        ) : (
          tree.map((proj) => (
            <ProjectGroup key={proj.projectId} project={proj} onCancel={cancelTask} onSteer={steerTask} onSelect={selectWorker} peekData={peekData} expandedPeek={expandedPeek} onTogglePeek={togglePeek} cardTitles={cardTitles} cliByTask={cliByTask} />
          ))
        )}
      </div>

      {/* Output modal */}
      {selectedLive && (
        <WorkerOutputModal worker={selectedLive} onClose={() => setSelectedWorker(null)} />
      )}
    </div>
  );
}

// ── Project group (collapsible) ─────────────────────────────────────────────

function ProjectGroup({ project, onCancel, onSteer, onSelect, peekData, expandedPeek, onTogglePeek, cardTitles, cliByTask }: {
  project: ProjectNode;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  peekData: Record<string, PeekResult | null>;
  expandedPeek: Set<string>;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
  cliByTask: Record<string, CliSessionInfo>;
}) {
  const [open, setOpen] = useState(true);
  const navigate = useNavigate();

  const isScheduler = project.projectId === SCHEDULER_GROUP_ID;

  const handleProjectClick = () => {
    // Navigate to project on click (but not for _general or _scheduler)
    if (project.projectId !== '_general' && !isScheduler) {
      navigate(project.projectId === SYSTEM_PROJECT_ID ? '/' : `/project/${project.projectId}`);
    }
    setOpen((o) => !o);
  };

  return (
    <div>
      <button
        className="flex items-center gap-1 w-full px-1 text-[11px] font-bold text-foreground hover:text-accent cursor-pointer rounded hover:bg-accent/10 transition-colors"
        onClick={handleProjectClick}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {isScheduler && <Clock size={10} className="shrink-0 text-muted-foreground" />}
        {project.projectName}
      </button>
      {open && (
        <div className="flex flex-col gap-0.5">
          {project.sessions.map((s) => (
            <SessionRow key={s.chatId} session={s} projectId={project.projectId} onCancel={onCancel} onSteer={onSteer} onSelect={onSelect} peekData={peekData} expandedPeek={expandedPeek} onTogglePeek={onTogglePeek} cardTitles={cardTitles} cliByTask={cliByTask} />
          ))}
        </div>
      )}
    </div>
  );
}
