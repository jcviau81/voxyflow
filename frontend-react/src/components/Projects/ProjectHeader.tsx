import { cn } from '../../lib/utils';
import { useTabStore } from '../../stores/useTabStore';
import { useProjectStore } from '../../stores/useProjectStore';
import { useViewStore } from '../../stores/useViewStore';
import type { ViewMode } from '../../types';

interface ProjectTab {
  view: ViewMode;
  emoji: string;
  label: string;
}

const PROJECT_TABS: ProjectTab[] = [
  { view: 'chat',      emoji: '💬', label: 'Chat' },
  { view: 'kanban',    emoji: '📋', label: 'Kanban' },
  { view: 'freeboard', emoji: '📌', label: 'Board' },
  { view: 'knowledge', emoji: '🧠', label: 'Knowledge' },
  { view: 'stats',     emoji: '📊', label: 'Stats' },
  { view: 'docs',      emoji: '📄', label: 'Docs' },
];

// Main tab only shows a subset of views
const MAIN_VIEWS: ViewMode[] = ['chat', 'kanban', 'freeboard'];

interface ProjectHeaderProps {
  onOpenProjectProperties?: (projectId: string) => void;
}

export function ProjectHeader({ onOpenProjectProperties }: ProjectHeaderProps) {
  const activeTab = useTabStore((s) => s.activeTab);
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const getProject = useProjectStore((s) => s.getProject);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);

  const isMainTab = activeTab === 'main';
  const project = currentProjectId ? getProject(currentProjectId) : undefined;

  // Hidden when on a project tab but no project is loaded
  if (!isMainTab && !project) {
    return null;
  }

  const visibleTabs = isMainTab
    ? PROJECT_TABS.filter((t) => MAIN_VIEWS.includes(t.view))
    : PROJECT_TABS;

  return (
    <div
      className="project-header flex items-center justify-between px-4 py-1 border-b border-border bg-background shrink-0"
      data-testid="project-header"
    >
      {/* Left: project emoji + name */}
      {isMainTab ? (
        <div className="project-header__title flex items-center gap-1.5">
          <span className="project-header__emoji text-base">🏠</span>
          <span className="project-header__name text-sm font-medium text-foreground">Main</span>
        </div>
      ) : (
        <button
          className="project-header__title flex items-center gap-1.5 rounded px-1 py-0.5 hover:bg-accent transition-colors cursor-pointer"
          title="Project properties"
          onClick={() => {
            if (currentProjectId) {
              onOpenProjectProperties?.(currentProjectId);
            }
          }}
        >
          <span className="project-header__emoji text-base">{project!.emoji || '📁'}</span>
          <span className="project-header__name text-sm font-medium text-foreground">
            {project!.name}
          </span>
        </button>
      )}

      {/* Right: view navigation tabs */}
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
                'project-header__tab px-3 py-1 text-xs rounded transition-colors',
                isActive
                  ? 'project-header__tab--active bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
              )}
            >
              {tab.emoji} {tab.label}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
