import { useState } from 'react';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useCards } from '../../hooks/api/useCards';
import { StatsGrid } from './StatsGrid';
import { StandupSection } from './StandupSection';
import { BriefSection } from './BriefSection';
import { HealthSection } from './HealthSection';
import { PrioritySection } from './PrioritySection';
import { FocusSection, type FocusAnalytics } from './FocusSection';

export function WorkspaceStats() {
  const currentWorkspaceId = useWorkspaceStore(s => s.currentWorkspaceId);
  const workspace = useWorkspaceStore(s => s.getActiveWorkspace());
  // Access the raw array reference (stable) — slicing inside the selector creates
  // a new reference every call, causing Zustand to loop infinitely.
  const rawActivities = useNotificationStore(s =>
    currentWorkspaceId ? s.activities[currentWorkspaceId] : null
  );
  const activities = rawActivities?.slice(0, 50) ?? [];

  const { data: cards = [] } = useCards(currentWorkspaceId ?? '');

  const [focusAnalytics, setFocusAnalytics] = useState<FocusAnalytics | null>(null);

  if (!currentWorkspaceId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No workspace selected.
      </div>
    );
  }

  return (
    <div className="p-6 h-full overflow-y-auto space-y-6">
      <StatsGrid
        cards={cards}
        activities={activities}
        focusAnalytics={focusAnalytics}
      />

      <StandupSection workspaceId={currentWorkspaceId} />

      <BriefSection
        workspaceId={currentWorkspaceId}
        workspaceName={workspace?.name ?? 'workspace'}
      />

      <HealthSection workspaceId={currentWorkspaceId} />

      <PrioritySection workspaceId={currentWorkspaceId} cards={cards} />

      <FocusSection
        workspaceId={currentWorkspaceId}
        onAnalyticsLoaded={setFocusAnalytics}
      />
    </div>
  );
}
