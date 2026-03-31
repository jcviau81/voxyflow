import { cn } from '@/lib/utils';
import type { AgentInfo } from '../../types';
import { useAgents } from '../../hooks/api/useAgents';
import { AGENT_TYPE_EMOJI } from '../../lib/constants';

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

export function AgentSelector({ current, onChange }: AgentSelectorProps) {
  const { data: agents } = useAgents();
  const list = agents && agents.length > 0 ? agents : FALLBACK_AGENTS;

  return (
    <div className="flex flex-wrap gap-1.5">
      {list.map((agent) => (
        <button
          key={agent.type}
          type="button"
          title={agent.description}
          onClick={() => onChange(agent.type)}
          className={cn(
            'rounded-md border px-2 py-1 text-xs transition-colors',
            current === agent.type
              ? 'border-accent bg-accent/20 text-accent-foreground'
              : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted',
          )}
        >
          {agent.emoji} {agent.name}
        </button>
      ))}
    </div>
  );
}
