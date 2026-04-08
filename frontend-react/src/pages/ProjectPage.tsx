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
import { cn } from '../lib/utils';

const PROJECT_VIEWS = new Set(['chat', 'kanban', 'freeboard', 'knowledge', 'stats']);

export function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const selectCard = useProjectStore((s) => s.selectCard);
  const getProject = useProjectStore((s) => s.getProject);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);

  // Project ID sync is handled by AppShell's URL → store effect

  // Reset to chat if current view is not valid for a project tab
  useEffect(() => {
    if (!PROJECT_VIEWS.has(currentView)) {
      setView('chat');
    }
  }, [currentView, setView]);

  if (!id) {
    return <Navigate to="/" replace />;
  }

  // Guard: if project doesn't exist in the store yet (loading), render nothing
  const project = getProject(id);
  if (!project) {
    return null;
  }

  const view = PROJECT_VIEWS.has(currentView) ? currentView : 'chat';

  const handleCardClick = (cardId: string) => {
    selectCard(cardId);
  };

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
    </div>
  );
}
