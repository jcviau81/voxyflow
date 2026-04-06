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
 *       aside.worker-panel-container ← WorkerPanel (active Deep workers)
 *     OpportunitiesPanel / NotificationsPanel drawers (fixed, toggled from TabBar)
 */
import { Outlet, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/useThemeStore';
import { useViewStore } from '../../stores/useViewStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { CardDetailModal } from '../CardDetail';
import { Sidebar } from '../Navigation/Sidebar';
import { TabBar } from '../Navigation/TabBar';
import { ProjectHeader } from '../Projects';
import { WorkerPanel } from '../RightPanel/WorkerPanel';
import { OpportunitiesPanel } from '../RightPanel/OpportunitiesPanel';
import { NotificationsPanel } from '../RightPanel/NotificationsPanel';
import { useChatService } from '../../contexts/useChatService';
import { useProjects } from '../../hooks/api/useProjects';
import { useWorkerSync } from '../../hooks/useWorkerSync';
import type { CardSuggestion } from '../../contexts/ChatProvider';

type OpenPanel = 'opportunities' | 'notifications' | null;

export function AppShell() {
  const location = useLocation();
  const isFullPage = ['/settings', '/jobs', '/projects'].includes(location.pathname);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [opportunities, setOpportunities] = useState<CardSuggestion[]>([]);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const theme = useThemeStore((s) => s.theme);
  const { registerCallbacks } = useChatService();

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

  // Subscribe to card suggestion events from ChatProvider
  useEffect(() => {
    return registerCallbacks({
      onCardSuggestion: (suggestion) => {
        setOpportunities((prev) => [...prev, suggestion]);
      },
    });
    // registerCallbacks is stable (useCallback with [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleSidebar = useCallback(() => setSidebarOpen((o) => !o), []);

  const handlePanelToggle = useCallback((panel: 'opportunities' | 'notifications') => {
    setOpenPanel((prev) => (prev === panel ? null : panel));
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '1') {
        e.preventDefault();
        useViewStore.getState().setView('chat');
      } else if (e.ctrlKey && e.key === '2') {
        e.preventDefault();
        useViewStore.getState().setView('kanban');
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

  const handleOpportunityAccepted = useCallback((id: string) => {
    setOpportunities((prev) => prev.filter((o) => o.id !== id));
  }, []);

  const handleOpportunityDismissed = useCallback((id: string) => {
    setOpportunities((prev) => prev.filter((o) => o.id !== id));
  }, []);

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
                opportunityCount={opportunities.length}
                onPanelToggle={handlePanelToggle}
                onSidebarToggle={toggleSidebar}
              />
              <ProjectHeader />
            </>
          )}
          <main className="main-content flex-1 overflow-auto">
            <Outlet context={{ sidebarToggle: toggleSidebar }} />
          </main>
        </div>

        {/* ── Worker panel (active Deep workers) — hidden on mobile ── */}
        <aside className="worker-panel-container hidden md:block">
          <WorkerPanel />
        </aside>
      </div>

      {/* ── Backdrop (click outside to close any open panel) ── */}
      {openPanel && (
        <div className="fixed inset-0 z-40" onClick={closePanel} />
      )}

      {/* ── Opportunities drawer ── */}
      <aside
        className={cn(
          'fixed top-0 right-0 bottom-0 z-50 w-72 flex flex-col',
          'bg-secondary border-l border-border shadow-2xl',
          'transition-transform duration-200',
          openPanel === 'opportunities' ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <OpportunitiesPanel
          opportunities={opportunities}
          onAccepted={handleOpportunityAccepted}
          onDismissed={handleOpportunityDismissed}
          onClose={closePanel}
        />
      </aside>

      {/* ── Notifications drawer ── */}
      <aside
        className={cn(
          'fixed top-0 right-0 bottom-0 z-50 w-72 flex flex-col',
          'bg-secondary border-l border-border shadow-2xl',
          'transition-transform duration-200',
          openPanel === 'notifications' ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <NotificationsPanel
          onClose={closePanel}
          onOpenOpportunities={() => setOpenPanel('opportunities')}
        />
      </aside>

      {/* Global card detail modal */}
      <CardDetailModal />
    </div>
  );
}
