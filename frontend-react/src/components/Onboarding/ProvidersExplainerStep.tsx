/**
 * ProvidersExplainerStep — the new onboarding step that replaces the legacy
 * "LLM API URL + fake API key + fast/deep model" form fields.
 *
 * Voxyflow is multi-provider: real configuration lives in
 * Settings → "Models & Providers" ("My Providers" + "Worker Classes").
 * The legacy single-proxy field embarked new users in the wrong direction —
 * this step explains the two layers of config and lets them open the real
 * panels inline (drawer/modal) without leaving the onboarding flow.
 *
 * Decisions locked in by JC (do not change copy / wording):
 *   - Page = "Models & Providers"
 *   - Endpoint section = "My Providers"
 *   - "My Machines" is OBSOLETE — never appears in user-facing copy
 *   - Badge ✓ "configured" auto when endpoints.length >= 1
 *   - Drawer reuses the existing Settings ModelPanel (no duplication)
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Server, Workflow, ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { apiFetch } from '@/lib/apiClient';
import {
  ModelsProvidersDialog,
  type ModelsProvidersSection,
} from './ModelsProvidersDialog';

interface AppSettings {
  models?: {
    endpoints?: Array<{ id: string }>;
  };
}

interface Props {
  onContinue: () => void;
  onSkip: () => void;
}

export function ProvidersExplainerStep({ onContinue, onSkip }: Props) {
  const [drawer, setDrawer] = useState<ModelsProvidersSection | null>(null);

  // Live endpoint count drives the ✓ "configured" badge. The query refreshes
  // every time the dialog closes (cf. ModelPanel's saveMutation invalidates
  // queryKey: ['settings']) so badge auto-updates without manual refetch.
  const { data: settings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => apiFetch<AppSettings>('/api/settings'),
    staleTime: 5_000,
  });

  const endpointCount = settings?.models?.endpoints?.length ?? 0;
  const configured = endpointCount >= 1;

  return (
    <div
      className="w-full max-w-2xl space-y-6"
      data-testid="onboarding-providers-step"
    >
      <div className="text-center space-y-2">
        <div className="text-4xl">🧠</div>
        <h1 className="text-2xl font-bold">Models &amp; Providers</h1>
        <p className="text-sm text-muted-foreground">
          Voxyflow routes your tasks to the right model based on intent.
          Configure this in two places:
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-1">
        {/* ── Card 1: My Providers ── */}
        <div
          className="rounded-xl border border-border bg-card p-5 space-y-3"
          data-testid="onboarding-card-my-providers"
        >
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Server size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-semibold">My Providers</h2>
                {configured && (
                  <span
                    className="inline-flex items-center gap-1 rounded-full bg-green-500/10 text-green-500 px-2 py-0.5 text-xs font-medium"
                    data-testid="onboarding-badge-configured"
                  >
                    <CheckCircle2 size={12} />
                    configured
                  </span>
                )}
              </div>
              <p className="text-sm text-muted-foreground mt-1">
                Local or remote servers running an LLM. Declare your endpoints
                (Claude CLI, Codex CLI, Ollama, OpenAI, Gemini, Groq, Mistral,
                LM Studio).
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full justify-center"
            onClick={() => setDrawer('my-providers')}
            data-testid="onboarding-btn-configure-providers"
          >
            <ExternalLink size={14} className="mr-2" />
            Configure providers
          </Button>
        </div>

        {/* ── Card 2: Worker Classes ── */}
        <div
          className="rounded-xl border border-border bg-card p-5 space-y-3"
          data-testid="onboarding-card-worker-classes"
        >
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Workflow size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-base font-semibold">Worker Classes</h2>
              <p className="text-sm text-muted-foreground mt-1">
                Map intents (Coding, Research, Architecture…) to the providers
                you just declared. Fast = quick dispatch, Deep = complex
                reasoning.
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full justify-center"
            onClick={() => setDrawer('worker-classes')}
            data-testid="onboarding-btn-configure-worker-classes"
          >
            <ExternalLink size={14} className="mr-2" />
            Configure worker classes
          </Button>
        </div>
      </div>

      <p className="text-center text-xs text-muted-foreground">
        You can skip and configure later — Voxyflow ships with sensible
        defaults.
      </p>

      <div className="flex flex-col sm:flex-row gap-2 sm:justify-end pt-2">
        <Button
          type="button"
          variant="outline"
          onClick={onSkip}
          data-testid="onboarding-btn-skip"
        >
          Skip for now
        </Button>
        <Button
          type="button"
          onClick={onContinue}
          data-testid="onboarding-btn-continue"
        >
          Continue
        </Button>
      </div>

      <ModelsProvidersDialog
        open={drawer !== null}
        onOpenChange={(o) => !o && setDrawer(null)}
        section={drawer ?? undefined}
      />
    </div>
  );
}
