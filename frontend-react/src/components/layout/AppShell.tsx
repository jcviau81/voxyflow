/**
 * AppShell — top-level layout matching the vanilla frontend structure.
 *
 * Vanilla layout (from App.ts):
 *   .app-container
 *     .app-layout
 *       aside.sidebar-container      ← Sidebar (nav + projects + footer)
 *       .main-area
 *         .tab-bar-container         ← TabBar (session tabs + panel triggers)
 *         .project-header-container  ← ProjectHeader (view tabs: kanban/chat/stats…)
 *         main.main-content          ← <Outlet /> (routed page)
 *       aside.worker-panel-container ← WorkerPanel (active Deep workers)
 *     RightPanel drawer (fixed, toggled from TabBar)
 */
import { Outlet } from 'react-router-dom';
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
import { RightPanel } from '../RightPanel/RightPanel';
import { useChatService } from '../../contexts/useChatService';
import { useProjects } from '../../hooks/api/useProjects';
import type { CardSuggestion } from '../../contexts/ChatProvider';

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [opportunities, setOpportunities] = useState<CardSuggestion[]>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelTab, setPanelTab] = useState<'opportunities' | 'notifications'>('opportunities');
  const theme = useThemeStore((s) => s.theme);
  const { registerCallbacks } = useChatService();

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

  const handlePanelToggle = useCallback((tab: 'opportunities' | 'notifications') => {
    setPanelTab((prev) => {
      // If already open on same tab → close
      if (panelOpen && prev === tab) {
        setPanelOpen(false);
        return prev;
      }
      setPanelOpen(true);
      return tab;
    });
  }, [panelOpen]);

  // Global keyboard shortcuts (Ctrl+1 → chat, Ctrl+2 → kanban, Ctrl+B → sidebar)
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
          {/* TabBar: session tabs (Main + open projects) */}
          <TabBar
            opportunityCount={opportunities.length}
            onPanelToggle={handlePanelToggle}
          />

          {/* Project header — view tabs (Chat / Kanban / Board / Knowledge) */}
          <ProjectHeader />

          {/* Routed page content */}
          <main className="main-content flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>

        {/* ── Worker panel (active Deep workers) ── */}
        <aside className="worker-panel-container">
          <WorkerPanel />
        </aside>
      </div>

      {/* ── Right panel drawer (Opportunities + Notifications) ── */}
      {panelOpen && (
        <div
          className="fixed inset-0 z-40"
          onClick={() => setPanelOpen(false)}
        />
      )}
      <aside
        className={cn(
          'fixed top-0 right-0 bottom-0 z-50 w-72 flex flex-col',
          'bg-secondary border-l border-border shadow-2xl',
          'transition-transform duration-200',
          panelOpen ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        <RightPanel
          opportunities={opportunities}
          onOpportunityAccepted={handleOpportunityAccepted}
          onOpportunityDismissed={handleOpportunityDismissed}
          defaultTab={panelTab}
          onClose={() => setPanelOpen(false)}
        />
      </aside>

      {/* Global card detail modal — opens when selectedCardId is set */}
      <CardDetailModal />
    </div>
  );
}
