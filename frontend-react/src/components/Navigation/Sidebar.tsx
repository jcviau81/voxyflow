/**
 * Sidebar — React port of frontend/src/components/Navigation/Sidebar.ts
 *
 * Sections (top → bottom):
 *   1. Brand (🔥 Voxyflow)
 *   2. Main item (🏠 Main) — always at top
 *   3. Favorites section — starred projects with progress dots
 *   4. Active Sessions section — sessions across open tabs with close button
 *   5. All Projects link + New Project + Archived count
 *   6. Connection status
 *   7. Footer: notification bell, theme toggle, Settings, Docs, Help
 *
 * Props:
 *   isOpen  — controlled by AppShell (Ctrl+B shortcut handled here, emits onToggle)
 *   onToggle — called to flip the open/close state in the parent
 */

import { useEffect, useCallback, useMemo } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Home,
  Settings,
  BookOpen,
  HelpCircle,
  Bell,
  Moon,
  Sun,
  FolderPlus,
  ChevronRight,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { useProjectStore } from '../../stores/useProjectStore';
import { useSessionStore } from '../../stores/useSessionStore';
import { useTabStore } from '../../stores/useTabStore';
import { useCardStore, SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { useWS } from '../../providers/WebSocketProvider';
import { useToggleFavorite } from '../../hooks/api/useProjects';
import type { Project, SessionInfo } from '../../types';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}

interface SessionEntry {
  tabId: string;
  session: SessionInfo;
  label: string;
}

// ─── Progress dot helpers ─────────────────────────────────────────────────────

type DotColor = 'done' | 'halfway' | 'started' | 'empty';

const DOT_CLASS: Record<DotColor, string> = {
  done: 'bg-green-500',
  halfway: 'bg-yellow-400',
  started: 'bg-blue-400',
  empty: 'bg-muted-foreground/30',
};

// ─── Connection status dot ─────────────────────────────────────────────────────

const CONNECTION_DOT_CLASS = {
  connected: 'bg-green-500',
  connecting: 'bg-yellow-400',
  reconnecting: 'bg-yellow-500',
  disconnected: 'bg-red-500',
} as const;

// ─── Sub-components ───────────────────────────────────────────────────────────

function ProjectItem({
  project,
  isActive,
  onToggleFavorite,
}: {
  project: Project;
  isActive: boolean;
  onToggleFavorite: (id: string) => void;
}) {
  const navigate = useNavigate();
  const cardsById = useCardStore((s) => s.cardsById);
  const cards = useMemo(
    () => Object.values(cardsById).filter((c) => c.projectId === project.id),
    [cardsById, project.id],
  );
  const openTabs = useTabStore((s) => s.openTabs);
  const openProjectTab = useTabStore((s) => s.openProjectTab);

  const isTabOpen = openTabs.some((t) => t.id === project.id);

  const total = cards.length;
  const done = cards.filter((c) => c.status === 'done').length;
  const inProgress = cards.filter((c) => c.status === 'in-progress').length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const dotColor: DotColor =
    pct === 100 ? 'done' : pct >= 50 ? 'halfway' : pct > 0 ? 'started' : 'empty';

  const tooltip =
    total > 0
      ? `${total} cards · ${done} done · ${inProgress} in progress · ${pct}%`
      : 'No cards yet';

  const handleClick = () => {
    openProjectTab(project.id, project.name, project.emoji);
    navigate(`/project/${project.id}`);
  };

  return (
    <div
      className={cn(
        'sidebar-project-item flex items-center gap-1.5 px-3 py-1.5 mx-2 rounded-md text-sm cursor-pointer',
        'hover:bg-accent hover:text-accent-foreground transition-colors',
        isActive && 'bg-accent text-accent-foreground font-medium',
        isTabOpen && !isActive && 'text-foreground',
      )}
      title={tooltip}
      data-testid={`sidebar-project-${project.id}`}
      onClick={handleClick}
    >
      {/* Favorite star */}
      <button
        className="shrink-0 text-xs leading-none hover:scale-110 transition-transform"
        title={project.isFavorite ? 'Remove from favorites' : 'Add to favorites'}
        onClick={(e) => {
          e.stopPropagation();
          onToggleFavorite(project.id);
        }}
      >
        {project.isFavorite ? '⭐' : '☆'}
      </button>

      {/* Project name */}
      <span className="flex-1 truncate">{project.name}</span>

      {/* Progress dot */}
      <span
        className={cn('shrink-0 w-2 h-2 rounded-full', DOT_CLASS[dotColor])}
        title={tooltip}
      />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  const navigate = useNavigate();

  // Stores
  const projects = useProjectStore((s) => s.projects);
  const activeTab = useTabStore((s) => s.activeTab);
  const openTabs = useTabStore((s) => s.openTabs);
  const sessions = useSessionStore((s) => s.sessions);
  const activeSession = useSessionStore((s) => s.activeSession);
  const closeSessionInStore = useSessionStore((s) => s.closeSession);
  const createSession = useSessionStore((s) => s.createSession);
  const setActiveSession = useSessionStore((s) => s.setActiveSession);
  const switchTab = useTabStore((s) => s.switchTab);
  const notificationUnreadCount = useNotificationStore((s) => s.notificationUnreadCount);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const { connectionState, send } = useWS();
  const toggleFavoriteMutation = useToggleFavorite();

  // Derived data
  const activeProjects = projects.filter((p) => !p.archived && p.id !== SYSTEM_PROJECT_ID);
  const favoriteProjects = activeProjects.filter((p) => p.isFavorite);
  const archivedProjects = projects.filter((p) => p.archived && p.id !== SYSTEM_PROJECT_ID);

  // ── Active session entries ─────────────────────────────────────────────────

  const sessionEntries: SessionEntry[] = [];
  for (const tab of openTabs) {
    const sessionKey = tab.id === 'main' ? 'system-main' : tab.id;
    const tabSessions = sessions[sessionKey] || [];
    if (tabSessions.length === 0) continue;

    for (const session of tabSessions) {
      let label: string;
      if (tab.id === 'main') {
        label = `Main › ${session.title || 'Chat'}`;
      } else {
        const project = projects.find((p) => p.id === tab.id);
        const projectName = project?.name || tab.label || 'Project';
        label = `${projectName} › ${session.title || 'Session'}`;
      }
      sessionEntries.push({ tabId: tab.id, session, label });
    }
  }

  // ── Close session handler ──────────────────────────────────────────────────

  const handleCloseSession = useCallback(
    (tabId: string, session: SessionInfo) => {
      const sessionTabId = tabId === 'main' ? 'system-main' : tabId;
      send('session:reset', { sessionId: session.chatId, tabId: sessionTabId });

      const tabSessions = sessions[sessionTabId] || [];
      if (tabSessions.length <= 1) {
        // Store refuses to close last session, but vanilla would create a fresh one
        createSession(sessionTabId);
      } else {
        closeSessionInStore(sessionTabId, session.id);
      }
    },
    [send, sessions, closeSessionInStore, createSession],
  );

  // ── Switch to session handler ──────────────────────────────────────────────

  const handleSwitchSession = useCallback(
    (tabId: string, session: SessionInfo) => {
      const sessionTabId = tabId === 'main' ? 'system-main' : tabId;
      switchTab(tabId);
      setActiveSession(sessionTabId, session.id);
      if (tabId === 'main') {
        navigate('/');
      } else {
        navigate(`/project/${tabId}`);
      }
    },
    [switchTab, setActiveSession, navigate],
  );

  // ── Keyboard shortcut Ctrl+B ───────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === 'b') {
        e.preventDefault();
        onToggle();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onToggle]);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <aside
      className={cn(
        'sidebar flex flex-col bg-sidebar border-r border-border transition-all duration-200 shrink-0',
        isOpen ? 'w-56' : 'w-0 overflow-hidden',
      )}
      data-testid="sidebar"
    >
      {/* ── Brand ── */}
      <div className="sidebar-brand flex items-center gap-2 px-4 py-3 border-b border-border shrink-0">
        <span className="text-xl leading-none">🔥</span>
        <span className="font-semibold text-sm text-foreground whitespace-nowrap">Voxyflow</span>
      </div>

      {/* ── Scrollable content ── */}
      <nav className="sidebar-content flex-1 overflow-y-auto py-2 min-w-0">

        {/* Main / General */}
        <div className="sidebar-nav px-2">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              cn(
                'sidebar-item flex items-center gap-2 px-3 py-2 rounded-md text-sm cursor-pointer whitespace-nowrap',
                'hover:bg-accent hover:text-accent-foreground transition-colors',
                (isActive || activeTab === 'main') && 'bg-accent text-accent-foreground font-medium',
              )
            }
            data-testid="sidebar-general"
            data-tab="main"
          >
            <Home size={15} className="shrink-0" />
            <span>Main</span>
          </NavLink>
        </div>

        {/* ── Favorites ── */}
        {favoriteProjects.length > 0 && (
          <div className="sidebar-favorites mt-3">
            <p className="sidebar-section-header px-5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
              ⭐ Favorites
            </p>
            {favoriteProjects.map((proj) => (
              <ProjectItem
                key={proj.id}
                project={proj}
                isActive={activeTab === proj.id}
                onToggleFavorite={(id) => toggleFavoriteMutation.mutate(id)}
              />
            ))}
          </div>
        )}

        {/* ── Active Sessions ── */}
        {sessionEntries.length > 0 && (
          <div className="sidebar-sessions mt-3">
            <p className="sidebar-section-header px-5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
              💬 Active Sessions
            </p>
            {sessionEntries.map(({ tabId, session, label }) => {
              const sessionTabId = tabId === 'main' ? 'system-main' : tabId;
              const isCurrent =
                tabId === activeTab &&
                activeSession[sessionTabId] === session.id;

              return (
                <div
                  key={`${tabId}-${session.id}`}
                  className={cn(
                    'sidebar-session-item flex items-center gap-1.5 px-3 py-1.5 mx-2 rounded-md text-sm cursor-pointer group',
                    'hover:bg-accent hover:text-accent-foreground transition-colors',
                    isCurrent && 'bg-accent text-accent-foreground font-medium',
                  )}
                  title={label}
                  onClick={() => handleSwitchSession(tabId, session)}
                >
                  {/* Status dot */}
                  <span className="shrink-0 text-xs leading-none">
                    {isCurrent ? '🟢' : '⚫'}
                  </span>

                  {/* Breadcrumb label */}
                  <span className="sidebar-session-label flex-1 truncate text-xs">{label}</span>

                  {/* Close button — visible on hover */}
                  <button
                    className="sidebar-session-close shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground leading-none px-0.5"
                    title="Close session"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleCloseSession(tabId, session);
                    }}
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {/* ── All Projects ── */}
        <div className="sidebar-projects mt-3">
          {/* Header with "All Projects" link */}
          <button
            className="sidebar-section-header w-full flex items-center justify-between px-5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap"
            title="All projects"
            onClick={() => navigate('/projects')}
          >
            <span>📁 All Projects</span>
            <ChevronRight size={12} />
          </button>

          {/* New project */}
          <button
            className="sidebar-new-project flex items-center gap-2 w-full px-3 py-1.5 mx-2 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors whitespace-nowrap"
            style={{ width: 'calc(100% - 1rem)' }}
            data-testid="sidebar-new-project"
            onClick={() => navigate('/projects?new=1')}
          >
            <FolderPlus size={14} className="shrink-0" />
            <span>New Project</span>
          </button>

          {/* Archived link */}
          {archivedProjects.length > 0 && (
            <button
              className="sidebar-archived-link flex items-center gap-2 w-full px-3 py-1.5 mx-2 rounded-md text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors whitespace-nowrap"
              style={{ width: 'calc(100% - 1rem)' }}
              data-testid="sidebar-archived"
              title={`${archivedProjects.length} archived project${archivedProjects.length > 1 ? 's' : ''}`}
              onClick={() => navigate('/projects?filter=archived')}
            >
              <span className="shrink-0">📦</span>
              <span className="truncate">
                Archived ({archivedProjects.length})
              </span>
            </button>
          )}
        </div>

        {/* ── Connection status ── */}
        <div className="sidebar-status flex items-center gap-2 px-5 py-2 mt-2">
          <span
            className={cn(
              'status-dot shrink-0 w-2 h-2 rounded-full',
              CONNECTION_DOT_CLASS[connectionState],
            )}
          />
          <span className="status-text text-xs text-muted-foreground capitalize whitespace-nowrap">
            {connectionState}
          </span>
        </div>
      </nav>

      {/* ── Footer ── */}
      <div
        className="sidebar-footer flex items-center gap-1 px-2 py-2 border-t border-border shrink-0"
        data-testid="sidebar-footer"
      >
        {/* Notification bell */}
        <div className="notification-bell-wrapper relative">
          <button
            className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
            data-action="notifications"
            title="Notifications"
          >
            <Bell size={16} />
          </button>
          {notificationUnreadCount > 0 && (
            <span className="notification-badge absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-4 px-0.5 rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold leading-none">
              {notificationUnreadCount > 99 ? '99+' : notificationUnreadCount}
            </span>
          )}
        </div>

        {/* Theme toggle */}
        <button
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          data-action="theme-toggle"
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          onClick={toggleTheme}
        >
          {theme === 'dark' ? <Moon size={16} /> : <Sun size={16} />}
        </button>

        {/* Settings */}
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            cn(
              'sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground',
              'hover:bg-accent hover:text-accent-foreground transition-colors',
              isActive && 'text-foreground bg-accent',
            )
          }
          title="Settings"
          data-action="settings"
        >
          <Settings size={16} />
        </NavLink>

        {/* Docs */}
        <button
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          data-action="docs"
          title="Documentation"
        >
          <BookOpen size={16} />
        </button>

        {/* Help */}
        <button
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
          data-action="help"
          title="Help"
        >
          <HelpCircle size={16} />
        </button>
      </div>
    </aside>
  );
}
