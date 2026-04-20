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

// ── Constants & Helpers ────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set<WorkerInfo['status']>(['done', 'failed', 'cancelled']);

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
    case 'haiku': return 'Haiku';
    case 'sonnet': return 'Sonnet';
    case 'opus': return 'Opus';
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

// ── Session tree types ─────────────────────────────────────────────────────

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

// ── Build hierarchy ────────────────────────────────────────────────────────

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

// ── Worker card ────────────────────────────────────────────────────────────

function WorkerRow({ worker, onCancel, onSteer, onSelect, isLast, peekData, peekExpanded, onTogglePeek, cardTitles, parentChatId, projectId }: {
  worker: WorkerInfo;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  isLast?: boolean;
  peekData: PeekResult | null;
  peekExpanded: boolean;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
  parentChatId: string;
  projectId: string;
}) {
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerInput, setSteerInput] = useState('');
  const [detailsOpen, setDetailsOpen] = useState(false);
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

  // Auto-open details panel when peek is activated
  useEffect(() => {
    if (peekExpanded) setDetailsOpen(true);
  }, [peekExpanded]);

  const isActive = !TERMINAL_STATUSES.has(worker.status);
  const e = elapsed(worker.startedAt, worker.completedAt);

  const parentIsCardSession =
    worker.cardId != null && parentChatId === `card:${worker.cardId}`;
  const showCardPill = !!worker.cardId && !parentIsCardSession;
  const cardLabel = worker.cardId
    ? cardTitles[worker.cardId] || worker.cardId.slice(0, 8)
    : '';

  const selectCard = useProjectStore((s) => s.selectCard);
  const navigate = useNavigate();

  const handleRowClick = () => { onSelect(worker); };

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
    worker.status === 'failed'    ? 'failed'    : 'cancelled';

  const hasDetails =
    worker.toolCount > 0 ||
    !!worker.resultSummary ||
    peekExpanded;

  const progressPct = Math.min(((worker.toolCount ?? 0) / 15) * 100 + 8, 90);

  return (
    <div className="relative group/worker worker-item-appear">
      {/* Tree connector lines */}
      <div className={cn(
        'absolute left-0 top-0 w-px bg-border/40',
        isLast ? 'h-[32px]' : 'h-full',
      )} />
      <div className="absolute left-0 top-[32px] w-3 h-px bg-border/40" />

      {/* ── Card shell ──────────────────────────────────────── */}
      <div
        className={cn(
          'ml-3 rounded-xl border transition-all duration-200',
          isActive
            ? 'bg-card border-accent/20 shadow-sm shadow-black/15'
            : 'bg-card/50 border-border/30 opacity-60',
        )}
      >
        {/* ── Primary row — always visible ──────────────────── */}
        <div
          className="flex items-center gap-2.5 px-4 pt-3.5 pb-3 cursor-pointer select-none"
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
          {/* Status indicator */}
          {isActive ? (
            <div
              className="w-3.5 h-3.5 border-[2px] border-accent border-t-transparent rounded-full animate-spin [animation-duration:0.7s] shrink-0"
              aria-label="running"
            />
          ) : (
            <span
              className={cn(
                'w-3.5 h-3.5 flex items-center justify-center text-[11px] font-bold shrink-0',
                worker.status === 'done'      && 'text-green-500',
                worker.status === 'failed'    && 'text-red-400',
                worker.status === 'cancelled' && 'text-muted-foreground',
              )}
              aria-label={statusLabel}
            >
              {worker.status === 'done' ? '✓' : worker.status === 'failed' ? '✗' : '⊘'}
            </span>
          )}

          {/* Model + class badge */}
          <span
            className={cn(
              'inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-md shrink-0 leading-none',
              modelTier(worker.model) === 'haiku'  && 'bg-blue-500/15 text-blue-400',
              modelTier(worker.model) === 'sonnet' && 'bg-violet-500/15 text-violet-400',
              modelTier(worker.model) === 'opus'   && 'bg-purple-500/15 text-purple-400',
              !modelTier(worker.model)             && 'bg-muted text-muted-foreground',
            )}
            aria-hidden="true"
          >
            <span className="text-[10px] leading-none">{modelEmoji(worker.model)}</span>
            <span>{worker.workerClass || modelLabel(worker.model)}</span>
          </span>

          {/* Action text — grows to fill */}
          <span className="text-[13px] font-medium text-foreground truncate flex-1 min-w-0">
            {formatAction(worker.action)}
          </span>

          {/* Card pill (inline, compact) */}
          {showCardPill && (
            <button
              className="text-[10px] font-medium px-1.5 py-0.5 rounded-md bg-amber-500/12 text-amber-500 hover:bg-amber-500/22 focus-visible:ring-2 focus-visible:ring-amber-500/40 focus:outline-none transition-colors shrink-0 max-w-[80px] truncate"
              title={`Open card: ${cardLabel}`}
              aria-label={`Open card ${cardLabel}`}
              onClick={handleCardPillClick}
            >
              {cardLabel}
            </button>
          )}

          {/* Elapsed time */}
          <span className="text-[12px] tabular-nums text-muted-foreground shrink-0 font-medium">
            {isActive ? `${e}\u2026` : e}
          </span>

          {/* Expand / collapse toggle */}
          {hasDetails && (
            <button
              type="button"
              className="ml-0.5 p-0.5 text-muted-foreground/40 hover:text-muted-foreground rounded transition-colors shrink-0"
              aria-label={detailsOpen ? 'Collapse details' : 'Expand details'}
              aria-expanded={detailsOpen}
              onClick={(ev) => { ev.stopPropagation(); setDetailsOpen((o) => !o); }}
            >
              {detailsOpen
                ? <ChevronDown size={13} aria-hidden="true" />
                : <ChevronRight size={13} aria-hidden="true" />}
            </button>
          )}
        </div>

        {/* Progress bar — active workers only */}
        {isActive && (
          <div className="mx-4 mb-2.5 h-[3px] bg-border/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-accent/65 rounded-full transition-[width] duration-700 ease-out"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        )}

        {/* ── Expanded details ────────────────────────────────── */}
        {detailsOpen && (
          <div className="border-t border-border/25 mx-3 pt-2.5 pb-2.5 space-y-2">
            {/* Tool count + last tool */}
            {worker.toolCount > 0 && (
              <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground px-1">
                <span>{worker.toolCount} tool call{worker.toolCount !== 1 ? 's' : ''}</span>
                {peekData?.last_tool && (
                  <>
                    <span className="text-muted-foreground/40">&mdash;</span>
                    <span className="font-medium text-foreground/70">last: {peekData.last_tool}</span>
                  </>
                )}
              </div>
            )}

            {/* Recent tools (from peek) */}
            {peekExpanded && peekData && peekData.recent_tools.length > 0 && (
              <div className="flex flex-wrap gap-1 px-1">
                {peekData.recent_tools.map((t, i) => (
                  <span
                    key={i}
                    className="px-1.5 py-0.5 rounded-md bg-background border border-border/50 text-[10px] text-muted-foreground"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            {/* Peek loading state */}
            {peekExpanded && !peekData && (
              <p className="text-[11px] text-muted-foreground px-1 animate-pulse">
                Fetching live data\u2026
              </p>
            )}

            {/* Result summary (terminal workers) */}
            {worker.resultSummary && TERMINAL_STATUSES.has(worker.status) && (
              <p
                className="text-[12px] text-muted-foreground/80 hover:text-foreground line-clamp-3 cursor-pointer transition-colors px-1"
                title={worker.resultSummary}
                onClick={(ev) => { ev.stopPropagation(); onSelect(worker); }}
              >
                {worker.resultSummary}
              </p>
            )}
          </div>
        )}

        {/* ── Action bar — hover / focus-within reveal ─────────── */}
        {isActive && (
          <div
            className={cn(
              'flex items-center gap-1 px-3 pb-3 transition-opacity duration-150',
              'opacity-0 group-hover/worker:opacity-100 group-focus-within/worker:opacity-100',
              (steerOpen || peekExpanded) && 'opacity-100',
            )}
            onClick={(ev) => ev.stopPropagation()}
          >
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-accent hover:bg-accent/10 focus-visible:ring-2 focus-visible:ring-accent/40 focus:outline-none transition-colors"
              aria-label="Peek at tool calls"
              aria-expanded={peekExpanded}
              onClick={() => onTogglePeek(worker.taskId)}
            >
              <Eye size={12} aria-hidden="true" />
              <span>Peek</span>
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-accent hover:bg-accent/10 focus-visible:ring-2 focus-visible:ring-accent/40 focus:outline-none transition-colors"
              aria-label="Steer worker"
              aria-expanded={steerOpen}
              onClick={() => setSteerOpen((o) => !o)}
            >
              <MessageSquare size={12} aria-hidden="true" />
              <span>Steer</span>
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-muted-foreground hover:text-red-400 hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-red-400/40 focus:outline-none transition-colors ml-auto"
              aria-label="Cancel worker"
              onClick={() => onCancel(worker.taskId)}
            >
              <XIcon size={12} aria-hidden="true" />
              <span>Cancel</span>
            </button>
          </div>
        )}

        {/* ── Steer input ─────────────────────────────────────── */}
        {steerOpen && isActive && (
          <div
            className="flex items-center gap-2 mx-3 mb-3 bg-background border border-border/60 rounded-xl px-3 py-2 focus-within:ring-2 focus-within:ring-accent/40 transition-shadow"
            onClick={(ev) => ev.stopPropagation()}
          >
            <input
              ref={steerRef}
              type="text"
              value={steerInput}
              onChange={(ev) => setSteerInput(ev.target.value)}
              onKeyDown={onKey}
              placeholder="Send steering message\u2026"
              aria-label="Steering message"
              className="flex-1 text-[12px] bg-transparent outline-none text-foreground placeholder:text-muted-foreground/60"
            />
            <button
              type="button"
              className="text-accent hover:text-accent/70 disabled:opacity-40 transition-colors p-0.5"
              disabled={!steerInput.trim()}
              aria-label="Send steer message"
              onClick={submit}
            >
              <Send size={13} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Session row (a CLI session + its child workers) ────────────────────────

function SessionRow({ session, projectId, onCancel, onSteer, onSelect, peekData, expandedPeek, onTogglePeek, cardTitles }: {
  session: SessionNode;
  projectId: string;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  peekData: Record<string, PeekResult | null>;
  expandedPeek: Set<string>;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
}) {
  const hasChildren = session.workers.length > 0;
  const [open, setOpen] = useState(true);
  const selectCard = useProjectStore((s) => s.selectCard);
  const navigate = useNavigate();

  const isActive = !!session.cliSession || session.workers.some((w) => !TERMINAL_STATUSES.has(w.status));
  const isJobSession = session.chatId.startsWith('job:');

  const isDispatcher = !isJobSession && !!(
    session.cliSession?.type === 'chat' ||
    session.chatId.startsWith('project:') ||
    session.chatId.startsWith('card:')
  );

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
          'flex items-center gap-1.5 w-full px-2 py-1.5 text-[12px] transition-colors cursor-pointer rounded-lg hover:bg-accent/8',
          isActive ? 'text-foreground' : 'text-muted-foreground',
        )}
        onClick={handleSessionClick}
      >
        {hasChildren ? (
          open
            ? <ChevronDown size={10} className="shrink-0 text-muted-foreground/60" />
            : <ChevronRight size={10} className="shrink-0 text-muted-foreground/60" />
        ) : (
          <span className="w-[10px] shrink-0" />
        )}

        {isActive && (
          <span className="relative flex h-1.5 w-1.5 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
          </span>
        )}

        {isJobSession && (
          <Clock size={9} className="shrink-0 text-muted-foreground" />
        )}

        {isDispatcher && hasChildren && (
          <span className="text-[9px] font-semibold px-1 py-0.5 rounded-md bg-accent/15 text-accent shrink-0">
            Voxy
          </span>
        )}

        <span className="truncate font-medium">{session.label}</span>

        {session.cliSession && (
          <span className="text-[9px] text-muted-foreground/50 shrink-0 ml-auto">
            pid:{session.cliSession.pid}
          </span>
        )}

        {cardId && (
          <button
            className="text-accent/60 hover:text-accent shrink-0 ml-1 transition-colors"
            title="Open card"
            onClick={(e) => {
              e.stopPropagation();
              navigate(`/project/${projectId}`);
              selectCard(cardId);
            }}
          >
            <ExternalLink size={9} />
          </button>
        )}
      </button>

      {open && hasChildren && (
        <div className="flex flex-col gap-2 mt-1">
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
              parentChatId={session.chatId}
              projectId={projectId}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

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
  const tree = useMemo(
    () => buildTree(allCli, allWorkers, projectNames, cardTitles, jobMeta),
    [allCli, allWorkers, projectNames, cardTitles, jobMeta],
  );

  const activeCount = allCli.length + allWorkers.filter((w) => !TERMINAL_STATUSES.has(w.status)).length;
  const terminalCount = allWorkers.filter((w) => TERMINAL_STATUSES.has(w.status)).length;

  // Output modal state
  const [selectedWorker, setSelectedWorker] = useState<WorkerInfo | null>(null);

  const selectWorker = useCallback((w: WorkerInfo) => {
    setSelectedWorker(w);
  }, []);

  const selectedLive = selectedWorker ? workers[selectedWorker.taskId] ?? selectedWorker : null;

  return (
    <div className="flex flex-col h-full" data-testid="session-panel">
      {/* ── Header ──────────────────────────────────────────── */}
      <div className="flex items-center justify-between px-3 py-2.5 border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Sessions
          </span>
          {activeCount > 0 && (
            <span className="bg-primary text-primary-foreground text-xs font-bold px-1.5 rounded-full min-w-[18px] text-center">
              {activeCount}
            </span>
          )}
        </div>

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

      {/* ── Body ────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {tree.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-8">No active sessions</div>
        ) : (
          tree.map((proj) => (
            <ProjectGroup
              key={proj.projectId}
              project={proj}
              onCancel={cancelTask}
              onSteer={steerTask}
              onSelect={selectWorker}
              peekData={peekData}
              expandedPeek={expandedPeek}
              onTogglePeek={togglePeek}
              cardTitles={cardTitles}
            />
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

// ── Project group (collapsible) ────────────────────────────────────────────

function ProjectGroup({ project, onCancel, onSteer, onSelect, peekData, expandedPeek, onTogglePeek, cardTitles }: {
  project: ProjectNode;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
  onSelect: (worker: WorkerInfo) => void;
  peekData: Record<string, PeekResult | null>;
  expandedPeek: Set<string>;
  onTogglePeek: (taskId: string) => void;
  cardTitles: Record<string, string>;
}) {
  const [open, setOpen] = useState(true);
  const navigate = useNavigate();

  const isScheduler = project.projectId === SCHEDULER_GROUP_ID;

  const hasActiveWorkers = project.sessions.some(
    (s) => s.cliSession || s.workers.some((w) => !TERMINAL_STATUSES.has(w.status)),
  );

  const handleProjectClick = () => {
    if (project.projectId !== '_general' && !isScheduler) {
      navigate(project.projectId === SYSTEM_PROJECT_ID ? '/' : `/project/${project.projectId}`);
    }
    setOpen((o) => !o);
  };

  return (
    <div className={cn(
      'rounded-xl border overflow-hidden transition-colors',
      hasActiveWorkers
        ? 'border-border/40 bg-muted/15'
        : 'border-border/25 bg-muted/8',
    )}>
      {/* Project header */}
      <button
        className={cn(
          'flex items-center gap-1.5 w-full px-3 py-2.5 text-[12px] font-semibold cursor-pointer transition-colors hover:bg-accent/8',
          hasActiveWorkers ? 'text-foreground' : 'text-muted-foreground',
        )}
        onClick={handleProjectClick}
      >
        {open
          ? <ChevronDown size={11} className="shrink-0 text-muted-foreground/60" />
          : <ChevronRight size={11} className="shrink-0 text-muted-foreground/60" />}
        {isScheduler && <Clock size={10} className="shrink-0 text-muted-foreground" />}
        <span>{project.projectName}</span>
      </button>

      {/* Sessions */}
      {open && (
        <div className="px-2 pb-2.5 flex flex-col gap-1.5">
          {project.sessions.map((s) => (
            <SessionRow
              key={s.chatId}
              session={s}
              projectId={project.projectId}
              onCancel={onCancel}
              onSteer={onSteer}
              onSelect={onSelect}
              peekData={peekData}
              expandedPeek={expandedPeek}
              onTogglePeek={onTogglePeek}
              cardTitles={cardTitles}
            />
          ))}
        </div>
      )}
    </div>
  );
}
