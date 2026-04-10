/**
 * ProjectPage — renders a project tab (or the home tab) with view switching.
 *
 * Used for both the home route (/) and project routes (/project/:id).
 * When no :id param is present, falls back to SYSTEM_PROJECT_ID (home project).
 * Home is a regular project — the only difference is it cannot be deleted.
 *
 * Views:
 *   - 'chat'      → ChatWindow
 *   - 'kanban'    → KanbanBoard
 *   - 'freeboard' → FreeBoard
 *   - 'knowledge' → ProjectKnowledge
 *   - 'projects'  → ProjectList (home only)
 *   - 'stats'     → ProjectStats (non-home only)
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { ChatWindow } from '../components/Chat/ChatWindow';
import { KanbanBoard } from '../components/Kanban/KanbanBoard';
import { FreeBoard } from '../components/Board/FreeBoard';
import { ProjectKnowledge } from '../components/Projects/ProjectKnowledge';
import { ProjectStats } from '../components/Projects/ProjectStats';
import { ProjectList } from '../components/Projects/ProjectList';
import { useViewStore } from '../stores/useViewStore';
import { useProjectStore } from '../stores/useProjectStore';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { SYSTEM_PROJECT_ID } from '../lib/constants';
import { cn } from '../lib/utils';

const ALL_VIEWS = new Set(['chat', 'kanban', 'freeboard', 'knowledge', 'projects', 'stats']);

export function ProjectPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const id = routeId ?? SYSTEM_PROJECT_ID;
  const isHome = id === SYSTEM_PROJECT_ID;

  const selectCard = useProjectStore((s) => s.selectCard);
  const getProject = useProjectStore((s) => s.getProject);
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const isDesktop = useIsDesktop();

  // Resizable split (desktop)
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

  // Reset to kanban if current view is invalid for this context
  useEffect(() => {
    if (!ALL_VIEWS.has(currentView)) {
      setView('kanban');
    } else if (isHome && currentView === 'stats') {
      setView('kanban');
    } else if (!isHome && currentView === 'projects') {
      setView('kanban');
    }
  }, [currentView, setView, isHome]);

  // Validate non-home project exists
  if (!isHome) {
    const project = getProject(id);
    if (!project) return <Navigate to="/" replace />;
  }

  const rawView = ALL_VIEWS.has(currentView) ? currentView : 'kanban';
  const view = (isDesktop && rawView === 'chat') ? 'kanban' : rawView;

  const handleCardClick = (cardId: string) => selectCard(cardId);

  const chatLevel = isHome ? 'general' : 'project';

  const contentPanel = (
    <>
      {view === 'kanban' && (
        <KanbanBoard key={id} projectId={id} onCardClick={handleCardClick} />
      )}
      {view === 'freeboard' && (
        <FreeBoard key={id} projectId={id} />
      )}
      {view === 'knowledge' && (
        <ProjectKnowledge projectId={id} />
      )}
      {view === 'projects' && isHome && (
        <ProjectList />
      )}
      {view === 'stats' && !isHome && (
        <ProjectStats />
      )}
    </>
  );

  if (isDesktop) {
    return (
      <div className={cn('project-page flex flex-col h-full w-full overflow-hidden', `project-page--${view}`)}>
        <div id="board-header-slot" />
        <div ref={containerRef} className="flex flex-row flex-1 overflow-hidden">
          <div style={{ width: `${chatPct}%` }} className="min-w-70 flex flex-col">
            <ChatWindow
              tabId={id}
              chatLevel={chatLevel}
              projectId={isHome ? undefined : id}
              className="flex-1"
            />
          </div>
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

  // Mobile: single-view
  return (
    <div className={cn('project-page flex flex-col h-full w-full overflow-hidden', `project-page--${view}`)}>
      {view === 'chat' && (
        <div className="chat-view flex flex-col h-full">
          <ChatWindow
            tabId={id}
            chatLevel={chatLevel}
            projectId={isHome ? undefined : id}
            className="flex-1"
          />
        </div>
      )}
      {contentPanel}
    </div>
  );
}
