import { useCallback, useEffect } from 'react';
import { Lightbulb, Bell, X, Home, Folder, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { useTabStore } from '../../stores/useTabStore';
import { useSessionStore } from '../../stores/useSessionStore';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useWS } from '../../providers/WebSocketProvider';
import type { Tab } from '../../types';

interface TabBarProps {
  opportunityCount?: number;
  onPanelToggle?: (tab: 'opportunities' | 'notifications') => void;
  onSidebarToggle?: () => void;
}

export function TabBar({ opportunityCount = 0, onPanelToggle, onSidebarToggle }: TabBarProps) {
  const navigate = useNavigate();
  const openTabs = useTabStore((s) => s.openTabs);
  const activeTab = useTabStore((s) => s.activeTab);
  const closeTab = useTabStore((s) => s.closeTab);
  const sessions = useSessionStore((s) => s.sessions);
  const closeSession = useSessionStore((s) => s.closeSession);
  const notificationUnreadCount = useNotificationStore((s) => s.notificationUnreadCount);
  const { send } = useWS();

  const handleSwitchTab = useCallback(
    (tabId: string) => {
      // Navigate only — AppShell syncs stores from URL
      if (tabId === 'main') {
        navigate('/');
      } else {
        navigate(`/project/${tabId}`);
      }
    },
    [navigate],
  );

  const handleCloseTab = useCallback(
    async (tab: Tab) => {
      const tabSessions = sessions[tab.id] ?? [];

      if (tabSessions.length > 0) {
        const confirmed = window.confirm(
          `Close ${tab.label}?\n\nThis will close ${tabSessions.length} active session${tabSessions.length > 1 ? 's' : ''} for this project.`
        );
        if (!confirmed) return;

        for (const session of tabSessions) {
          send('session:reset', { sessionId: session.chatId, tabId: tab.id });
          closeSession(tab.id, session.id);
        }
      }

      closeTab(tab.id);

      // Navigate to wherever closeTab landed
      const newActive = useTabStore.getState().activeTab;
      if (newActive === 'main') {
        navigate('/');
      } else {
        navigate(`/project/${newActive}`);
      }
    },
    [sessions, send, closeSession, closeTab, navigate]
  );


  // Keyboard shortcuts: Ctrl+Tab to cycle, Ctrl+W to close active
  useEffect(() => {
    const handleKeydown = (e: KeyboardEvent) => {
      // Ctrl+Tab: cycle to next/prev tab
      if (e.ctrlKey && e.key === 'Tab') {
        e.preventDefault();
        const currentIndex = openTabs.findIndex((t) => t.id === activeTab);
        const nextIndex = e.shiftKey
          ? (currentIndex - 1 + openTabs.length) % openTabs.length
          : (currentIndex + 1) % openTabs.length;
        handleSwitchTab(openTabs[nextIndex].id);
      }

      // Ctrl+W / Cmd+W: close current tab
      if ((e.ctrlKey || e.metaKey) && e.key === 'w') {
        const activeTabObj = openTabs.find((t) => t.id === activeTab);
        if (activeTabObj?.closable) {
          e.preventDefault();
          handleCloseTab(activeTabObj);
        }
      }
    };

    document.addEventListener('keydown', handleKeydown);
    return () => document.removeEventListener('keydown', handleKeydown);
  }, [openTabs, activeTab, handleSwitchTab, handleCloseTab]);

  return (
    <div className="tab-bar flex items-center gap-2 px-2 py-1.5 overflow-x-auto border-b border-border" data-testid="tab-bar">
      {/* Hamburger — mobile only */}
      <button
        className="md:hidden flex-shrink-0 flex items-center justify-center w-8 h-8 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer"
        onClick={onSidebarToggle}
        title="Menu"
        data-testid="hamburger"
      >
        <Menu size={18} />
      </button>

      {openTabs.map((tab) => (
        <TabItem
          key={tab.id}
          tab={tab}
          isActive={tab.id === activeTab}
          onSwitch={() => handleSwitchTab(tab.id)}
          onClose={() => handleCloseTab(tab)}
        />
      ))}

      {/* Right-side panel triggers */}
      <div className="ml-auto flex items-center gap-0.5 pl-2 flex-shrink-0">
        <PanelTrigger
          icon={<Lightbulb size={15} />}
          count={opportunityCount}
          title="Opportunities"
          onClick={() => onPanelToggle?.('opportunities')}
        />
        <PanelTrigger
          icon={<Bell size={15} />}
          count={notificationUnreadCount}
          title="Notifications"
          badge="red"
          onClick={() => onPanelToggle?.('notifications')}
        />
      </div>
    </div>
  );
}

interface PanelTriggerProps {
  icon: React.ReactNode;
  count: number;
  title: string;
  badge?: 'primary' | 'red';
  onClick?: () => void;
}

function PanelTrigger({ icon, count, title, badge = 'primary', onClick }: PanelTriggerProps) {
  return (
    <button
      className="relative flex items-center justify-center w-7 h-7 rounded text-base text-muted-foreground hover:text-foreground hover:bg-accent transition-colors flex-shrink-0 cursor-pointer"
      title={title}
      onClick={onClick}
    >
      {icon}
      {count > 0 && (
        <span
          className={cn(
            'absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-[3px]',
            'text-[9px] font-bold leading-[14px] text-center rounded-full text-white',
            badge === 'red' ? 'bg-red-500' : 'bg-primary',
          )}
        >
          {count > 99 ? '99+' : count}
        </span>
      )}
    </button>
  );
}

interface TabItemProps {
  tab: Tab;
  isActive: boolean;
  onSwitch: () => void;
  onClose: () => void;
}

function TabItem({ tab, isActive, onSwitch, onClose }: TabItemProps) {
  const handleAuxClick = (e: React.MouseEvent) => {
    if (e.button === 1 && tab.closable) {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <button
      className={cn(
        'tab group flex items-center gap-2 p-1 rounded text-sm transition-colors hover:bg-accent cursor-pointer hover:bg-accent',
        'max-w-[180px] flex-shrink-0 relative transition-colors cursor-pointer',
        isActive
          ? 'bg-background bg-accent text-foreground shadow-sm border border-border transition-colors'
          : 'text-muted-foreground hover:text-foreground hover:bg-accent'
      )}
      data-testid={`tab-${tab.id}`}
      data-tab-id={tab.id}
      onClick={onSwitch}
      onAuxClick={handleAuxClick}
    >
      {tab.id === 'main' ? (
        <Home size={13} className="flex-shrink-0" />
      ) : tab.emoji ? (
        <span className="tab-emoji flex-shrink-0 text-xs leading-none">{tab.emoji}</span>
      ) : (
        <Folder size={13} className="flex-shrink-0" />
      )}

      <span className="tab-label truncate">{tab.label}</span>

      {tab.hasNotification && (
        <span className="tab-notification flex-shrink-0 w-1.5 h-1.5 rounded-full bg-primary" />
      )}

      {tab.closable && (
        <span
          className={cn(
            'tab-close flex-shrink-0 w-4 h-4 flex items-center justify-center rounded',
            'text-xs leading-none opacity-0 group-hover:opacity-100',
            isActive && 'opacity-60',
            'hover:!opacity-100 hover:bg-destructive/20 hover:text-destructive',
            'transition-opacity'
          )}
          data-testid={`tab-close-${tab.id}`}
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
        >
          <X size={10} />
        </span>
      )}
    </button>
  );
}
