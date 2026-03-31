import { useState } from 'react';
import { Activity, Loader2, CheckCircle2, Lightbulb } from 'lucide-react';

interface HealthData {
  score: number;
  grade: string;
  summary: string;
  strengths: string[];
  issues: { severity: string; message: string }[];
  recommendations: string[];
  generated_at: string;
}

interface HealthSectionProps {
  projectId: string;
}

const SCORE_COLOR: Record<string, string> = {
  green:  '#4ade80',
  yellow: '#fbbf24',
  red:    '#f87171',
};

const GRADE_COLOR: Record<string, string> = {
  a: '#4ade80',
  b: '#a3e635',
  c: '#fbbf24',
  d: '#fb923c',
  f: '#f87171',
};

const ISSUE_COLOR: Record<string, string> = {
  critical: '#f87171',
  warning:  '#fbbf24',
  info:     '#60a5fa',
};

export function HealthSection({ projectId }: HealthSectionProps) {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<HealthData | null>(null);

  async function runHealthCheck() {
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      setData(await resp.json() as HealthData);
    } catch (err) {
      console.error('[HealthCheck] failed:', err);
      setData({
        score: 0,
        grade: 'F',
        summary: '⚠️ Failed to run health check. Please try again.',
        strengths: [],
        issues: [],
        recommendations: [],
        generated_at: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  }

  const scoreColor = data
    ? data.score > 80 ? SCORE_COLOR.green
    : data.score > 60 ? SCORE_COLOR.yellow
    : SCORE_COLOR.red
    : '';

  return (
    <div className="pt-2">
      <h3 className="flex items-center gap-2 text-base font-bold text-foreground mb-3.5"><Activity size={16} /> Health Check</h3>

      <div className="flex items-center gap-3 mb-3.5">
        <button
          className="flex items-center gap-1.5 border-none rounded-lg px-5 py-2 text-sm font-semibold text-white cursor-pointer transition-opacity hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ background: 'linear-gradient(135deg, #2ecc71 0%, #27ae60 100%)' }}
          disabled={loading}
          onClick={runHealthCheck}
        >
          {loading ? <><Loader2 size={14} className="animate-spin" /> Analysing…</> : <><Activity size={14} /> Run Health Check</>}
        </button>
      </div>

      {data && (
        <div className="bg-card border border-border rounded-lg p-5 flex flex-col gap-4">
          <div className="text-[0.8125rem] text-muted-foreground">
            Analysed {new Date(data.generated_at).toLocaleString()}
          </div>

          <div className="flex items-center gap-4">
            <div
              className="text-[3.5rem] font-extrabold leading-none tracking-[-2px]"
              style={{ color: scoreColor }}
            >
              {data.score}
            </div>
            <div
              className="text-[1.8rem] font-extrabold px-4 py-1 rounded-lg leading-none border-2"
              style={{
                color: GRADE_COLOR[data.grade.toLowerCase()] ?? '#9ca3af',
                borderColor: GRADE_COLOR[data.grade.toLowerCase()] ?? '#9ca3af',
              }}
            >
              {data.grade}
            </div>
          </div>

          <p className="text-sm text-muted-foreground leading-relaxed italic">{data.summary}</p>

          {data.strengths.length > 0 && (
            <div>
              <div className="text-[0.8125rem] font-bold uppercase tracking-[0.06em] text-muted-foreground mb-2">
                Strengths
              </div>
              <ul className="flex flex-col gap-1.5 list-none p-0 m-0">
                {data.strengths.map((s, i) => (
                  <li key={i} className="flex items-center gap-1.5 text-sm" style={{ color: '#4ade80' }}><CheckCircle2 size={13} /> {s}</li>
                ))}
              </ul>
            </div>
          )}

          {data.issues.length > 0 && (
            <div>
              <div className="text-[0.8125rem] font-bold uppercase tracking-[0.06em] text-muted-foreground mb-2">
                Issues
              </div>
              <ul className="flex flex-col gap-1.5 list-none p-0 m-0">
                {data.issues.map((issue, i) => {
                  return (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 text-sm"
                      style={{ color: ISSUE_COLOR[issue.severity] ?? '#9ca3af' }}
                    >
                      <span
                        className="mt-[3px] shrink-0 w-2 h-2 rounded-full"
                        style={{ background: ISSUE_COLOR[issue.severity] ?? '#9ca3af' }}
                      />
                      {issue.message}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {data.recommendations.length > 0 && (
            <div>
              <div className="text-[0.8125rem] font-bold uppercase tracking-[0.06em] text-muted-foreground mb-2">
                Recommendations
              </div>
              <ul className="flex flex-col gap-1.5 list-none p-0 m-0">
                {data.recommendations.map((rec, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-sm text-muted-foreground"><Lightbulb size={13} className="shrink-0 mt-[1px]" /> {rec}</li>
                ))}
              </ul>
            </div>
          )}

          {data.issues.length === 0 && (
            <div className="flex items-center gap-1.5 text-sm font-semibold" style={{ color: '#4ade80' }}>
              <CheckCircle2 size={14} /> No issues detected — project looks healthy!
            </div>
          )}
        </div>
      )}
    </div>
  );
}
