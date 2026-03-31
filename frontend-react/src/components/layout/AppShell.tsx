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
import { Outlet, NavLink } from 'react-router-dom';
import { useState } from 'react';
import { Settings, Home, PanelLeft } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useProjectStore } from '../../stores/useProjectStore';
import { useThemeStore } from '../../stores/useThemeStore';

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const projects = useProjectStore((s) => s.projects);
  const theme = useThemeStore((s) => s.theme);

  return (
    <div className={cn('app-container flex flex-col h-screen w-screen overflow-hidden', theme)}>
      {/* ── Main layout row ── */}
      <div className="app-layout flex flex-1 overflow-hidden">

        {/* ── Sidebar ── */}
        <aside
          className={cn(
            'sidebar flex flex-col bg-sidebar border-r border-border transition-all duration-200',
            sidebarOpen ? 'w-56' : 'w-0 overflow-hidden',
          )}
          data-testid="sidebar"
        >
          {/* Brand */}
          <div className="sidebar-brand flex items-center gap-2 px-4 py-3 border-b border-border">
            <span className="text-xl">🔥</span>
            <span className="font-semibold text-sm text-foreground">Voxyflow</span>
          </div>

          {/* Nav content */}
          <nav className="sidebar-content flex-1 overflow-y-auto py-2">
            {/* Main / General */}
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                cn(
                  'sidebar-item flex items-center gap-2 px-3 py-2 mx-2 rounded-md text-sm cursor-pointer',
                  'hover:bg-accent hover:text-accent-foreground',
                  isActive && 'bg-accent text-accent-foreground font-medium',
                )
              }
            >
              <Home size={15} />
              <span>Main</span>
            </NavLink>

            {/* Projects list */}
            {projects.length > 0 && (
              <div className="mt-3">
                <p className="sidebar-section-header px-5 py-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Projects
                </p>
                {projects
                  .filter((p) => !p.archived)
                  .map((project) => (
                    <NavLink
                      key={project.id}
                      to={`/project/${project.id}`}
                      className={({ isActive }) =>
                        cn(
                          'sidebar-item flex items-center gap-2 px-3 py-1.5 mx-2 rounded-md text-sm cursor-pointer',
                          'hover:bg-accent hover:text-accent-foreground',
                          isActive && 'bg-accent text-accent-foreground font-medium',
                        )
                      }
                    >
                      <span>{project.emoji ?? '📁'}</span>
                      <span className="truncate">{project.name}</span>
                    </NavLink>
                  ))}
              </div>
            )}
          </nav>

          {/* Footer */}
          <div className="sidebar-footer border-t border-border px-2 py-2 flex items-center gap-1">
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  'flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground',
                  'hover:bg-accent hover:text-accent-foreground',
                  isActive && 'text-foreground',
                )
              }
              title="Settings"
            >
              <Settings size={16} />
            </NavLink>
          </div>
        </aside>

        {/* ── Main area ── */}
        <div className="main-area flex flex-col flex-1 overflow-hidden">
          {/* TopBar */}
          <header className="top-bar flex items-center gap-2 px-4 py-2 border-b border-border bg-background shrink-0">
            <button
              onClick={() => setSidebarOpen((o) => !o)}
              className="top-bar-menu-btn p-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
              title="Toggle sidebar"
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
    </div>
  );
}
