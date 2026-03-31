/**
 * SettingsPage — settings layout shell with sidebar navigation between panels.
 *
 * Matches the section structure of the vanilla SettingsPage.ts (2420 lines).
 * Only the Appearance panel is implemented in step 14a; the rest are placeholders
 * that will be filled in steps 14b–14d.
 *
 * Vanilla sections:
 *   Appearance · Personality · Models · GitHub · Voice · Workspace · Connection · Data · Jobs · About
 */

import { useState } from 'react';
import { Palette, Cpu, Mic, GitBranch, FolderOpen, Database, Info, Clock } from 'lucide-react';
import { cn } from '../../lib/utils';
import { AppearancePanel } from './AppearancePanel';
import { ModelPanel } from './ModelPanel';
import { VoicePanel } from './VoicePanel';
import { GitHubPanel } from './GitHubPanel';
import { WorkspacePanel } from './WorkspacePanel';
import { DataPanel } from './DataPanel';
import { AboutPanel } from './AboutPanel';
import { JobsPanel } from './JobsPanel';

// ── Panel registry ─────────────────────────────────────────────────────────

type PanelId =
  | 'appearance'
  | 'models'
  | 'voice'
  | 'github'
  | 'workspace'
  | 'data'
  | 'jobs'
  | 'about';

interface NavItem {
  id: PanelId;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'models',     label: 'Models',     icon: Cpu },
  { id: 'voice',      label: 'Voice & STT', icon: Mic },
  { id: 'github',     label: 'GitHub',     icon: GitBranch },
  { id: 'workspace',  label: 'Workspace',  icon: FolderOpen },
  { id: 'data',       label: 'Data',       icon: Database },
  { id: 'jobs',       label: 'Jobs',       icon: Clock },
  { id: 'about',      label: 'About',      icon: Info },
];

// ── Panel renderer ─────────────────────────────────────────────────────────

function renderPanel(id: PanelId) {
  switch (id) {
    case 'appearance': return <AppearancePanel />;
    case 'models':     return <ModelPanel />;
    case 'voice':      return <VoicePanel />;
    case 'github':     return <GitHubPanel />;
    case 'workspace':  return <WorkspacePanel />;
    case 'data':       return <DataPanel />;
    case 'jobs':       return <JobsPanel />;
    case 'about':      return <AboutPanel />;
  }
}

// ── SettingsPage ───────────────────────────────────────────────────────────

export function SettingsPage() {
  const [activePanel, setActivePanel] = useState<PanelId>('appearance');

  return (
    <div className="settings-page flex h-full overflow-hidden" data-testid="settings-page">

      {/* ── Sidebar nav ── */}
      <aside className="settings-nav w-48 shrink-0 border-r border-border bg-muted/20 overflow-y-auto">
        <div className="px-4 pt-5 pb-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Settings
          </h2>
        </div>
        <nav>
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActivePanel(id)}
              className={cn(
                'settings-nav-item w-full flex items-center gap-2.5 px-4 py-2 text-sm text-left transition-colors',
                'hover:bg-accent hover:text-accent-foreground',
                activePanel === id
                  ? 'bg-accent text-accent-foreground font-medium'
                  : 'text-muted-foreground',
              )}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </nav>
      </aside>

      {/* ── Panel content ── */}
      <main className="settings-panel flex-1 overflow-y-auto">
        {renderPanel(activePanel)}
      </main>

    </div>
  );
}
