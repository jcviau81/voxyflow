import { useCallback } from 'react';
import { Lightbulb, Bot, X } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useCardStore } from '../../stores/useCardStore';
import type { CardSuggestion } from '../../contexts/ChatProvider';

interface OpportunityCardProps {
  opp: CardSuggestion;
  onAccept: (id: string) => void;
  onDismiss: (id: string) => void;
}

function OpportunityCard({ opp, onAccept, onDismiss }: OpportunityCardProps) {
  return (
    <div className="bg-muted/50 rounded-lg border border-border p-3">
      <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1 uppercase tracking-wide font-medium">
        <Bot size={11} /> {opp.agentName || 'Ember'}
      </div>
      <div className="text-sm font-semibold text-foreground mb-1 leading-tight">{opp.title}</div>
      {opp.description && (
        <div className="text-xs text-muted-foreground mb-2.5 leading-relaxed">{opp.description}</div>
      )}
      <div className="flex gap-1.5">
        <button
          className="flex-1 px-3 py-1.5 bg-primary text-primary-foreground rounded text-xs font-semibold cursor-pointer transition-all hover:-translate-y-px hover:shadow-md"
          onClick={() => onAccept(opp.id)}
        >
          Create Card
        </button>
        <button
          className="flex items-center justify-center px-2 py-1.5 bg-transparent text-muted-foreground border border-border rounded text-xs cursor-pointer transition-all hover:text-red-400 hover:border-red-400/30 hover:bg-red-400/5"
          onClick={() => onDismiss(opp.id)}
        >
          <X size={12} />
        </button>
      </div>
    </div>
  );
}

export interface OpportunitiesPanelProps {
  opportunities: CardSuggestion[];
  onAccepted: (id: string) => void;
  onDismissed: (id: string) => void;
  onClose: () => void;
}

export function OpportunitiesPanel({
  opportunities,
  onAccepted,
  onDismissed,
  onClose,
}: OpportunitiesPanelProps) {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const selectCard = useProjectStore((s) => s.selectCard);
  const addCard = useCardStore((s) => s.addCard);

  const handleAccept = useCallback(
    (id: string) => {
      const opp = opportunities.find((o) => o.id === id);
      if (opp && currentProjectId) {
        const card = addCard({
          projectId: currentProjectId,
          title: opp.title,
          description: opp.description,
          status: 'idea',
          agentType: opp.agentType,
          priority: 0,
          dependencies: [],
          tags: [],
        });
        selectCard(card.id);
      }
      onAccepted(id);
    },
    [opportunities, currentProjectId, addCard, selectCard, onAccepted],
  );

  return (
    <div className="flex flex-col h-full bg-secondary overflow-hidden" data-testid="opportunities-panel">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground"><Lightbulb size={15} /> Opportunities</span>
          {opportunities.length > 0 && (
            <span className="bg-primary text-primary-foreground text-[10px] font-bold px-1.5 rounded-full min-w-[16px] text-center">
              {opportunities.length}
            </span>
          )}
        </div>
        <button
          className="flex items-center justify-center w-7 h-7 rounded text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
          title="Close"
          onClick={onClose}
        >
          <X size={15} />
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-3">
        {opportunities.length === 0 ? (
          <div className="text-xs text-muted-foreground text-center py-10 px-4 leading-relaxed">
            No suggestions yet. Start chatting!
          </div>
        ) : (
          <div className="flex flex-col gap-2.5">
            {opportunities.map((opp) => (
              <OpportunityCard
                key={opp.id}
                opp={opp}
                onAccept={handleAccept}
                onDismiss={onDismissed}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
