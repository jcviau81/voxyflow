import { useState } from 'react';

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

interface BriefSectionProps {
  projectId: string;
  projectName: string;
}

export function BriefSection({ projectId, projectName }: BriefSectionProps) {
  const [loading, setLoading] = useState(false);
  const [brief, setBrief] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function generateBrief() {
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/brief`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json() as { brief: string; generated_at: string };
      setBrief(data.brief);
      setGeneratedAt(data.generated_at);
    } catch (err) {
      console.error('[Brief] generation failed:', err);
      setBrief('⚠️ Failed to generate project brief. Please try again.');
      setGeneratedAt(null);
    } finally {
      setLoading(false);
    }
  }

  async function copyToClipboard() {
    if (!brief) return;
    await navigator.clipboard.writeText(brief);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function downloadMarkdown() {
    if (!brief) return;
    const filename = `${projectName.replace(/\s+/g, '-').toLowerCase()}-brief.md`;
    const blob = new Blob([brief], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="brief-section">
      <h3 className="brief-section-title">📄 Project Brief</h3>

      <div className="brief-controls">
        <button
          className={`brief-gen-btn${loading ? ' loading' : ''}`}
          disabled={loading}
          onClick={generateBrief}
        >
          {loading ? (
            <>⏳ Generating… <span className="brief-loading-note">(Using Deep model — may take 10-15s…)</span></>
          ) : (
            <>✨ Generate Brief <span className="brief-model-note">Opus</span></>
          )}
        </button>
      </div>

      {brief && (
        <div className="brief-card">
          {generatedAt && (
            <div className="brief-card-meta">
              Generated {new Date(generatedAt).toLocaleString()} · Deep model (Opus)
            </div>
          )}
          <div
            className="brief-card-content"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(brief) }}
          />
          <div className="brief-actions">
            <button className="brief-action-btn" onClick={copyToClipboard}>
              {copied ? '✅ Copied!' : '📋 Copy to Clipboard'}
            </button>
            <button className="brief-action-btn" onClick={downloadMarkdown}>
              ⬇️ Download .md
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
