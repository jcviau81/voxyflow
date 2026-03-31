import { useState, useEffect } from 'react';

function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^#{1,3}\s+(.+)$/gm, '<h4>$1</h4>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>')
    .replace(/\n{2,}/g, '</p><p>')
    .replace(/\n/g, '<br>');
}

interface StandupSectionProps {
  projectId: string;
}

export function StandupSection({ projectId }: StandupSectionProps) {
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [scheduled, setScheduled] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    checkSchedule();
  }, [projectId]);

  async function checkSchedule() {
    try {
      const resp = await fetch(`/api/projects/${projectId}/standup/schedule`);
      if (resp.ok) {
        const data = await resp.json() as { enabled?: boolean };
        setScheduled(!!(data && data.enabled));
      }
    } catch (err) {
      console.warn('[ProjectStats] Failed to load standup schedule:', err);
    }
  }

  async function generateStandup() {
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/standup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as { summary: string; generated_at: string };
      setSummary(data.summary);
      setGeneratedAt(data.generated_at);
    } catch (err) {
      console.error('[Standup] generation failed:', err);
      setSummary('⚠️ Failed to generate standup. Please try again.');
      setGeneratedAt(null);
    } finally {
      setLoading(false);
    }
  }

  async function toggleSchedule(enabled: boolean) {
    try {
      await fetch(`/api/projects/${projectId}/standup/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, hour: 9, minute: 0 }),
      });
      setScheduled(enabled);
    } catch (err) {
      console.error('[Standup] schedule toggle failed:', err);
    }
  }

  async function copyToClipboard() {
    if (!summary) return;
    await navigator.clipboard.writeText(summary);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="standup-section">
      <h3 className="standup-section-title">📋 Daily Standup</h3>

      <div className="standup-controls">
        <button
          className={`standup-gen-btn${loading ? ' loading' : ''}`}
          disabled={loading}
          onClick={generateStandup}
        >
          {loading ? '⏳ Generating…' : '✨ Generate Standup'}
        </button>

        <label className="standup-schedule-label">
          <input
            type="checkbox"
            checked={scheduled}
            onChange={e => toggleSchedule(e.target.checked)}
          />
          <span>⏰ Schedule daily (09:00)</span>
        </label>
      </div>

      {summary && (
        <div className="standup-card">
          {generatedAt && (
            <div className="standup-card-meta">
              Generated {new Date(generatedAt).toLocaleString()}
            </div>
          )}
          <div
            className="standup-card-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(summary) }}
          />
          <button className="standup-copy-btn" onClick={copyToClipboard}>
            {copied ? '✅ Copied!' : '📋 Copy to Clipboard'}
          </button>
        </div>
      )}
    </div>
  );
}
