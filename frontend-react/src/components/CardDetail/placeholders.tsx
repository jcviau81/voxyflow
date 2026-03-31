/**
 * Placeholder components for CardDetailModal sections not yet implemented.
 * 11b sections (TimeTracking, Comments, Checklist, Attachments, LinkedFiles) are in sections/.
 * Remaining placeholders are for step 11c.
 */

// ── 11c placeholders ────────────────────────────────────────────────────────

export function RelationsSection({ cardId: _cardId }: { cardId: string }) {
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium text-muted-foreground">Related Cards</span>
      <p className="text-xs text-muted-foreground/60">Coming in step 11c</p>
    </div>
  );
}

export function HistorySection({ cardId: _cardId }: { cardId: string }) {
  return (
    <div className="space-y-1">
      <span className="text-xs font-medium text-muted-foreground">History</span>
      <p className="text-xs text-muted-foreground/60">Coming in step 11c</p>
    </div>
  );
}

export function CardChatSection({ cardId: _cardId }: { cardId: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <span className="text-sm font-medium text-muted-foreground">Card Chat</span>
      <p className="mt-1 text-xs text-muted-foreground/60">
        Embedded chat will be wired in step 11c
      </p>
    </div>
  );
}

export function DescriptionEditor({
  cardId: _cardId,
  value,
  onChange,
}: {
  cardId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Write card description... (Markdown supported)"
        className="min-h-[200px] flex-1 resize-none rounded-md border border-border bg-transparent p-3 text-sm outline-none placeholder:text-muted-foreground/50 focus:border-accent"
      />
      <p className="mt-1 text-[10px] text-muted-foreground/50">
        CodeMirror editor will replace this in step 11c
      </p>
    </div>
  );
}
