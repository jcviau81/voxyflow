import { useUsageStore, type ContextBreakdown } from '../../stores/useUsageStore';
import { cn } from '../../lib/utils';

interface ContextUsagePillProps {
  sessionId?: string;
  className?: string;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}K`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatPercent(pct: number): string {
  if (pct < 1) return pct.toFixed(1);
  return String(Math.round(pct));
}

// Order + labels for the injected-context breakdown tooltip.
const BREAKDOWN_ROWS: Array<[keyof ContextBreakdown, string]> = [
  ['system', 'System prompt'],
  ['tools', 'Tools (MCP schemas)'],
  ['memory', 'Memory / RAG'],
  ['workspace', 'Workspace + cards'],
  ['sessions', 'Sessions (history)'],
  ['workers', 'Workers / live state'],
];

export function ContextUsagePill({ sessionId, className }: ContextUsagePillProps) {
  const usage = useUsageStore((s) => (sessionId ? s.byChat[sessionId] : undefined));
  if (!usage || !usage.contextWindow) return null;

  const bd = usage.contextBreakdown;

  // Model-reported usage (input + cache, disjoint, = full prompt size). Kept as
  // a secondary reference in the tooltip — in CLI mode it includes Claude Code's
  // own prompt + tool schemas, so it's not what WE inject.
  const cacheRead = usage.cacheReadTokens ?? 0;
  const cacheCreate = usage.cacheCreationTokens ?? 0;
  const modelTotal = usage.inputTokens + cacheRead + cacheCreate;

  // Primary metric = the weight of the context WE inject, when available.
  // Falls back to the model-reported total if no breakdown was emitted.
  const total = bd ? bd.total : modelTotal;
  const pct = (total / usage.contextWindow) * 100;

  const tone =
    pct >= 80 ? 'text-red-500'
    : pct >= 60 ? 'text-yellow-500'
    : 'text-muted-foreground';

  const modelLine = usage.model ? `${usage.model}\n` : '';

  let title: string;
  if (bd) {
    const rows = BREAKDOWN_ROWS
      .filter(([k]) => (bd[k] as number) > 0)
      .map(([k, label]) => `  ${label}: ${(bd[k] as number).toLocaleString()} tokens`)
      .join('\n');
    const approxNote = bd.exact ? '' : '  (≈ estimate — exact tokenizer unavailable)\n';
    title =
      `${modelLine}injected context (what we send the dispatcher):\n` +
      `${rows}\n` +
      `  ─────\n` +
      `  total: ${bd.total.toLocaleString()} / ${usage.contextWindow.toLocaleString()} tokens (${formatPercent(pct)}%)\n` +
      approxNote +
      `\nmodel-reported last turn (incl. CLI/tool overhead):\n` +
      `  input: ${usage.inputTokens.toLocaleString()}  ·  output: ${usage.outputTokens.toLocaleString()} tokens` +
      (cacheRead || cacheCreate
        ? `\n  cache read: ${cacheRead.toLocaleString()}  ·  cache create: ${cacheCreate.toLocaleString()}`
        : '');
  } else {
    const cacheLine = cacheRead || cacheCreate
      ? `\n  cache read: ${cacheRead.toLocaleString()} tokens\n  cache create: ${cacheCreate.toLocaleString()} tokens`
      : '';
    title =
      `${modelLine}last turn (model-reported):\n` +
      `  fresh input: ${usage.inputTokens.toLocaleString()} tokens\n` +
      `  output: ${usage.outputTokens.toLocaleString()} tokens` +
      cacheLine;
  }

  return (
    <div
      className={cn(
        'chat-context-usage flex items-center gap-1 tabular-nums select-none',
        tone,
        className,
      )}
      title={title}
    >
      <span>{formatTokens(total)} / {formatTokens(usage.contextWindow)}</span>
      <span>·</span>
      <span>{formatPercent(pct)}%</span>
    </div>
  );
}
