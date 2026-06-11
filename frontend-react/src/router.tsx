/**
 * Application router — matches the navigation model of the vanilla frontend.
 *
 * ViewMode in the vanilla app: 'chat' | 'kanban' | 'freeboard' | 'workspaces' |
 * 'settings' | 'stats' | 'roadmap' | 'wiki' | 'docs' | 'knowledge'
 *
 * Route mapping:
 *   /onboarding     → First-launch setup (shown when onboarding_complete is false)
 *   /               → Main tab (chat + kanban + freeboard accessible via tab state)
 *   /workspace/:id    → Workspace tab (kanban/chat/stats/roadmap/wiki/docs/knowledge)
 *   /settings       → Settings page
 */
import { Suspense } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/ProtectedRoute';
import { OnboardingGuard } from './components/OnboardingGuard';
import { PageSkeleton } from './components/ui/PageSkeleton';
import { lazyWithReload } from './lib/lazyWithReload';

import { WorkspaceList } from './components/Workspaces';
import { WorkspacePage } from './pages/WorkspacePage';

// ── Route-level code splitting ────────────────────────────────────────────────
// Heavy, rarely-first-visited pages load on demand. WorkspacePage stays eager —
// it is the landing route and lazy-loading it would only add a waterfall.
const SettingsPage = lazyWithReload(() =>
  import('./components/Settings/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);
const OnboardingPage = lazyWithReload(() =>
  import('./pages/OnboardingPage').then((m) => ({ default: m.OnboardingPage })),
);
const JobsPage = lazyWithReload(() =>
  import('./pages/JobsPage').then((m) => ({ default: m.JobsPage })),
);

function Lazy({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<PageSkeleton />}>{children}</Suspense>;
}

function NotFound() {
  return <Navigate to="/" replace />;
}

export const router = createBrowserRouter([
  {
    path: 'onboarding',
    element: (
      <Lazy>
        <OnboardingPage />
      </Lazy>
    ),
  },
  {
    element: (
      <OnboardingGuard>
        <ProtectedRoute>
          <AppShell />
        </ProtectedRoute>
      </OnboardingGuard>
    ),
    children: [
      { index: true, element: <WorkspacePage /> },
      { path: 'workspaces', element: <WorkspaceList /> },
      { path: 'workspace/:id', element: <WorkspacePage /> },
      { path: 'settings', element: <Lazy><SettingsPage /></Lazy> },
      { path: 'jobs', element: <Lazy><JobsPage /></Lazy> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
