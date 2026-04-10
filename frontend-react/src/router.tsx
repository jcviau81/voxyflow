/**
 * Application router — matches the navigation model of the vanilla frontend.
 *
 * ViewMode in the vanilla app: 'chat' | 'kanban' | 'freeboard' | 'projects' |
 * 'settings' | 'stats' | 'roadmap' | 'wiki' | 'docs' | 'knowledge'
 *
 * Route mapping:
 *   /onboarding     → First-launch setup (shown when onboarding_complete is false)
 *   /               → Main tab (chat + kanban + freeboard accessible via tab state)
 *   /project/:id    → Project tab (kanban/chat/stats/roadmap/wiki/docs/knowledge)
 *   /settings       → Settings page
 */
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/ProtectedRoute';
import { OnboardingGuard } from './components/OnboardingGuard';

import { SettingsPage } from './components/Settings/SettingsPage';
import { ProjectList } from './components/Projects';
import { MainPage } from './pages/MainPage';
import { ProjectPage } from './pages/ProjectPage';
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
      { index: true, element: <MainPage /> },
      { path: 'projects', element: <ProjectList /> },
      { path: 'project/:id', element: <ProjectPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: 'jobs', element: <JobsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
