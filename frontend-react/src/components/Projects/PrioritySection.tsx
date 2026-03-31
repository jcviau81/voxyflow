import { useState } from 'react';
import type { Card } from '../../types';

interface PriorityData {
  ordered_cards: { card_id: string; title: string; score: number; reasoning: string }[];
  summary: string;
}

interface PrioritySectionProps {
  projectId: string;
  cards: Card[];
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

    // Group ordered cards by status, preserving priority order within each column
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

  function scoreColor(score: number): string {
    if (score >= 70) return '#4ade80';
    if (score >= 40) return '#fbbf24';
    return '#60a5fa';
  }

  return (
    <div className="priority-section">
      <h3 className="priority-section-title">🎯 Smart Priority</h3>

      <div className="priority-controls">
        <button
          className={`priority-analyze-btn${loading ? ' loading' : ''}`}
          disabled={loading}
          onClick={analyzePriority}
        >
          {loading ? '⏳ Analyzing…' : '🎯 Analyze Priority'}
        </button>

        {data && data.ordered_cards.length > 0 && (
          <button
            className="priority-apply-btn"
            disabled={applying}
            onClick={applyToKanban}
          >
            {applying ? '⏳ Applying…' : '✅ Apply to Kanban'}
          </button>
        )}
      </div>

      {data && (
        <div className="priority-card">
          {data.summary && (
            <div className="priority-summary">{data.summary}</div>
          )}

          {data.ordered_cards.length === 0 ? (
            <div className="priority-empty">🎉 All cards are done — nothing to prioritize!</div>
          ) : (
            <ol className="priority-list">
              {data.ordered_cards.map((item, i) => (
                <li key={item.card_id} className="priority-item">
                  <span className="priority-rank">{i + 1}</span>
                  <div className="priority-info">
                    <div className="priority-title">{item.title}</div>
                    <div className="priority-score-bar-wrap">
                      <div className="priority-score-bar">
                        <div
                          className="priority-score-bar-fill"
                          style={{ width: `${item.score}%`, background: scoreColor(item.score) }}
                        />
                      </div>
                      <span className="priority-score-label">{item.score}/100</span>
                    </div>
                    {item.reasoning && i < 3 && (
                      <div className="priority-reasoning">💬 {item.reasoning}</div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
