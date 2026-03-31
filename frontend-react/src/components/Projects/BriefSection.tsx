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
    <div className="pt-6 border-t border-border">
      <h3 className="text-base font-bold text-foreground mb-3.5">📄 Project Brief</h3>

      <div className="flex items-center gap-3 flex-wrap mb-4">
        <button
          className="inline-flex items-center gap-2 border-none rounded-lg px-4 py-2 text-sm font-semibold text-white cursor-pointer transition-opacity hover:opacity-85 disabled:opacity-65 disabled:cursor-not-allowed"
          style={{
            background: loading
              ? 'linear-gradient(135deg, #5a52d5 0%, #8b44d4 100%)'
              : 'linear-gradient(135deg, #6c63ff 0%, #a855f7 100%)',
          }}
          disabled={loading}
          onClick={generateBrief}
        >
          {loading ? (
            <>⏳ Generating… <span className="text-xs font-normal opacity-85">(Using Deep model — may take 10-15s…)</span></>
          ) : (
            <>✨ Generate Brief <span className="bg-white/25 rounded px-1.5 py-0.5 text-[0.8125rem] font-bold tracking-[0.04em] uppercase">Opus</span></>
          )}
        </button>
      </div>

      {brief && (
        <div className="bg-card border border-border rounded-xl p-5 flex flex-col gap-3.5">
          {generatedAt && (
            <div className="text-[0.8125rem] text-muted-foreground">
              Generated {new Date(generatedAt).toLocaleString()} · Deep model (Opus)
            </div>
          )}
          <div
            className="text-sm text-foreground leading-[1.7] [&_ul]:my-1 [&_ul]:pl-5.5 [&_ul]:mb-2.5 [&_li]:mb-1 [&_strong]:text-foreground [&_strong]:font-bold [&_h4]:text-[0.95rem] [&_h4]:font-bold [&_h4]:mt-4.5 [&_h4]:mb-1.5 [&_h4]:border-b [&_h4]:border-border [&_h4]:pb-1"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(brief) }}
          />
          <div className="flex gap-2.5 flex-wrap">
            <button
              className="bg-transparent border border-border rounded-lg px-3.5 py-1.5 text-xs text-muted-foreground cursor-pointer transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              onClick={copyToClipboard}
            >
              {copied ? '✅ Copied!' : '📋 Copy to Clipboard'}
            </button>
            <button
              className="bg-transparent border border-border rounded-lg px-3.5 py-1.5 text-xs text-muted-foreground cursor-pointer transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              onClick={downloadMarkdown}
            >
              ⬇️ Download .md
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
