import { useState, useEffect } from 'react';
import { ClipboardList, Sparkles, Loader2, Clock, Clipboard, Check } from 'lucide-react';

// XSS-safe by construction: the first replace chain escapes all &, <, > before
// any tag-injecting regex runs, so user-supplied angle brackets can only appear
// as &lt;/&gt; entities in the final HTML. Do NOT remove the leading escape
// line or reorder replacements.
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
    <div className="bg-card border border-border rounded-xl p-5">
      <h3 className="flex items-center gap-2 text-base font-bold text-foreground mb-4"><ClipboardList size={16} /> Daily Standup</h3>

      <div className="flex items-center gap-4 flex-wrap">
        <button
          className="flex items-center gap-1.5 bg-[var(--color-accent)] text-white border-none rounded-lg px-4 py-2 text-sm font-semibold cursor-pointer transition-opacity hover:opacity-85 disabled:opacity-55 disabled:cursor-not-allowed"
          disabled={loading}
          onClick={generateStandup}
        >
          {loading
            ? <><Loader2 size={14} className="animate-spin" /> Generating…</>
            : <><Sparkles size={14} /> Generate Standup</>
          }
        </button>

        <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={scheduled}
            onChange={e => toggleSchedule(e.target.checked)}
            className="accent-[var(--color-accent)] w-4 h-4 cursor-pointer"
          />
          <span className="flex items-center gap-1"><Clock size={13} /> Schedule daily (09:00)</span>
        </label>
      </div>

      {summary && (
        <div
          className="mt-4 bg-muted/30 border border-border rounded-lg p-4 flex flex-col gap-3"
          style={{ borderLeftWidth: '3px', borderLeftColor: 'var(--color-accent)' }}
        >
          {generatedAt && (
            <div className="text-[0.8125rem] text-muted-foreground">
              Generated {new Date(generatedAt).toLocaleString()}
            </div>
          )}
          <div
            className="text-sm text-foreground leading-relaxed [&_ul]:my-1 [&_ul]:pl-5 [&_ul]:mb-2 [&_li]:mb-[3px] [&_strong]:text-foreground [&_strong]:font-bold [&_h4]:text-sm [&_h4]:font-bold [&_h4]:mt-3 [&_h4]:mb-1"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(summary) }}
          />
          <button
            className="self-start flex items-center gap-1.5 bg-transparent border border-border rounded-lg px-3.5 py-1.5 text-xs text-muted-foreground cursor-pointer transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
            onClick={copyToClipboard}
          >
            {copied
              ? <><Check size={12} /> Copied!</>
              : <><Clipboard size={12} /> Copy to Clipboard</>
            }
          </button>
        </div>
      )}
    </div>
  );
}
