/**
 * WorkerPanel — Hierarchical session/worker view.
 *
 * Structure:
 *   SESSIONS
 *   └── Project Name
 *       ├── Project Chat - 🔵 Fast Session
 *       │   ├── 🔵 sonnet — action — 45s… [steer][cancel]
 *       │   └── 🟡 Analyzer
 *       ├── Project Chat - 🟣 Deep Session
 *       │   └── 🟣 opus — action — 2m… [steer][cancel]
 *       └── Card: Title
 *           └── 🔵 sonnet — action — 1m… [steer][cancel]
 */

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import type { KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { MessageSquare, Send, ExternalLink, ChevronRight, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useWS } from '../../providers/WebSocketProvider';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore } from '../../stores/useCardStore';
import { useWorkerStore, type WorkerInfo, type CliSessionInfo } from '../../stores/useWorkerStore';

// ── Constants & Helpers ─────────────────────────────────────────────────────

const TERMINAL_STATUSES = new Set<WorkerInfo['status']>(['done', 'failed', 'cancelled']);

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

function modelLabel(model?: string): string {
  switch (model) {
    case 'haiku': return 'Fast';
    case 'opus': return 'Deep';
    default: return model ?? 'unknown';
  }
}

function formatAction(action: string): string {
  return action.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Parse a chatId like "project:uuid" or "project:card-uuid" into a session label. */
function parseSessionLabel(chatId: string | null, cardTitles: Record<string, string>): string {
  if (!chatId) return 'Direct';
  // Card session: "project:card-<uuid>"
  const cardMatch = chatId.match(/^project:card-(.+)$/);
  if (cardMatch) {
    const cardId = cardMatch[1];
    const title = cardTitles[cardId];
    return title ? `Card: ${title}` : `Card: ${cardId.slice(0, 8)}`;
  }
  // Project chat session: "project:<uuid>" or "general:system-main"
  if (chatId.startsWith('general:')) return 'General Chat';
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

function buildTree(
  allCli: CliSessionInfo[],
  allWorkers: WorkerInfo[],
  projectNames: Record<string, string>,
  cardTitles: Record<string, string>,
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

  // Group chatIds by project
  const chatIdsByProject: Record<string, Set<string>> = {};
  for (const chatId of allChatIds) {
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
      const label = parseSessionLabel(chatId, cardTitles);
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
      projectName: pid === '_general' ? 'General' : (projectNames[pid] || pid.slice(0, 12)),
      sessions,
    });
  }

  // Sort: projects with active sessions first
  projects.sort((a, b) => {
    const aActive = a.sessions.some((s) => s.cliSession || s.workers.some((w) => !TERMINAL_STATUSES.has(w.status))) ? 0 : 1;
    const bActive = b.sessions.some((s) => s.cliSession || s.workers.some((w) => !TERMINAL_STATUSES.has(w.status))) ? 0 : 1;
    return aActive - bActive;
  });

  return projects;
}

// ── Worker row ──────────────────────────────────────────────────────────────

function WorkerRow({ worker, onCancel, onSteer }: {
  worker: WorkerInfo;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
}) {
  const [steerOpen, setSteerOpen] = useState(false);
  const [steerInput, setSteerInput] = useState('');
  const [expanded, setExpanded] = useState(false);
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

  const handleRowClick = () => {
    if (isActive) {
      setSteerOpen((o) => !o);
    } else if (worker.resultSummary) {
      setExpanded((v) => !v);
    }
  };

  return (
    <div className="relative ml-4 pl-3 border-l border-border/50">
      <div
        className={cn(
          'flex items-center gap-1.5 py-1 text-[11px] cursor-pointer rounded hover:bg-accent/10 transition-colors',
          !isActive && 'opacity-50',
        )}
        onClick={handleRowClick}
      >
        {/* Spinner or status */}
        {isActive ? (
          <div className="w-3 h-3 border-2 border-accent border-t-transparent rounded-full animate-spin [animation-duration:0.6s] shrink-0" />
        ) : (
          <span className={cn(
            'w-3 h-3 flex items-center justify-center text-[9px] font-bold shrink-0',
            worker.status === 'done' ? 'text-green-500' : worker.status === 'failed' ? 'text-red-500' : 'text-muted-foreground',
          )}>
            {worker.status === 'done' ? '\u2713' : worker.status === 'failed' ? '\u2715' : '\u2298'}
          </span>
        )}

        <span className="shrink-0">{modelEmoji(worker.model)}</span>
        <span className="font-medium truncate">{worker.model}</span>
        <span className="text-muted-foreground truncate flex-1">{formatAction(worker.action)}</span>
        <span className="text-muted-foreground tabular-nums shrink-0">{isActive ? `${e}\u2026` : e}</span>

        {/* Steer + Cancel */}
        {isActive && (
          <div className="flex items-center gap-1 shrink-0">
            <button
              className="text-muted-foreground hover:text-accent transition-colors"
              title="Steer"
              onClick={() => setSteerOpen((o) => !o)}
            >
              <MessageSquare size={10} />
            </button>
            <button
              className="text-muted-foreground hover:text-red-400 transition-colors"
              title="Cancel"
              onClick={() => onCancel(worker.taskId)}
            >
              &times;
            </button>
          </div>
        )}
      </div>

      {/* Tool count */}
      {worker.toolCount > 0 && (
        <div className="text-[10px] text-muted-foreground ml-[18px]">
          {worker.toolCount} tool{worker.toolCount !== 1 ? 's' : ''}
          {worker.lastTool ? ` \u2014 ${worker.lastTool}` : ''}
        </div>
      )}

      {/* Result summary (click to expand) */}
      {worker.resultSummary && TERMINAL_STATUSES.has(worker.status) && (
        <div
          className={cn(
            'text-[10px] text-muted-foreground ml-[18px] mt-0.5',
            worker.resultSummary.length > 80 && 'cursor-pointer hover:text-foreground',
          )}
          onClick={worker.resultSummary.length > 80 ? () => setExpanded((v) => !v) : undefined}
        >
          {expanded ? worker.resultSummary.substring(0, 300) : worker.resultSummary.substring(0, 80) + (worker.resultSummary.length > 80 ? '\u2026' : '')}
        </div>
      )}

      {/* Steering mini-input */}
      {steerOpen && isActive && (
        <div className="flex items-center gap-1 ml-[18px] mt-1 bg-card border border-border rounded px-2 py-1">
          <input
            ref={steerRef}
            type="text"
            value={steerInput}
            onChange={(e) => setSteerInput(e.target.value)}
            onKeyDown={onKey}
            placeholder="Steer\u2026"
            className="flex-1 text-[11px] bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
          />
          <button className="text-accent hover:text-accent/80 disabled:opacity-40" disabled={!steerInput.trim()} onClick={submit}>
            <Send size={10} />
          </button>
        </div>
      )}
    </div>
  );
}

// ── Session row (a CLI session with its child workers) ──────────────────────

function SessionRow({ session, projectId, onCancel, onSteer }: {
  session: SessionNode;
  projectId: string;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
}) {
  const hasChildren = session.workers.length > 0;
  const [open, setOpen] = useState(true);
  const selectCard = useProjectStore((s) => s.selectCard);
  const navigate = useNavigate();

  const isActive = !!session.cliSession || session.workers.some((w) => !TERMINAL_STATUSES.has(w.status));

  // Extract cardId from chatId for link
  const cardMatch = session.chatId.match(/^project:card-(.+)$/);
  const cardId = cardMatch?.[1];

  const handleSessionClick = () => {
    if (cardId && projectId !== '_general') {
      // Card session: navigate to project and open card modal
      navigate(`/project/${projectId}`);
      selectCard(cardId);
    } else if (projectId !== '_general') {
      // Project Chat session: navigate to project
      navigate(`/project/${projectId}`);
    }
    // Toggle children open/closed regardless
    if (hasChildren) setOpen((o) => !o);
  };

  return (
    <div className="ml-3">
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
          {session.workers.map((w) => (
            <WorkerRow key={w.taskId} worker={w} onCancel={onCancel} onSteer={onSteer} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────

export function WorkerPanel() {
  const [collapsed, setCollapsed] = useState(false);
  const [, setTick] = useState(0);

  const { send } = useWS();
  const workers = useWorkerStore((s) => s.workers);
  const cliSessions = useWorkerStore((s) => s.cliSessions);
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

  // Build tree
  const allCli = useMemo(() => Object.values(cliSessions), [cliSessions]);
  const allWorkers = useMemo(() => Object.values(workers), [workers]);
  const tree = useMemo(() => buildTree(allCli, allWorkers, projectNames, cardTitles), [allCli, allWorkers, projectNames, cardTitles]);

  const activeCount = allCli.length + allWorkers.filter((w) => !TERMINAL_STATUSES.has(w.status)).length;
  const terminalCount = allWorkers.filter((w) => TERMINAL_STATUSES.has(w.status)).length;

  return (
    <div
      className={cn(
        'flex flex-col h-full bg-secondary border-l border-r border-border shrink-0 overflow-hidden transition-all duration-200',
        collapsed ? 'w-[42px]' : 'w-64',
      )}
      data-testid="session-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Sessions</span>
          {activeCount > 0 && (
            <span className="bg-primary text-primary-foreground text-xs font-bold px-1.5 rounded-full min-w-[18px] text-center">{activeCount}</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {terminalCount > 0 && !collapsed && (
            <button
              className="text-[10px] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              title="Clear finished"
              onClick={clearTerminal}
            >
              Clear
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
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="flex-1 overflow-y-auto p-1.5 flex flex-col gap-1">
          {tree.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-8">No active sessions</div>
          ) : (
            tree.map((proj) => (
              <ProjectGroup key={proj.projectId} project={proj} onCancel={cancelTask} onSteer={steerTask} />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Project group (collapsible) ─────────────────────────────────────────────

function ProjectGroup({ project, onCancel, onSteer }: {
  project: ProjectNode;
  onCancel: (id: string) => void;
  onSteer: (id: string, msg: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const navigate = useNavigate();

  const handleProjectClick = () => {
    // Navigate to project on click (but not for _general)
    if (project.projectId !== '_general') {
      navigate(`/project/${project.projectId}`);
    }
    setOpen((o) => !o);
  };

  return (
    <div>
      <button
        className="flex items-center gap-1 w-full px-1 py-0.5 text-[11px] font-bold text-foreground hover:text-accent cursor-pointer rounded hover:bg-accent/10 transition-colors"
        onClick={handleProjectClick}
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        {project.projectName}
      </button>
      {open && (
        <div className="flex flex-col gap-0.5">
          {project.sessions.map((s) => (
            <SessionRow key={s.chatId} session={s} projectId={project.projectId} onCancel={onCancel} onSteer={onSteer} />
          ))}
        </div>
      )}
    </div>
  );
}
