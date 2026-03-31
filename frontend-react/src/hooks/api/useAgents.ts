import { useQuery } from '@tanstack/react-query';
import type { AgentInfo } from '../../types';

const API = '';

export const agentKeys = {
  all: ['agents'] as const,
};

export function useAgents() {
  return useQuery({
    queryKey: agentKeys.all,
    queryFn: async () => {
      const res = await fetch(`${API}/api/agents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<AgentInfo[]>;
    },
    staleTime: 5 * 60_000, // agents rarely change
  });
}
