import { Home, MessageSquare, LayoutGrid, Pin, Brain, BarChart2, Pencil, Archive, Zap } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useTabStore } from '../../stores/useTabStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useViewStore } from '../../stores/useViewStore';
import { useIsDesktop } from '../../hooks/useIsDesktop';
import { useToastStore } from '../../stores/useToastStore';
import {
  useProjectAutonomy,
  useUpsertProjectAutonomy,
} from '../../hooks/api/useProjectAutonomy';
import type { ViewMode } from '../../types';

interface ProjectTab {
  view: ViewMode;
  icon: React.ReactNode;
  label: string;
}

const PROJECT_TABS: ProjectTab[] = [
  { view: 'chat',      icon: <MessageSquare size={13} />, label: 'Chat' },
  { view: 'kanban',    icon: <LayoutGrid size={13} />,    label: 'Kanban' },
  { view: 'freeboard', icon: <Pin size={13} />,           label: 'Backlog' },
  { view: 'knowledge', icon: <Brain size={13} />,         label: 'Knowledge' },
  { view: 'archives',  icon: <Archive size={13} />,       label: 'Archives' },
  { view: 'stats',     icon: <BarChart2 size={13} />,     label: 'Stats' },
];

// Main tab only shows a subset of views
const MAIN_VIEWS: ViewMode[] = ['chat', 'kanban', 'freeboard', 'knowledge', 'archives'];

interface ProjectHeaderProps {
  onOpenProjectProperties?: (projectId: string) => void;
}

export function ProjectHeader({ onOpenProjectProperties }: ProjectHeaderProps) {
  const activeTab = useTabStore((s) => s.activeTab);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const getProject = useProjectStore((s) => s.getProject);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const isDesktop = useIsDesktop();
  const { showToast } = useToastStore();

  const isMainTab = activeTab === 'main';
  const project = currentProjectId ? getProject(currentProjectId) : undefined;

  // Autonomy toggle — Home uses the system-main project, regular project tabs use the active one.
  const autonomyProjectId = isMainTab ? 'system-main' : currentProjectId ?? undefined;
  const { data: autonomy } = useProjectAutonomy(autonomyProjectId);
  const upsertAutonomy = useUpsertProjectAutonomy();

  const toggleAutonomy = async () => {
    if (!autonomyProjectId) return;
    const next = !(autonomy?.enabled ?? false);
    try {
      await upsertAutonomy.mutateAsync({
        projectId: autonomyProjectId,
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
  const autonomyDisabled = !autonomyProjectId || upsertAutonomy.isPending || !autonomy;

  // Hidden when on a project tab but no project is loaded
  if (!isMainTab && !project) {
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
      className="project-header flex items-center justify-between px-4 py-1 border-b border-border bg-background shrink-0"
      data-testid="project-header"
    >
      {/* Left: project emoji + name */}
      {isMainTab ? (
        <div className="project-header__title flex items-center gap-1.5">
          <Home size={15} className="text-muted-foreground" />
          <span className="project-header__name text-sm font-medium text-foreground">Home</span>
        </div>
      ) : (
        <div className="project-header__title flex items-center gap-1.5">
          <span className="project-header__emoji text-base">{project!.emoji || '📁'}</span>
          <span className="project-header__name text-sm font-medium text-foreground">
            {project!.name}
          </span>
          <button
            className="gap-1.5 p-1 rounded hover:bg-accent transition-colors cursor-pointer text-muted-foreground hover:text-foreground"
            title="Project properties"
            onClick={() => {
              if (currentProjectId) {
                onOpenProjectProperties?.(currentProjectId);
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
          data-testid="project-header-autonomy-toggle"
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
      <nav className="project-header__tabs flex items-center gap-1">
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
                'project-header__tab flex items-center gap-1.5 px-3 py-1 text-xs rounded transition-colors cursor-pointer',
                isActive
                  ? 'project-header__tab--active bg-accent text-accent-foreground font-medium'
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
