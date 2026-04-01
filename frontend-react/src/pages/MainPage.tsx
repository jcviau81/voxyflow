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
 * for the main tab (stats, knowledge, docs, roadmap, sprint) is reset to 'chat'.
 */
import { useEffect } from 'react';
import { ChatWindow } from '../components/Chat/ChatWindow';
import { KanbanBoard } from '../components/Kanban/KanbanBoard';
import { FreeBoard } from '../components/Board/FreeBoard';
import { ProjectList } from '../components/Projects/ProjectList';
import { ProjectKnowledge } from '../components/Projects/ProjectKnowledge';
import { useViewStore } from '../stores/useViewStore';
import { useProjectStore } from '../stores/useProjectStore';
import { SYSTEM_PROJECT_ID } from '../lib/constants';
import { cn } from '../lib/utils';

const MAIN_TAB_VIEWS = new Set(['chat', 'kanban', 'freeboard', 'projects', 'knowledge']);

export function MainPage() {
  const currentView = useViewStore((s) => s.currentView);
  const setView = useViewStore((s) => s.setView);
  const selectCard = useProjectStore((s) => s.selectCard);

  // Reset to chat if a project-only view leaked into main tab
  useEffect(() => {
    if (!MAIN_TAB_VIEWS.has(currentView)) {
      setView('chat');
    }
  }, [currentView, setView]);

  const handleCardClick = (cardId: string) => {
    selectCard(cardId);
  };

  const view = MAIN_TAB_VIEWS.has(currentView) ? currentView : 'chat';

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
    </div>
  );
}
