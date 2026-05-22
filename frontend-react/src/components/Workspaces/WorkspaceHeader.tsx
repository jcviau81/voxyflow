import { Home, MessageSquare, LayoutGrid, Pin, Brain, BarChart2, Pencil, Archive, Zap } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useTabStore } from '../../stores/useTabStore';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useViewStore } from '../../stores/useViewStore';
import { useIsDesktop } from '../../hooks/useIsDesktop';
import { useToastStore } from '../../stores/useToastStore';
import {
  useWorkspaceAutonomy,
  useUpsertWorkspaceAutonomy,
} from '../../hooks/api/useWorkspaceAutonomy';
import type { ViewMode } from '../../types';

interface WorkspaceTab {
  view: ViewMode;
  icon: React.ReactNode;
  label: string;
}

const PROJECT_TABS: WorkspaceTab[] = [
  { view: 'chat',      icon: <MessageSquare size={13} />, label: 'Chat' },
  { view: 'kanban',    icon: <LayoutGrid size={13} />,    label: 'Kanban' },
  { view: 'freeboard', icon: <Pin size={13} />,           label: 'Backlog' },
  { view: 'knowledge', icon: <Brain size={13} />,         label: 'Knowledge' },
  { view: 'archives',  icon: <Archive size={13} />,       label: 'Archives' },
  { view: 'stats',     icon: <BarChart2 size={13} />,     label: 'Stats' },
];

// Main tab only shows a subset of views
const MAIN_VIEWS: ViewMode[] = ['chat', 'kanban', 'freeboard', 'knowledge', 'archives'];

interface WorkspaceHeaderProps {
  onOpenWorkspaceProperties?: (workspaceId: string) => void;
}

export function WorkspaceHeader({ onOpenWorkspaceProperties }: WorkspaceHeaderProps) {
  const activeTab = useTabStore((s) => s.activeTab);
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const getWorkspace = useWorkspaceStore((s) => s.getWorkspace);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const isDesktop = useIsDesktop();
  const { showToast } = useToastStore();

  const isMainTab = activeTab === 'main';
  const workspace = currentWorkspaceId ? getWorkspace(currentWorkspaceId) : undefined;

  // Autonomy toggle — Home uses the system-main workspace, regular workspace tabs use the active one.
  const autonomyWorkspaceId = isMainTab ? 'system-main' : currentWorkspaceId ?? undefined;
  const { data: autonomy } = useWorkspaceAutonomy(autonomyWorkspaceId);
  const upsertAutonomy = useUpsertWorkspaceAutonomy();

  const toggleAutonomy = async () => {
    if (!autonomyWorkspaceId) return;
    const next = !(autonomy?.enabled ?? false);
    try {
      await upsertAutonomy.mutateAsync({
        workspaceId: autonomyWorkspaceId,
        enabled: next,
        schedule: autonomy?.schedule,
        directive: autonomy?.directive,
      });
      showToast(next ? 'Autonomy resumed' : 'Autonomy paused', 'success');
    } catch (e) {
      showToast(`Could not toggle autonomy: ${(e as Error).message}`, 'error');
    }
  };

  const autonomyOn = autonomy?.enabled ?? false;
  const autonomyDisabled = !autonomyWorkspaceId || upsertAutonomy.isPending || !autonomy;

  // Hidden when on a workspace tab but no workspace is loaded
  if (!isMainTab && !workspace) {
    return null;
  }

  let visibleTabs = isMainTab
    ? PROJECT_TABS.filter((t) => MAIN_VIEWS.includes(t.view))
    : PROJECT_TABS;

  // On desktop, hide Chat tab (chat is always visible in the left panel)
  if (isDesktop) {
    visibleTabs = visibleTabs.filter((t) => t.view !== 'chat');
  }

  return (
    <div
      className="workspace-header flex items-center justify-between px-4 py-1 border-b border-border bg-background shrink-0"
      data-testid="workspace-header"
    >
      {/* Left: workspace emoji + name */}
      {isMainTab ? (
        <div className="workspace-header__title flex items-center gap-1.5">
          <Home size={15} className="text-muted-foreground" />
          <span className="workspace-header__name text-sm font-medium text-foreground">Home</span>
        </div>
      ) : (
        <div className="workspace-header__title flex items-center gap-1.5">
          <span className="workspace-header__emoji text-base">{workspace!.emoji || '📁'}</span>
          <span className="workspace-header__name text-sm font-medium text-foreground">
            {workspace!.name}
          </span>
          <button
            className="gap-1.5 p-1 rounded hover:bg-accent transition-colors cursor-pointer text-muted-foreground hover:text-foreground"
            title="Workspace properties"
            onClick={() => {
              if (currentWorkspaceId) {
                onOpenWorkspaceProperties?.(currentWorkspaceId);
              }
            }}
          >
            <Pencil size={13} />
          </button>
        </div>
      )}

      {/* Right: autonomy toggle + view navigation tabs */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={autonomyOn}
          aria-label={autonomyOn ? 'Pause Autonomy' : 'Enable Autonomy'}
          onClick={() => void toggleAutonomy()}
          disabled={autonomyDisabled}
          title={
            !autonomy
              ? 'Loading autonomy status…'
              : autonomyOn
              ? 'Autonomy is running — click to pause'
              : 'Autonomy is paused — click to enable'
          }
          className={cn(
            'flex items-center gap-1.5 text-[11px] font-medium select-none',
            autonomyDisabled ? 'opacity-50 cursor-wait' : 'cursor-pointer',
          )}
          data-testid="workspace-header-autonomy-toggle"
        >
          <Zap
            size={12}
            className={cn(
              'shrink-0',
              autonomyOn ? 'text-primary' : 'text-muted-foreground',
            )}
          />
          <span className={autonomyOn ? 'text-foreground' : 'text-muted-foreground'}>
            Autonomy
          </span>
          <span
            className={cn(
              'relative inline-flex h-[14px] w-[26px] rounded-full transition-colors',
              autonomyOn ? 'bg-primary' : 'bg-muted-foreground/30',
            )}
          >
            <span
              className={cn(
                'absolute top-[2px] h-[10px] w-[10px] rounded-full bg-background shadow transition-[left]',
                autonomyOn ? 'left-[14px]' : 'left-[2px]',
              )}
            />
          </span>
        </button>
      <nav className="workspace-header__tabs flex items-center gap-1">
        {visibleTabs.map((tab) => {
          const isActive = currentView === tab.view;
          return (
            <button
              key={tab.view}
              data-view={tab.view}
              onClick={() => {
                if (currentView !== tab.view) setView(tab.view);
              }}
              className={cn(
                'workspace-header__tab flex items-center gap-1.5 px-3 py-1 text-xs rounded transition-colors cursor-pointer',
                isActive
                  ? 'workspace-header__tab--active bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              )}
            >
              {tab.icon} <span className="hidden md:inline">{tab.label}</span>
            </button>
          );
        })}
      </nav>
      </div>
    </div>
  );
}
