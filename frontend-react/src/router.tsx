/**
 * Application router — matches the navigation model of the vanilla frontend.
 *
 * ViewMode in the vanilla app: 'chat' | 'kanban' | 'freeboard' | 'projects' |
 * 'settings' | 'stats' | 'roadmap' | 'wiki' | 'sprint' | 'docs' | 'knowledge'
 *
 * Route mapping:
 *   /               → Main tab (chat + kanban + freeboard accessible via tab state)
 *   /project/:id    → Project tab (kanban/chat/stats/roadmap/wiki/sprint/docs/knowledge)
 *   /settings       → Settings page
 */
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/ProtectedRoute';

import { SettingsPage } from './components/Settings/SettingsPage';

// Placeholder page components — replaced as migration progresses.
function MainPage() {
  return <div className="p-8 text-foreground">Main — Chat / Kanban / FreeBoard (coming soon)</div>;
}

function ProjectPage() {
  return <div className="p-8 text-foreground">Project view (coming soon)</div>;
}

function NotFound() {
  return <Navigate to="/" replace />;
}

export const router = createBrowserRouter([
  {
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <MainPage /> },
      { path: 'project/:id', element: <ProjectPage /> },
      { path: 'settings', element: <SettingsPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);
