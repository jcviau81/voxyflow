import { X } from 'lucide-react';
import type { Card } from '../../types';
import { useCardStore } from '../../stores/useCardStore';

interface DependenciesSectionProps {
  card: Card;
  projectCards: Card[];
  onAdd: (depId: string) => void;
  onRemove: (depId: string) => void;
}

export function DependenciesSection({ card, projectCards, onAdd, onRemove }: DependenciesSectionProps) {
  const getCard = useCardStore((s) => s.getCard);

  const otherCards = projectCards.filter((c) => c.id !== card.id);

  return (
    <div className="space-y-2">
      {/* Existing dependency chips */}
      {card.dependencies.length === 0 ? (
        <span className="text-xs text-muted-foreground/60">No dependencies</span>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {card.dependencies.map((depId) => {
            const dep = getCard(depId);
            return (
              <span
                key={depId}
                className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
              >
                {dep ? (
                  <>
                    {dep.status === 'done' ? '✅' : '⏳'} {dep.title}
                  </>
                ) : (
                  depId
                )}
                <button
                  type="button"
                  onClick={() => onRemove(depId)}
                  title="Remove dependency"
                  className="hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}

      {/* Add dependency dropdown */}
      {otherCards.length > 0 ? (
        <select
          className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none"
          value=""
          onChange={(e) => {
            if (e.target.value) onAdd(e.target.value);
          }}
        >
          <option value="" disabled>
            + Add dependency...
          </option>
          {otherCards.map((c) => (
            <option key={c.id} value={c.id} disabled={card.dependencies.includes(c.id)}>
              {c.status === 'done' ? '✅' : '⏳'} {c.title}
            </option>
          ))}
        </select>
      ) : (
        <span className="text-xs text-muted-foreground/60">No other cards in this project</span>
      )}
    </div>
  );
}
