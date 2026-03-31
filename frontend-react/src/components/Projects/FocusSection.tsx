import { useState, useEffect } from 'react';

interface FocusAnalytics {
  total_sessions: number;
  total_minutes: number;
  completed_sessions: number;
  avg_session_minutes: number;
  by_card: { card_id: string; title: string; sessions: number; minutes: number }[];
  by_day: { date: string; sessions: number; minutes: number }[];
}

interface FocusSectionProps {
  projectId: string;
  /** Lifted so StatsGrid's "Focus Time" card can show a summary */
  onAnalyticsLoaded?: (analytics: FocusAnalytics | null) => void;
}

export function FocusSection({ projectId, onAnalyticsLoaded }: FocusSectionProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<FocusAnalytics | null>(null);

  useEffect(() => {
    loadAnalytics();
  }, [projectId]);

  async function loadAnalytics() {
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/focus`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const analytics = await resp.json() as FocusAnalytics;
      setData(analytics);
      onAnalyticsLoaded?.(analytics);
    } catch (err) {
      console.error('[FocusAnalytics] load failed:', err);
      onAnalyticsLoaded?.(null);
    } finally {
      setLoading(false);
    }
  }

  const weeklyMinutes = data ? data.by_day.reduce((acc, d) => acc + d.minutes, 0) : 0;
  const wHours = Math.floor(weeklyMinutes / 60);
  const wMins = weeklyMinutes % 60;

  return (
    <div className="focus-analytics-section">
      <h3 className="focus-analytics-title">⏱ Focus Analytics</h3>

      <div className="focus-analytics-controls">
        <button
          className={`focus-analytics-btn${loading ? ' loading' : ''}`}
          disabled={loading}
          onClick={loadAnalytics}
        >
          {loading ? '⏳ Loading…' : '🔄 Refresh'}
        </button>
      </div>

      {!data ? (
        <div className="focus-analytics-hint">
          Start Focus Mode on a card to track your Pomodoro sessions.
        </div>
      ) : (
        <>
          {/* Summary row */}
          <div className="focus-analytics-summary">
            <div className="focus-stat-box">
              <div className="focus-stat-value">
                {wHours > 0 ? `${wHours}h ${wMins}m` : `${wMins}m`}
              </div>
              <div className="focus-stat-label">This week</div>
            </div>
            <div className="focus-stat-box">
              <div className="focus-stat-value">{data.completed_sessions}</div>
              <div className="focus-stat-label">Completed</div>
            </div>
            <div className="focus-stat-box">
              <div className="focus-stat-value">{data.total_sessions - data.completed_sessions}</div>
              <div className="focus-stat-label">Interrupted</div>
            </div>
            <div className="focus-stat-box">
              <div className="focus-stat-value">{data.avg_session_minutes}m</div>
              <div className="focus-stat-label">Avg session</div>
            </div>
          </div>

          {/* Most focused card */}
          {data.by_card.length > 0 && (
            <div className="focus-top-card">
              <span className="focus-top-card-icon">🏆</span>
              <span className="focus-top-card-text">
                Most focused: &quot;{data.by_card[0].title}&quot; — {data.by_card[0].minutes}m across{' '}
                {data.by_card[0].sessions} session{data.by_card[0].sessions !== 1 ? 's' : ''}
              </span>
            </div>
          )}

          {/* Day-by-day bar chart */}
          {data.by_day.length > 0 && (
            <>
              <div className="focus-chart-label">Last 7 days (minutes in focus)</div>
              <div className="focus-day-chart">
                {(() => {
                  const maxMinutes = Math.max(...data.by_day.map(d => d.minutes), 1);
                  return data.by_day.map((day, i) => {
                    const heightPct = Math.round((day.minutes / maxMinutes) * 100);
                    const dayLabel = new Date(day.date + 'T00:00:00')
                      .toLocaleDateString('en', { weekday: 'short' })
                      .slice(0, 1);
                    return (
                      <div key={i} className="focus-day-bar-wrap">
                        <div className="focus-day-min-label">
                          {day.minutes > 0 ? `${day.minutes}m` : ''}
                        </div>
                        <div className="focus-day-bar-container">
                          <div
                            className={`focus-day-bar${day.minutes > 0 ? ' focus-day-bar--active' : ''}`}
                            style={{ height: `${Math.max(heightPct, day.minutes > 0 ? 4 : 0)}%` }}
                            title={`${day.minutes}m (${day.sessions} session${day.sessions !== 1 ? 's' : ''})`}
                          />
                        </div>
                        <div className="focus-day-label">{dayLabel}</div>
                      </div>
                    );
                  });
                })()}
              </div>
            </>
          )}

          {/* Per-card breakdown (top 5) */}
          {data.by_card.length > 0 && (
            <>
              <div className="focus-card-breakdown-title">Focus by card</div>
              <div className="focus-card-breakdown">
                {(() => {
                  const maxCardMin = Math.max(...data.by_card.map(c => c.minutes), 1);
                  return data.by_card.slice(0, 5).map((c) => (
                    <div key={c.card_id} className="focus-card-row">
                      <div className="focus-card-row-label" title={c.title}>{c.title}</div>
                      <div className="focus-card-row-track">
                        <div
                          className="focus-card-row-fill"
                          style={{ width: `${Math.round((c.minutes / maxCardMin) * 100)}%` }}
                        />
                      </div>
                      <div className="focus-card-row-stat">{c.minutes}m</div>
                    </div>
                  ));
                })()}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

export type { FocusAnalytics };
