/**
 * TopBar — minimal header bar.
 *
 * Contains:
 *   - Mobile hamburger button (toggles sidebar)
 *   - Project name (emoji + name, or 'Main')
 */

import { Menu } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';

interface TopBarProps {
  onMenuClick: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const projects = useProjectStore((s) => s.projects);

  const project = currentProjectId
    ? projects.find((p) => p.id === currentProjectId)
    : undefined;
  const projectName = project
    ? `${project.emoji ? project.emoji + ' ' : ''}${project.name}`
    : 'Main';

  return (
    <header className="top-bar flex items-center gap-2 px-3 h-10 border-b border-border bg-background shrink-0">
      {/* Mobile hamburger */}
      <button
        className="p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors md:hidden"
        onClick={onMenuClick}
        aria-label="Toggle sidebar"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Project name */}
      <span className="text-sm font-medium truncate max-w-[200px]">
        {projectName}
      </span>
    </header>
  );
}
