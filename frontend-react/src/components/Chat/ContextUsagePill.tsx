import { useUsageStore } from '../../stores/useUsageStore';
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

export function ContextUsagePill({ sessionId, className }: ContextUsagePillProps) {
  const usage = useUsageStore((s) => (sessionId ? s.byChat[sessionId] : undefined));
  if (!usage || !usage.contextWindow) return null;

  const cacheRead = usage.cacheReadTokens ?? 0;
  const cacheCreate = usage.cacheCreationTokens ?? 0;
  // Context window = input-side budget only. fresh + cache_read + cache_create
  // are disjoint in Anthropic's usage response and together equal the full prompt
  // size. Output has its own separate max_tokens budget, so don't add it here —
  // including it was pushing the displayed total past 200k on normal turns.
  const total = usage.inputTokens + cacheRead + cacheCreate;
  const pct = (total / usage.contextWindow) * 100;

  const tone =
    pct >= 80 ? 'text-red-500'
    : pct >= 60 ? 'text-yellow-500'
    : 'text-muted-foreground';

  const modelLine = usage.model ? `${usage.model}\n` : '';
  const cacheLine = cacheRead > 0 || cacheCreate > 0
    ? `\n  cache read: ${cacheRead.toLocaleString()} tokens\n  cache create: ${cacheCreate.toLocaleString()} tokens`
    : '';
  const title =
    `${modelLine}last turn:\n` +
    `  fresh input: ${usage.inputTokens.toLocaleString()} tokens\n` +
    `  output: ${usage.outputTokens.toLocaleString()} tokens` +
    cacheLine;

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
