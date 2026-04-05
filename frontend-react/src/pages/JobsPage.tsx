/**
 * JobsPage — Standalone Scheduler / Cron Jobs page.
 *
 * Accessible via /jobs route and the sidebar "Jobs" nav item.
 * Renders the full JobsPanel in a page layout matching other top-level pages.
 */

import { JobsPanel } from '../components/Settings/JobsPanel';

export function JobsPage() {
  return (
    <div className="jobs-page flex flex-col h-full overflow-hidden" data-testid="jobs-page">
      {/* Page header */}
      <div className="jobs-page-header flex items-center gap-3 px-6 py-4 border-b border-border shrink-0">
        <div>
          <h1 className="text-lg font-semibold">Scheduler</h1>
          <p className="text-sm text-muted-foreground">Manage scheduled jobs and automated tasks</p>
        </div>
      </div>

      {/* Panel content */}
      <div className="flex-1 overflow-y-auto">
        <JobsPanel />
      </div>
    </div>
  );
}
