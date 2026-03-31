import { useState } from 'react';
import { Target, Loader2, CheckCircle2, MessageSquare } from 'lucide-react';
import type { Card } from '../../types';

interface PriorityData {
  ordered_cards: { card_id: string; title: string; score: number; reasoning: string }[];
  summary: string;
}

interface PrioritySectionProps {
  projectId: string;
  cards: Card[];
}

const RANK_COLORS = [
  { bg: 'rgba(251, 191, 36, 0.2)',  text: '#fbbf24' }, // 1st — gold
  { bg: 'rgba(156, 163, 175, 0.2)', text: '#9ca3af' }, // 2nd — silver
  { bg: 'rgba(180, 83, 9, 0.2)',    text: '#d97706' }, // 3rd — bronze
];

function scoreColor(score: number): string {
  if (score >= 70) return '#4ade80';
  if (score >= 40) return '#fbbf24';
  return '#60a5fa';
}

export function PrioritySection({ projectId, cards }: PrioritySectionProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PriorityData | null>(null);
  const [applying, setApplying] = useState(false);

  async function analyzePriority() {
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/prioritize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setData(await resp.json() as PriorityData);
    } catch (err) {
      console.error('[Priority] analysis failed:', err);
      setData({ ordered_cards: [], summary: '⚠️ Failed to analyze priorities. Please try again.' });
    } finally {
      setLoading(false);
    }
  }

  async function applyToKanban() {
    if (!data || !data.ordered_cards.length) return;
    setApplying(true);

    const statusOrder: Record<string, string[]> = {};
    for (const item of data.ordered_cards) {
      const card = cards.find(c => c.id === item.card_id);
      if (!card) continue;
      if (!statusOrder[card.status]) statusOrder[card.status] = [];
      statusOrder[card.status].push(item.card_id);
    }

    for (const [, cardIds] of Object.entries(statusOrder)) {
      await Promise.all(
        cardIds.map((id, pos) =>
          fetch(`/api/cards/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ position: pos }),
          }).catch(err => console.warn(`[Priority] Failed to update card ${id}:`, err))
        )
      );
    }

    setApplying(false);
  }

  return (
    <div className="bg-card border border-border rounded-xl px-6 py-5 flex flex-col gap-4">
      <h3 className="flex items-center gap-2 text-base font-bold text-foreground m-0"><Target size={16} /> Smart Priority</h3>

      <div className="flex items-center gap-2.5 flex-wrap">
        <button
          className="flex items-center gap-1.5 border-none rounded-lg px-4 py-2 text-sm font-semibold text-white cursor-pointer transition-opacity hover:opacity-85 disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ background: 'linear-gradient(135deg, #7c3aed, #a855f7)' }}
          disabled={loading}
          onClick={analyzePriority}
        >
          {loading ? <><Loader2 size={14} className="animate-spin" /> Analyzing…</> : <><Target size={14} /> Analyze Priority</>}
        </button>

        {data && data.ordered_cards.length > 0 && (
          <button
            className="flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold cursor-pointer transition-colors hover:bg-[rgba(74,222,128,0.2)]"
            style={{
              background: 'rgba(74, 222, 128, 0.12)',
              color: '#4ade80',
              border: '1px solid rgba(74, 222, 128, 0.3)',
            }}
            disabled={applying}
            onClick={applyToKanban}
          >
            {applying
              ? <><Loader2 size={14} className="animate-spin" /> Applying…</>
              : <><CheckCircle2 size={14} /> Apply to Kanban</>
            }
          </button>
        )}
      </div>

      {data && (
        <div className="flex flex-col gap-3">
          {data.summary && (
            <div
              className="text-sm text-muted-foreground italic px-3 py-2 rounded"
              style={{
                background: 'rgba(124, 58, 237, 0.08)',
                borderLeft: '3px solid #7c3aed',
              }}
            >
              {data.summary}
            </div>
          )}

          {data.ordered_cards.length === 0 ? (
            <div className="text-sm font-semibold text-center py-4" style={{ color: '#4ade80' }}>
              🎉 All cards are done — nothing to prioritize!
            </div>
          ) : (
            <ol className="list-none m-0 p-0 flex flex-col gap-2.5">
              {data.ordered_cards.map((item, i) => {
                const rankStyle = RANK_COLORS[i] ?? { bg: 'rgba(124, 58, 237, 0.2)', text: '#a78bfa' };
                return (
                  <li
                    key={item.card_id}
                    className="flex items-start gap-3 px-3.5 py-3 rounded-lg border border-border transition-colors"
                    style={{ background: 'var(--color-bg-hover)' }}
                  >
                    <span
                      className="shrink-0 w-7 h-7 rounded-full text-[0.82rem] font-extrabold flex items-center justify-center mt-0.5"
                      style={{ background: rankStyle.bg, color: rankStyle.text }}
                    >
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                      <div className="text-sm font-semibold text-foreground truncate">{item.title}</div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${item.score}%`, background: scoreColor(item.score) }}
                          />
                        </div>
                        <span className="text-[0.8125rem] text-muted-foreground tabular-nums w-12 text-right shrink-0">
                          {item.score}/100
                        </span>
                      </div>
                      {item.reasoning && i < 3 && (
                        <div className="flex items-start gap-1 text-[0.8125rem] text-muted-foreground italic leading-[1.45] pt-1">
                          <MessageSquare size={11} className="shrink-0 mt-[2px]" /> {item.reasoning}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
