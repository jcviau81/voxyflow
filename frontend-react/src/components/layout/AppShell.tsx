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
 *
 * Components are stubs for now — replaced as migration progresses.
 */
import { Outlet } from 'react-router-dom';
import { useState } from 'react';
import { PanelLeft } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/useThemeStore';
import { CardDetailModal } from '../CardDetail';
import { Sidebar } from '../Navigation/Sidebar';

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const theme = useThemeStore((s) => s.theme);

  return (
    <div className={cn('app-container flex flex-col h-screen w-screen overflow-hidden', theme)}>
      {/* ── Main layout row ── */}
      <div className="app-layout flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <Sidebar isOpen={sidebarOpen} onToggle={() => setSidebarOpen((o) => !o)} />

        {/* ── Main area ── */}
        <div className="main-area flex flex-col flex-1 overflow-hidden">
          {/* TopBar */}
          <header className="top-bar flex items-center gap-2 px-4 py-2 border-b border-border bg-background shrink-0">
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className="top-bar-menu-btn p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
              title="Toggle sidebar (Ctrl+B)"
            >
              <PanelLeft size={18} />
            </button>
            {/* Project name + layer toggles will be rendered here once TopBar is migrated */}
          </header>

          {/* Routed page content */}
          <main className="main-content flex-1 overflow-auto">
            <Outlet />
          </main>
        </div>

        {/* ── Right panel placeholder ── */}
        {/* WorkerPanel + RightPanel added once those components are migrated */}
      </div>

      {/* Global card detail modal — opens when selectedCardId is set */}
      <CardDetailModal />
    </div>
  );
}
