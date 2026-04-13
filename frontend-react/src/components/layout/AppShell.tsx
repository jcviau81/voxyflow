/**
 * AppShell — top-level layout.
 *
 *   .app-container
 *     .app-layout
 *       aside.sidebar-container      ← Sidebar (nav + projects + footer)
 *       .main-area
 *         .tab-bar-container         ← TabBar (session tabs + panel triggers)
 *         .project-header-container  ← ProjectHeader (view tabs: kanban/chat/stats…)
 *         main.main-content          ← <Outlet /> (routed page)
 *     NotificationsPanel drawer (fixed, toggled from TabBar)
 */
import { Outlet, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/useThemeStore';
import { useViewStore } from '../../stores/useViewStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useTabStore } from '../../stores/useTabStore';
import { CardDetailModal } from '../CardDetail';
import { Sidebar } from '../Navigation/Sidebar';
import { TabBar } from '../Navigation/TabBar';
import { ProjectHeader, ProjectForm } from '../Projects';
import { NotificationsPanel } from '../RightPanel/NotificationsPanel';
import { useProjects } from '../../hooks/api/useProjects';
import { useWorkerSync } from '../../hooks/useWorkerSync';

type OpenPanel = 'notifications' | null;

export function AppShell() {
  const location = useLocation();
  const isFullPage = ['/settings', '/jobs', '/projects'].includes(location.pathname);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // Wire WS → worker store (must be inside WebSocketProvider)
  useWorkerSync();

  // Sync TanStack Query projects → Zustand store so Sidebar/Nav can read from store
  const { data: projects } = useProjects();
  const projectsRef = useRef(projects);

  useEffect(() => {
    if (projects && projects !== projectsRef.current) {
      projectsRef.current = projects;
      useProjectStore.getState().setProjects(projects);
    }
  }, [projects]);

  // ── URL → store sync (single source of truth) ──
  useEffect(() => {
    const match = location.pathname.match(/^\/project\/(.+)$/);
    const projectId = match?.[1] ?? null;

    const pStore = useProjectStore.getState();
    const tStore = useTabStore.getState();

    if (projectId) {
      // Sync project store from URL
      if (pStore.currentProjectId !== projectId) {
        pStore.selectProject(projectId);
      }
      // Ensure tab exists and is active
      const tabExists = tStore.openTabs.some((t) => t.id === projectId);
      if (!tabExists) {
        const project = pStore.getProject(projectId);
        tStore.openProjectTab(projectId, project?.name ?? 'Project', project?.emoji);
      } else if (tStore.activeTab !== projectId) {
        tStore.switchTab(projectId);
      }
    } else {
      // Main page or non-project route
      if (pStore.currentProjectId !== null) {
        pStore.selectProject(null);
      }
      if (tStore.activeTab !== 'main') {
        tStore.switchTab('main');
      }
    }
  }, [location.pathname]);

  const toggleSidebar = useCallback(() => setSidebarOpen((o) => !o), []);

  const handlePanelToggle = useCallback((panel: 'notifications') => {
    setOpenPanel((prev) => (prev === panel ? null : panel));
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '1') {
        e.preventDefault();
        useViewStore.getState().setView('kanban');
      } else if (e.ctrlKey && e.key === '2') {
        e.preventDefault();
        useViewStore.getState().setView('freeboard');
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      } else if (e.key === 'Escape') {
        setOpenPanel(null);
      }
    };
    document.addEventListener('keydown', handleKeydown);
    return () => document.removeEventListener('keydown', handleKeydown);
  }, [toggleSidebar]);

  const closePanel = useCallback(() => setOpenPanel(null), []);

  return (
    <div className={cn('app-container flex flex-col h-screen w-screen overflow-hidden', theme)}>
      {/* ── Main layout row ── */}
      <div className="app-layout flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <Sidebar isOpen={sidebarOpen} onToggle={toggleSidebar} />

        {/* Mobile overlay — tap outside to close sidebar */}
        {sidebarOpen && (
          <div
            className="sidebar-overlay fixed inset-0 z-20 bg-black/40 md:hidden"
            onClick={toggleSidebar}
          />
        )}

        {/* ── Main area ── */}
        <div className="main-area flex flex-col flex-1 overflow-hidden">
          {!isFullPage && (
            <>
              <TabBar
                onPanelToggle={handlePanelToggle}
                onSidebarToggle={toggleSidebar}
              />
              <ProjectHeader onOpenProjectProperties={setEditProjectId} />
            </>
          )}
          <main className="main-content flex-1 overflow-auto">
            <Outlet context={{ sidebarToggle: toggleSidebar }} />
          </main>
        </div>

      </div>

      {/* ── Backdrop (click outside to close any open panel) ── */}
      {openPanel && (
        <div className="fixed inset-0 z-40" onClick={closePanel} />
      )}

      {/* ── Notifications drawer ── */}
      <aside
        className={cn(
          'fixed top-0 right-0 bottom-0 z-50 w-72 flex flex-col',
          'bg-secondary border-l border-border shadow-2xl',
          'transition-transform duration-200',
          openPanel === 'notifications' ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <NotificationsPanel onClose={closePanel} />
      </aside>

      {/* Global card detail modal */}
      <CardDetailModal />

      {/* Project properties modal */}
      {editProjectId && (
        <ProjectForm
          mode="edit"
          project={useProjectStore.getState().getProject(editProjectId)}
          onClose={() => setEditProjectId(null)}
        />
      )}
    </div>
  );
}
