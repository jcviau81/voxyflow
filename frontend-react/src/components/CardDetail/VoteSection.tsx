import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useVoteCard } from '../../hooks/api/useCards';

interface VoteSectionProps {
  cardId: string;
  votes: number;
}

export function VoteSection({ cardId, votes }: VoteSectionProps) {
  const storageKey = `voxy_voted_${cardId}`;
  const [voted, setVoted] = useState(() => localStorage.getItem(storageKey) === 'true');
  const [count, setCount] = useState(votes);
  const voteMutation = useVoteCard();

  const handleVote = useCallback(async () => {
    const wasVoted = localStorage.getItem(storageKey) === 'true';
    voteMutation.mutate(
      { cardId, unvote: wasVoted },
      {
        onSuccess: (data) => {
          const nowVoted = !wasVoted;
          if (nowVoted) {
            localStorage.setItem(storageKey, 'true');
          } else {
            localStorage.removeItem(storageKey);
          }
          setVoted(nowVoted);
          setCount(data.votes);
        },
      },
    );
  }, [cardId, storageKey, voteMutation]);

  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-muted-foreground">
        ▲ {count} vote{count !== 1 ? 's' : ''}
      </span>
      <button
        type="button"
        onClick={handleVote}
        disabled={voteMutation.isPending}
        className={cn(
          'rounded-md border px-2.5 py-1 text-xs font-medium transition-colors',
          voted
            ? 'border-amber-500/40 bg-amber-500/20 text-amber-300'
            : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted',
        )}
      >
        {voted ? 'Un-vote' : 'Vote ▲'}
      </button>
    </div>
  );
}
