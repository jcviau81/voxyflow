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
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/ProtectedRoute';
import { OnboardingGuard } from './components/OnboardingGuard';

import { SettingsPage } from './components/Settings/SettingsPage';
import { WorkspaceList } from './components/Workspaces';
import { WorkspacePage } from './pages/WorkspacePage';
import { OnboardingPage } from './pages/OnboardingPage';
import { JobsPage } from './pages/JobsPage';

function NotFound() {
  return <Navigate to="/" replace />;
}

export const router = createBrowserRouter([
  {
    path: 'onboarding',
    element: <OnboardingPage />,
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
      { path: 'settings', element: <SettingsPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
