import { useState } from 'react';

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

  const scoreClass = data
    ? data.score > 80 ? 'health-score--green'
    : data.score > 60 ? 'health-score--yellow'
    : 'health-score--red'
    : '';

  return (
    <div className="health-check-section">
      <h3 className="health-check-section-title">🏥 Health Check</h3>

      <div className="health-check-controls">
        <button
          className={`health-run-btn${loading ? ' loading' : ''}`}
          disabled={loading}
          onClick={runHealthCheck}
        >
          {loading ? '⏳ Analysing…' : '🏥 Run Health Check'}
        </button>
      </div>

      {data && (
        <div className="health-card">
          <div className="health-card-meta">
            Analysed {new Date(data.generated_at).toLocaleString()}
          </div>

          <div className="health-score-row">
            <div className={`health-score ${scoreClass}`}>{data.score}</div>
            <div className={`health-grade health-grade--${data.grade.toLowerCase()}`}>
              {data.grade}
            </div>
          </div>

          <p className="health-summary">{data.summary}</p>

          {data.strengths.length > 0 && (
            <div className="health-strengths">
              <div className="health-list-title">Strengths</div>
              <ul className="health-list">
                {data.strengths.map((s, i) => (
                  <li key={i} className="health-strength-item">✅ {s}</li>
                ))}
              </ul>
            </div>
          )}

          {data.issues.length > 0 && (
            <div className="health-issues">
              <div className="health-list-title">Issues</div>
              <ul className="health-list">
                {data.issues.map((issue, i) => {
                  const icon = issue.severity === 'critical' ? '🔴'
                    : issue.severity === 'warning' ? '🟡' : '🔵';
                  return (
                    <li key={i} className={`health-issue-item health-issue-item--${issue.severity}`}>
                      {icon} {issue.message}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {data.recommendations.length > 0 && (
            <div className="health-recommendations">
              <div className="health-list-title">Recommendations</div>
              <ul className="health-list">
                {data.recommendations.map((rec, i) => (
                  <li key={i} className="health-rec-item">💡 {rec}</li>
                ))}
              </ul>
            </div>
          )}

          {data.issues.length === 0 && (
            <div className="health-all-clear">
              ✅ No issues detected — project looks healthy!
            </div>
          )}
        </div>
      )}
    </div>
  );
}
