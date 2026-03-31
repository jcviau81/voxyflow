import { useState } from 'react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useNotificationStore } from '../../stores/useNotificationStore';
import { useCards } from '../../hooks/api/useCards';
import { StatsGrid } from './StatsGrid';
import { StandupSection } from './StandupSection';
import { BriefSection } from './BriefSection';
import { HealthSection } from './HealthSection';
import { PrioritySection } from './PrioritySection';
import { FocusSection, type FocusAnalytics } from './FocusSection';

export function ProjectStats() {
  const currentProjectId = useProjectStore(s => s.currentProjectId);
  const project = useProjectStore(s => s.getActiveProject());
  // Access the raw array reference (stable) — slicing inside the selector creates
  // a new reference every call, causing Zustand to loop infinitely.
  const rawActivities = useNotificationStore(s =>
    currentProjectId ? s.activities[currentProjectId] : null
  );
  const activities = rawActivities?.slice(0, 50) ?? [];

  const { data: cards = [] } = useCards(currentProjectId ?? '');

  const [focusAnalytics, setFocusAnalytics] = useState<FocusAnalytics | null>(null);

  if (!currentProjectId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No project selected.
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

      <StandupSection projectId={currentProjectId} />

      <BriefSection
        projectId={currentProjectId}
        projectName={project?.name ?? 'project'}
      />

      <HealthSection projectId={currentProjectId} />

      <PrioritySection projectId={currentProjectId} cards={cards} />

      <FocusSection
        projectId={currentProjectId}
        onAnalyticsLoaded={setFocusAnalytics}
      />
    </div>
  );
}
