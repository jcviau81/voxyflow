/**
 * AppShell — top-level layout.
 *
 *   .app-container
 *     .app-layout
 *       aside.sidebar-container      ← Sidebar (nav + workspaces + footer)
 *       .main-area
 *         .tab-bar-container         ← TabBar (session tabs + panel triggers)
 *         .workspace-header-container  ← WorkspaceHeader (view tabs: kanban/chat/stats…)
 *         main.main-content          ← <Outlet /> (routed page)
 *     NotificationsPanel drawer (fixed, toggled from TabBar)
 */
import { Outlet, useLocation } from 'react-router-dom';
import { useState, useEffect, useCallback, useRef } from 'react';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../stores/useThemeStore';
import { useViewStore } from '../../stores/useViewStore';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useTabStore } from '../../stores/useTabStore';
import { CardDetailModal } from '../CardDetail';
import { Sidebar } from '../Navigation/Sidebar';
import { TabBar } from '../Navigation/TabBar';
import { WorkspaceHeader, WorkspaceForm } from '../Workspaces';
import { NotificationsPanel } from '../RightPanel/NotificationsPanel';
import { CommandPalette } from '../CommandPalette';
import { useWorkspaces } from '../../hooks/api/useWorkspaces';
import { useWorkerSync } from '../../hooks/useWorkerSync';

type OpenPanel = 'notifications' | null;

export function AppShell() {
  const location = useLocation();
  const isFullPage = ['/settings', '/jobs', '/workspaces'].includes(location.pathname);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth >= 768);
  const [openPanel, setOpenPanel] = useState<OpenPanel>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [editWorkspaceId, setEditWorkspaceId] = useState<string | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // Wire WS → worker store (must be inside WebSocketProvider)
  useWorkerSync();

  // Sync TanStack Query workspaces → Zustand store so Sidebar/Nav can read from store
  const { data: workspaces } = useWorkspaces();
  const workspacesRef = useRef(workspaces);

  useEffect(() => {
    if (workspaces && workspaces !== workspacesRef.current) {
      workspacesRef.current = workspaces;
      useWorkspaceStore.getState().setWorkspaces(workspaces);
    }
  }, [workspaces]);

  // ── URL → store sync (single source of truth) ──
  useEffect(() => {
    const match = location.pathname.match(/^\/workspace\/(.+)$/);
    const workspaceId = match?.[1] ?? null;

    const pStore = useWorkspaceStore.getState();
    const tStore = useTabStore.getState();

    if (workspaceId) {
      // Sync workspace store from URL
      if (pStore.currentWorkspaceId !== workspaceId) {
        pStore.selectWorkspace(workspaceId);
      }
      // Ensure tab exists and is active
      const tabExists = tStore.openTabs.some((t) => t.id === workspaceId);
      if (!tabExists) {
        const workspace = pStore.getWorkspace(workspaceId);
        tStore.openWorkspaceTab(workspaceId, workspace?.name ?? 'Workspace', workspace?.emoji);
      } else if (tStore.activeTab !== workspaceId) {
        tStore.switchTab(workspaceId);
      }
    } else {
      // Main page or non-workspace route
      if (pStore.currentWorkspaceId !== null) {
        pStore.selectWorkspace(null);
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
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (e.ctrlKey && e.key === '1') {
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
        <Sidebar
          isOpen={sidebarOpen}
          onToggle={toggleSidebar}
          onPanelToggle={handlePanelToggle}
          onOpenCommandPalette={() => setPaletteOpen(true)}
        />

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
              <WorkspaceHeader onOpenWorkspaceProperties={setEditWorkspaceId} />
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

      {/* Global command palette (Cmd/Ctrl+K) */}
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onToggleSidebar={toggleSidebar}
      />

      {/* Global card detail modal */}
      <CardDetailModal />

      {/* Workspace properties modal */}
      {editWorkspaceId && (
        <WorkspaceForm
          mode="edit"
          workspace={useWorkspaceStore.getState().getWorkspace(editWorkspaceId)}
          onClose={() => setEditWorkspaceId(null)}
        />
      )}
    </div>
  );
}
