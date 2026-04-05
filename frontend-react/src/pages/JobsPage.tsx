/**
 * JobsPage — Standalone Scheduler / Cron Jobs page.
 */

import { useOutletContext } from 'react-router-dom';
import { JobsPanel } from '../components/Settings/JobsPanel';
import { PageHeader } from '../components/layout/PageHeader';

export function JobsPage() {
  const { sidebarToggle } = useOutletContext<{ sidebarToggle: () => void }>();

  return (
    <div className="jobs-page flex flex-col h-full overflow-hidden" data-testid="jobs-page">
      <PageHeader title="Scheduler" onSidebarToggle={sidebarToggle} />
      <div className="flex-1 overflow-y-auto">
        <JobsPanel />
      </div>
    </div>
  );
}
