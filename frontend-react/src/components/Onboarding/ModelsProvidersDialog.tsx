/**
 * ModelsProvidersDialog — reuses the Settings ModelPanel inside a modal
 * so the onboarding flow can let users configure providers + worker classes
 * without leaving the welcome screen.
 *
 * The same ModelPanel that powers Settings → "Models & Providers" is mounted
 * inside a Radix Dialog. We optionally scroll to the relevant section
 * (data-section="my-providers" or "worker-classes") when opening, so each
 * onboarding card jumps the user straight to the right spot.
 */

import { useEffect, useRef } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { ModelPanel } from '@/components/Settings/ModelPanel';

export type ModelsProvidersSection = 'my-providers' | 'worker-classes';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Optional anchor; the dialog scrolls to `[data-section="<section>"]` on open. */
  section?: ModelsProvidersSection;
  /** Override the dialog title (defaults to "Models & Providers"). */
  title?: string;
  /** Override the dialog subtitle. */
  description?: string;
}

export function ModelsProvidersDialog({
  open,
  onOpenChange,
  section,
  title = 'Models & Providers',
  description = 'Add your local or remote providers (Mac Studio, MacBook, server...) then assign them to the Fast and Deep layers. Each layer can use a different provider.',
}: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Scroll to the requested section after the dialog opens & ModelPanel mounts.
  useEffect(() => {
    if (!open || !section) return;
    // ModelPanel renders async (queries fetch settings) — retry a few frames.
    let attempts = 0;
    const tryScroll = () => {
      const root = scrollRef.current;
      if (!root) return;
      const target = root.querySelector<HTMLElement>(`[data-section="${section}"]`);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }
      if (attempts++ < 15) {
        setTimeout(tryScroll, 120);
      }
    };
    tryScroll();
  }, [open, section]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-5xl w-[calc(100%-2rem)] max-h-[90vh] p-0 overflow-hidden flex flex-col"
        data-testid="onboarding-providers-dialog"
      >
        <DialogHeader className="px-6 pt-5 pb-3 border-b">
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto"
          data-testid="onboarding-providers-dialog-body"
        >
          <ModelPanel />
        </div>
      </DialogContent>
    </Dialog>
  );
}
