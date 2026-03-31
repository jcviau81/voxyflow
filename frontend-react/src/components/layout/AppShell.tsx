/**
 * AppShell — top-level layout matching the vanilla frontend structure.
 *
 * Vanilla layout (from App.ts):
 *   .app-container
 *     .app-layout
 *       aside.sidebar-container      ← Sidebar (nav + projects + footer)
 *       .main-area
 *         .top-bar-container         ← TopBar (hamburger, project name, layer toggles)
 *         .tab-bar-container         ← TabBar (session tabs)
 *         .project-header-container  ← ProjectHeader (view tabs: kanban/chat/stats…)
 *         main.main-content          ← <Outlet /> (routed page)
 *       aside.worker-panel-container ← WorkerPanel (active Deep workers)
 *       aside.opportunities-container← RightPanel (Opportunities + Notifications)
 */
import { Outlet } from 'react-router-dom';
import { useState, useEffect, useCallback } from 'react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/useThemeStore';
import { useViewStore } from '../../stores/useViewStore';
import { CardDetailModal } from '../CardDetail';
import { Sidebar } from '../Navigation/Sidebar';
import { TabBar } from '../Navigation/TabBar';
import { TopBar } from '../Navigation/TopBar';
import { ProjectHeader } from '../Projects';
import { WorkerPanel } from '../RightPanel/WorkerPanel';
import { RightPanel } from '../RightPanel/RightPanel';
import { useChatService } from '../../contexts/useChatService';
import type { CardSuggestion } from '../../contexts/ChatProvider';

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [opportunities, setOpportunities] = useState<CardSuggestion[]>([]);
  const theme = useThemeStore((s) => s.theme);
  const setView = useViewStore((s) => s.setView);
  const { registerCallbacks } = useChatService();

  // Subscribe to card suggestion events from ChatProvider
  useEffect(() => {
    return registerCallbacks({
      onCardSuggestion: (suggestion) => {
        setOpportunities((prev) => [...prev, suggestion]);
      },
    });
  }, [registerCallbacks]);

  const toggleSidebar = useCallback(() => setSidebarOpen((o) => !o), []);

  // Global keyboard shortcuts (Ctrl+1 → chat, Ctrl+2 → kanban, Ctrl+B → sidebar)
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key === '1') {
        e.preventDefault();
        setView('chat');
      } else if (e.ctrlKey && e.key === '2') {
        e.preventDefault();
        setView('kanban');
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }
    };
    document.addEventListener('keydown', handleKeydown);
    return () => document.removeEventListener('keydown', handleKeydown);
  }, [setView, toggleSidebar]);

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
          {/* TopBar: hamburger + project name + mode pill + voice toggles */}
          <TopBar onMenuClick={toggleSidebar} />

          {/* TabBar: session tabs (Main + open projects) */}
          <TabBar />

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

        {/* ── Right panel (Opportunities + Notifications) ── */}
        <aside className="opportunities-container">
          <RightPanel
            opportunities={opportunities}
            onOpportunityAccepted={handleOpportunityAccepted}
            onOpportunityDismissed={handleOpportunityDismissed}
          />
        </aside>
      </div>

      {/* Global card detail modal — opens when selectedCardId is set */}
      <CardDetailModal />
    </div>
  );
}
