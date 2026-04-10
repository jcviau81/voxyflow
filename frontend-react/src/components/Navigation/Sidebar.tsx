/**
 * Sidebar
 *
 * Sections (top → bottom):
 *   1. Brand (Voxyflow)
 *   2. Main / Jobs / Projects nav links
 *   3. Favorites — starred projects with progress dots
 *   4. New Project button
 *   5. Sessions — WorkerPanel (CLI sessions + workers)
 *   6. Connection status
 *   7. Footer: notification bell, theme toggle, Settings, Docs, Help
 *
 * Props:
 *   isOpen   — controlled by AppShell (Ctrl+B shortcut handled here, emits onToggle)
 *   onToggle — called to flip the open/close state in the parent
 */

import { useEffect, useMemo } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  Home,
  Settings,
  BookOpen,
  HelpCircle,
  Bell,
  Moon,
  Sun,
  Folder,
  Clock,
  Star,
} from 'lucide-react';
import { cn } from '../../lib/utils';
import { WorkerPanel } from './WorkerPanel';
import { useProjectStore } from '../../stores/useProjectStore';
import { useTabStore } from '../../stores/useTabStore';
import { useCardStore, SYSTEM_PROJECT_ID } from '../../stores/useCardStore';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useThemeStore } from '../../stores/useThemeStore';
import { useWS } from '../../providers/WebSocketProvider';
import type { Project } from '../../types';

// ─── Types ────────────────────────────────────────────────────────────────────

interface SidebarProps {
  isOpen: boolean;
  onToggle: () => void;
}



// ─── Shared nav item class ────────────────────────────────────────────────────

const NAV_ITEM =
  'sidebar-item flex items-center gap-2 px-3 py-2 rounded-md text-sm cursor-pointer whitespace-nowrap w-full hover:bg-accent hover:text-accent-foreground transition-colors';

// ─── Progress dot helpers ─────────────────────────────────────────────────────

type DotColor = 'done' | 'halfway' | 'started' | 'empty';

const DOT_CLASS: Record<DotColor, string> = {
  done:    'bg-green-500',
  halfway: 'bg-yellow-400',
  started: 'bg-blue-400',
  empty:   'bg-muted-foreground/30',
};

// ─── Connection status dot ─────────────────────────────────────────────────────

const CONNECTION_DOT_CLASS = {
  connected:    'bg-green-500',
  connecting:   'bg-yellow-400',
  reconnecting: 'bg-yellow-500',
  disconnected: 'bg-red-500',
} as const;

// ─── Sub-components ───────────────────────────────────────────────────────────

function ProjectItem({
  project,
  isActive,
}: {
  project: Project;
  isActive: boolean;
}) {
  const navigate = useNavigate();
  const cardsById = useCardStore((s) => s.cardsById);
  const cards = useMemo(
    () => Object.values(cardsById).filter((c) => c.projectId === project.id),
    [cardsById, project.id],
  );
  const openTabs = useTabStore((s) => s.openTabs);

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
    // Navigate only — AppShell syncs tab + project stores from URL
    navigate(`/project/${project.id}`);
  };

  return (
    <button
      className={cn(
        NAV_ITEM,
        isActive && 'bg-accent text-accent-foreground font-medium',
        isTabOpen && !isActive && 'text-foreground',
      )}
      
      title={tooltip}
      data-testid={`sidebar-project-${project.id}`}
      onClick={handleClick}
    >
      
      <span>
        {project.emoji || <Star size={14} className="shrink-0" /> }
      </span>
      
      {/* Project name */}
      <span>{project.name}</span>

      {/* Progress dot */}
      <span
        className={cn('shrink-0 w-2 h-2 rounded-full', DOT_CLASS[dotColor])}
        title={tooltip}
      />

    </button>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function Sidebar({ isOpen, onToggle }: SidebarProps) {
  // Stores
  const projects = useProjectStore((s) => s.projects);
  const activeTab = useTabStore((s) => s.activeTab);
  const notificationUnreadCount = useNotificationStore((s) => s.notificationUnreadCount);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const { connectionState } = useWS();

  // Derived data
  const activeProjects = projects.filter((p) => !p.archived && p.id !== SYSTEM_PROJECT_ID);
  const favoriteProjects = activeProjects.filter((p) => p.isFavorite);

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
        // Mobile: fixed overlay; Desktop: inline flex
        'fixed inset-y-0 left-0 z-30 md:relative md:z-auto',
        isOpen ? 'w-56' : 'w-0 overflow-hidden',
      )}
      data-testid="sidebar"
    >
      {/* ── Brand ── */}
      <div className="sidebar-brand flex items-center gap-2 px-4 py-3 border-b border-border shrink-0">
        <img src="/favicon.svg" alt="Voxyflow" width={28} height={28} className="shrink-0" />
        <span className="sidebar-logo-text text-sm text-foreground whitespace-nowrap">Voxyflow</span>
      </div>

      {/* ── Scrollable content ── */}
      <nav
        className="sidebar-content flex-1 overflow-y-auto py-2 min-w-0"
        onClick={(e) => {
          // Auto-close sidebar on mobile when clicking a nav link
          if (window.innerWidth < 768 && (e.target as HTMLElement).closest('a, [data-tab]')) {
            onToggle();
          }
        }}
      >

        {/* Main / General */}
        <div className="sidebar-nav flex-row px-2 gap-y-1 space-y-1">
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              cn(NAV_ITEM, (isActive || activeTab === 'main') && 'bg-accent text-accent-foreground font-medium')
            }
            data-testid="sidebar-general"
            data-tab="main"
          >
            <Home size={14} className="shrink-0" />
            <span>Home</span>
          </NavLink>

          {/* ── Favorites ── */}
          {favoriteProjects.length > 0 && favoriteProjects.map((proj) => (
            <ProjectItem
              key={proj.id}
              project={proj}
              isActive={activeTab === proj.id}
            />
          ))}

          <NavLink
            to="/jobs"
            className={({ isActive }) =>
              cn(NAV_ITEM, isActive && 'bg-accent text-accent-foreground font-medium')
            }
            data-testid="sidebar-jobs"
          >
            <Clock size={14} className="shrink-0" />
            <span>Jobs</span>
          </NavLink>

          <NavLink
            to="/projects"
            className={({ isActive }) =>
              cn(NAV_ITEM, isActive && 'bg-accent text-accent-foreground font-medium')
            }
            data-testid="sidebar-projects"
          >
            <Folder size={14} className="shrink-0" />
            <span>Projects</span>
          </NavLink>

        </div>

        {/* ── Sessions ── */}
        <div className="sidebar-sessions mt-3 pt-2 border-t border-border flex-1 min-h-0 overflow-y-auto">
          <WorkerPanel />
        </div>

      </nav>

      {/* ── Connection status ── */}
      <div className="sidebar-status flex align-middle items-center gap-2 px-5 py-2 mt-2">
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

      {/* ── Footer ── */}
      <div
        className="sidebar-footer flex items-center gap-1 px-2 py-2 border-t border-border shrink-0"
        data-testid="sidebar-footer"
        onClick={(e) => {
          // Auto-close sidebar on mobile when clicking a nav link in the footer
          if (window.innerWidth < 768 && (e.target as HTMLElement).closest('a')) {
            onToggle();
          }
        }}
      >
        {/* Notification bell */}
        <div className="notification-bell-wrapper relative">
          <button
            className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
            data-action="notifications"
            title="Notifications"
          >
            <Bell size={16} />
          </button>
          {notificationUnreadCount > 0 && (
            <span className="notification-badge absolute -top-1 -right-1 flex items-center justify-center min-w-[16px] h-4 px-0.5 rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold leading-none cursor-pointer">
              {notificationUnreadCount > 99 ? '99+' : notificationUnreadCount}
            </span>
          )}
        </div>

        {/* Theme toggle */}
        <button
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
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
              'hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer',
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
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
          data-action="docs"
          title="Documentation"
        >
          <BookOpen size={16} />
        </button>

        {/* Help */}
        <button
          className="sidebar-icon flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors cursor-pointer"
          data-action="help"
          title="Help"
        >
          <HelpCircle size={16} />
        </button>
      </div>
    </aside>
  );
}
