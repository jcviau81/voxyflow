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
import { useEffect } from 'react';
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

  // Desktop: split layout — chat left (30%) + content right (70%)
  if (isDesktop) {
    return (
      <div className={cn('main-page flex flex-col h-full w-full overflow-hidden', `main-page--${view}`)}>
        {/* BoardHeader portals here (rendered by KanbanBoard/FreeBoard) */}
        <div id="board-header-slot" />
        <div className="flex flex-row flex-1 overflow-hidden">
          <div className="w-[40%] min-w-[280px] border-r border-border flex flex-col">
            <ChatWindow
              tabId={SYSTEM_PROJECT_ID}
              chatLevel="general"
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
