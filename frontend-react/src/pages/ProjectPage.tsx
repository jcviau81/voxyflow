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
import { useEffect, useRef, useState, useCallback } from 'react';
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

  // Desktop: resizable split layout — chat left (default 40%, max 50%) + content right
  const [chatPct, setChatPct] = useState(40);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, []);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setChatPct(Math.min(50, Math.max(20, pct)));
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  if (isDesktop) {
    return (
      <div className={cn('project-page flex flex-col h-full w-full overflow-hidden', `project-page--${view}`)}>
        {/* BoardHeader portals here (rendered by KanbanBoard/FreeBoard) */}
        <div id="board-header-slot" />
        <div ref={containerRef} className="flex flex-row flex-1 overflow-hidden">
          <div style={{ width: `${chatPct}%` }} className="min-w-70 flex flex-col">
            <ChatWindow
              tabId={id}
              chatLevel="project"
              projectId={id}
              className="flex-1"
            />
          </div>
          {/* Drag handle */}
          <div
            onMouseDown={onMouseDown}
            className="w-1 cursor-col-resize bg-border hover:bg-primary/40 active:bg-primary/60 transition-colors shrink-0"
          />
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
