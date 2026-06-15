/**
 * PageSkeleton — lightweight Suspense fallback for lazily loaded routes.
 * Matches the app surface tokens (muted blocks on background) and respects
 * prefers-reduced-motion (pulse disabled).
 */
import { cn } from '@/lib/utils';

export function PageSkeleton({ className }: { className?: string }) {
  return (
    <div className={cn('flex h-full w-full flex-col gap-4 p-6', className)} data-testid="page-skeleton">
      <div className="h-7 w-48 rounded-md bg-muted/60 animate-pulse motion-reduce:animate-none" />
      <div className="h-4 w-72 rounded bg-muted/40 animate-pulse motion-reduce:animate-none" />
      <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-28 rounded-xl border border-border/40 bg-muted/30 animate-pulse motion-reduce:animate-none"
          />
        ))}
      </div>
    </div>
  );
}
