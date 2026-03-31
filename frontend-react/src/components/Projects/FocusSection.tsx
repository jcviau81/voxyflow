import { useState, useEffect } from 'react';
import { Timer, Loader2, RefreshCw, Trophy } from 'lucide-react';

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
    <div
      className="border border-border rounded-xl px-6 py-5"
      style={{ background: 'var(--color-surface-elevated, #1e1e2e)' }}
    >
      <h3 className="flex items-center gap-2 text-[1.05rem] font-bold text-foreground mb-3.5"><Timer size={16} /> Focus Analytics</h3>

      <div className="mb-4">
        <button
          className="flex items-center gap-1.5 bg-white/[0.06] border border-white/[0.12] rounded-md text-muted-foreground text-sm px-3 py-1 cursor-pointer transition-colors hover:bg-white/[0.1] hover:text-foreground disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={loading}
          onClick={loadAnalytics}
        >
          {loading
            ? <><Loader2 size={13} className="animate-spin" /> Loading…</>
            : <><RefreshCw size={13} /> Refresh</>
          }
        </button>
      </div>

      {!data ? (
        <div className="text-sm text-muted-foreground italic">
          Start Focus Mode on a card to track your Pomodoro sessions.
        </div>
      ) : (
        <>
          {/* Summary row */}
          <div className="flex gap-3 flex-wrap mb-4">
            {[
              { value: wHours > 0 ? `${wHours}h ${wMins}m` : `${wMins}m`, label: 'This week' },
              { value: data.completed_sessions, label: 'Completed' },
              { value: data.total_sessions - data.completed_sessions, label: 'Interrupted' },
              { value: `${data.avg_session_minutes}m`, label: 'Avg session' },
            ].map(({ value, label }) => (
              <div
                key={label}
                className="bg-white/[0.05] border border-white/[0.07] rounded-lg px-3.5 py-2.5 min-w-[80px] flex-1 text-center"
              >
                <div
                  className="text-[1.2rem] font-bold leading-none mb-1"
                  style={{ color: 'var(--color-accent)' }}
                >
                  {value}
                </div>
                <div className="text-[0.8125rem] text-muted-foreground uppercase tracking-[0.03em]">
                  {label}
                </div>
              </div>
            ))}
          </div>

          {/* Most focused card */}
          {data.by_card.length > 0 && (
            <div
              className="flex items-start gap-2 rounded-lg p-3 mb-4 text-sm text-foreground"
              style={{
                background: 'rgba(167, 139, 250, 0.08)',
                border: '1px solid rgba(167, 139, 250, 0.2)',
              }}
            >
              <Trophy size={15} className="shrink-0 text-yellow-400" />
              <span className="leading-[1.4]">
                Most focused: &quot;{data.by_card[0].title}&quot; — {data.by_card[0].minutes}m across{' '}
                {data.by_card[0].sessions} session{data.by_card[0].sessions !== 1 ? 's' : ''}
              </span>
            </div>
          )}

          {/* Day-by-day bar chart */}
          {data.by_day.length > 0 && (
            <>
              <div className="text-[0.8125rem] text-muted-foreground mb-2 uppercase tracking-[0.04em]">
                Last 7 days (minutes in focus)
              </div>
              <div className="flex gap-1.5 items-end h-[90px] mb-5 py-1">
                {(() => {
                  const maxMinutes = Math.max(...data.by_day.map(d => d.minutes), 1);
                  return data.by_day.map((day, i) => {
                    const heightPct = Math.round((day.minutes / maxMinutes) * 100);
                    const dayLabel = new Date(day.date + 'T00:00:00')
                      .toLocaleDateString('en', { weekday: 'short' })
                      .slice(0, 1);
                    return (
                      <div key={i} className="flex flex-col items-center flex-1 gap-0.5 h-full justify-end">
                        <div
                          className="text-[0.8125rem] text-muted-foreground h-[14px] leading-[14px] text-center whitespace-nowrap"
                        >
                          {day.minutes > 0 ? `${day.minutes}m` : ''}
                        </div>
                        <div className="flex items-end flex-1 w-full max-h-14">
                          <div
                            className="w-full rounded-t-[4px] transition-all duration-300"
                            style={{
                              height: `${Math.max(heightPct, day.minutes > 0 ? 4 : 0)}%`,
                              background: day.minutes > 0
                                ? 'var(--color-accent)'
                                : 'rgba(255,255,255,0.1)',
                              minHeight: 0,
                            }}
                            title={`${day.minutes}m (${day.sessions} session${day.sessions !== 1 ? 's' : ''})`}
                          />
                        </div>
                        <div className="text-[0.8125rem] text-muted-foreground text-center leading-none pt-[3px]">
                          {dayLabel}
                        </div>
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
              <div className="text-[0.8125rem] text-muted-foreground uppercase tracking-[0.04em] mb-2">
                Focus by card
              </div>
              <div className="flex flex-col gap-1.5">
                {(() => {
                  const maxCardMin = Math.max(...data.by_card.map(c => c.minutes), 1);
                  return data.by_card.slice(0, 5).map((c) => (
                    <div key={c.card_id} className="grid grid-cols-[1fr_2fr_auto] gap-2 items-center text-[0.82rem]">
                      <div className="text-foreground truncate" title={c.title}>{c.title}</div>
                      <div className="bg-white/[0.06] rounded-[3px] h-1.5 overflow-hidden">
                        <div
                          className="h-full rounded-[3px] transition-all duration-300"
                          style={{
                            width: `${Math.round((c.minutes / maxCardMin) * 100)}%`,
                            background: 'var(--color-accent)',
                          }}
                        />
                      </div>
                      <div className="text-muted-foreground text-[0.8125rem] text-right min-w-[36px]">
                        {c.minutes}m
                      </div>
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
