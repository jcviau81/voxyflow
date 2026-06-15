import type { Card } from '../types';

/** Active board filter criteria. A null/empty field means "no filter on that dimension". */
export interface CardFilters {
  query?: string;
  priorityFilter?: number | null;
  agentFilter?: string | null;
  tagFilter?: string | null;
}

/**
 * Returns true when a card satisfies all active filters.
 * Shared between KanbanBoard (filter match count) and KanbanCard (visibility).
 * Matching semantics must stay identical across both call sites.
 */
export function matchesCard(card: Card, filters: CardFilters): boolean {
  const { query, priorityFilter = null, agentFilter = null, tagFilter = null } = filters;
  if (query && !card.title.toLowerCase().includes(query.toLowerCase())) return false;
  if (priorityFilter !== null && card.priority !== priorityFilter) return false;
  if (agentFilter && (card.agentType || 'general') !== agentFilter) return false;
  if (tagFilter && !card.tags.some((t) => t.toLowerCase() === tagFilter.toLowerCase())) return false;
  return true;
}
