/**
 * ProjectPage — renders a project tab with view switching.
 *
 * Mirrors the switchView logic in vanilla App.ts for project tabs:
 *   - 'chat'      → ChatWindow (project-scoped)
 *   - 'kanban'    → KanbanBoard
 *   - 'freeboard' → FreeBoard
 *   - 'knowledge' → ProjectKnowledge
 *   - 'stats'     → ProjectStats
 *   - 'docs'      → ProjectDocuments
 *
 * On mount: sets currentProjectId in the store so all child components
 * pick up the correct project context automatically.
 */
import { useEffect } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { ChatWindow } from '../components/Chat/ChatWindow';
import { KanbanBoard } from '../components/Kanban/KanbanBoard';
import { FreeBoard } from '../components/Board/FreeBoard';
import { ProjectKnowledge } from '../components/Projects/ProjectKnowledge';
import { ProjectStats } from '../components/Projects/ProjectStats';
import { useViewStore } from '../stores/useViewStore';
import { useProjectStore } from '../stores/useProjectStore';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { cn } from '../lib/utils';

const PROJECT_VIEWS = new Set(['chat', 'kanban', 'freeboard', 'knowledge', 'stats']);

export function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const selectCard = useProjectStore((s) => s.selectCard);
  const getProject = useProjectStore((s) => s.getProject);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const isDesktop = useIsDesktop();

  // Reset to kanban if current view is not valid for a project tab
  useEffect(() => {
    if (!PROJECT_VIEWS.has(currentView)) {
      setView('kanban');
    }
  }, [currentView, setView]);

  if (!id) {
    return <Navigate to="/" replace />;
  }

  const project = getProject(id);
  if (!project) {
    return null;
  }

  // On desktop, 'chat' view falls back to 'kanban' (chat is always visible in left panel)
  const rawView = PROJECT_VIEWS.has(currentView) ? currentView : 'kanban';
  const view = (isDesktop && rawView === 'chat') ? 'kanban' : rawView;

  const handleCardClick = (cardId: string) => {
    selectCard(cardId);
  };

  const contentPanel = (
    <>
      {view === 'kanban' && (
        <KanbanBoard key={id} projectId={id} onCardClick={handleCardClick} />
      )}
      {view === 'freeboard' && (
        <FreeBoard key={id} projectId={id} />
      )}
      {view === 'knowledge' && (
        <ProjectKnowledge />
      )}
      {view === 'stats' && (
        <ProjectStats />
      )}
    </>
  );

  // Desktop: split layout — chat left (40%) + content right (60%)
  if (isDesktop) {
    return (
      <div className={cn('project-page flex flex-col h-full w-full overflow-hidden', `project-page--${view}`)}>
        {/* BoardHeader portals here (rendered by KanbanBoard/FreeBoard) */}
        <div id="board-header-slot" />
        <div className="flex flex-row flex-1 overflow-hidden">
          <div className="w-[40%] min-w-[280px] border-r border-border flex flex-col">
            <ChatWindow
              tabId={id}
              chatLevel="project"
              projectId={id}
              className="flex-1"
            />
          </div>
          <div className="flex-1 overflow-hidden flex flex-col">
            {contentPanel}
          </div>
        </div>
      </div>
    );
  }

  // Mobile: single-view (current behavior)
  return (
    <div className={cn('project-page flex flex-col h-full w-full overflow-hidden', `project-page--${view}`)}>
      {view === 'chat' && (
        <div className="chat-view flex flex-col h-full">
          <ChatWindow
            tabId={id}
            chatLevel="project"
            projectId={id}
            className="flex-1"
          />
        </div>
      )}
      {contentPanel}
    </div>
  );
}
