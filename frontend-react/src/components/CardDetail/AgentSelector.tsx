import { Bot, Search, Code2, Paintbrush, Building2, PenLine, FlaskConical, type LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { AgentInfo } from '../../types';
import { useAgents } from '../../hooks/api/useAgents';
import { AGENT_TYPE_EMOJI } from '../../lib/constants';

const AGENT_ICONS: Record<string, LucideIcon> = {
  general:    Bot,
  researcher: Search,
  coder:      Code2,
  designer:   Paintbrush,
  architect:  Building2,
  writer:     PenLine,
  qa:         FlaskConical,
};

// Fallback agents derived from AGENT_TYPE_EMOJI when API hasn't loaded yet
const FALLBACK_AGENTS: AgentInfo[] = Object.entries(AGENT_TYPE_EMOJI).map(([type, emoji]) => ({
  type,
  name: type.charAt(0).toUpperCase() + type.slice(1),
  emoji,
  description: '',
  strengths: [],
  keywords: [],
}));

interface AgentSelectorProps {
  current: string;
  onChange: (agentType: string) => void;
}

const GENERAL_AGENT: AgentInfo = {
  type: 'general',
  name: 'General',
  emoji: '',
  description: 'General-purpose agent',
  strengths: [],
  keywords: [],
};

export function AgentSelector({ current, onChange }: AgentSelectorProps) {
  const { data: agents } = useAgents();
  const base = agents && agents.length > 0 ? agents : FALLBACK_AGENTS;
  const list = base.some((a) => a.type === 'general') ? base : [GENERAL_AGENT, ...base];

  return (
    <div className="flex flex-wrap gap-1.5">
      {list.map((agent) => {
        const Icon = AGENT_ICONS[agent.type];
        return (
          <button
            key={agent.type}
            type="button"
            title={agent.description}
            onClick={() => onChange(agent.type)}
            className={cn(
              'flex items-center gap-1 rounded-md border px-2 py-1 text-xs transition-colors cursor-pointer',
              current === agent.type
                ? 'border-accent bg-accent-foreground/20 text-accent-foreground'
                : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted',
            )}
          >
            {Icon && <Icon size={11} />}
            {agent.name}
          </button>
        );
      })}
    </div>
  );
}
