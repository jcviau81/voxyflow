/**
 * MainPage — assembles the main-tab views (Chat, Kanban, FreeBoard, Projects).
 *
 * Mirrors the switchView logic in vanilla App.ts for the 'main' tab:
 *   - 'chat'      → ChatWindow + VoiceInput
 *   - 'kanban'    → KanbanBoard
 *   - 'freeboard' → FreeBoard
 *   - 'projects'  → ProjectList
 *
 * View state lives in useViewStore (persisted). Any view that is not valid
 * for the main tab (stats, knowledge, docs, roadmap) is reset to 'chat'.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { ChatWindow } from '../components/Chat/ChatWindow';
import { KanbanBoard } from '../components/Kanban/KanbanBoard';
import { FreeBoard } from '../components/Board/FreeBoard';
import { ProjectList } from '../components/Projects/ProjectList';
import { ProjectKnowledge } from '../components/Projects/ProjectKnowledge';
import { useViewStore } from '../stores/useViewStore';
import { useProjectStore } from '../stores/useProjectStore';
import { useIsDesktop } from '../hooks/useIsDesktop';
import { SYSTEM_PROJECT_ID } from '../lib/constants';
import { cn } from '../lib/utils';

const MAIN_TAB_VIEWS = new Set(['chat', 'kanban', 'freeboard', 'projects', 'knowledge']);

export function MainPage() {
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const selectCard = useProjectStore((s) => s.selectCard);
  const isDesktop = useIsDesktop();

  // Reset to kanban if a project-only view leaked into main tab
  useEffect(() => {
    if (!MAIN_TAB_VIEWS.has(currentView)) {
      setView('kanban');
    }
  }, [currentView, setView]);

  const handleCardClick = (cardId: string) => {
    selectCard(cardId);
  };

  // On desktop, 'chat' view falls back to 'kanban' (chat is always visible in left panel)
  const rawView = MAIN_TAB_VIEWS.has(currentView) ? currentView : 'kanban';
  const view = (isDesktop && rawView === 'chat') ? 'kanban' : rawView;

  const contentPanel = (
    <>
      {view === 'kanban' && (
        <KanbanBoard projectId={SYSTEM_PROJECT_ID} onCardClick={handleCardClick} />
      )}
      {view === 'freeboard' && (
        <FreeBoard />
      )}
      {view === 'projects' && (
        <ProjectList />
      )}
      {view === 'knowledge' && (
        <ProjectKnowledge projectId={SYSTEM_PROJECT_ID} />
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
      <div className={cn('main-page flex flex-col h-full w-full overflow-hidden', `main-page--${view}`)}>
        {/* BoardHeader portals here (rendered by KanbanBoard/FreeBoard) */}
        <div id="board-header-slot" />
        <div ref={containerRef} className="flex flex-row flex-1 overflow-hidden">
          <div style={{ width: `${chatPct}%` }} className="min-w-70 flex flex-col">
            <ChatWindow
              tabId={SYSTEM_PROJECT_ID}
              chatLevel="general"
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
    <div className={cn('main-page flex flex-col h-full w-full overflow-hidden', `main-page--${view}`)}>
      {view === 'chat' && (
        <div className="chat-view flex flex-col h-full">
          <ChatWindow
            tabId={SYSTEM_PROJECT_ID}
            chatLevel="general"
            className="flex-1"
          />
        </div>
      )}
      {contentPanel}
    </div>
  );
}
