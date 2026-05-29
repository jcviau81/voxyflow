/**
 * OnboardingPage — First-launch setup, two-step explainer flow.
 *
 * Step 1: Welcome + identity (your name, assistant name, theme, font size).
 * Step 2: "Models & Providers" explainer — points users to the real config
 *   (Settings → My Providers + Worker Classes) without leaving the flow.
 *
 * Why this changed (2026-05): the legacy onboarding asked for a single
 * "LLM API URL + API key" pair that wrote `models.fast.provider_url` /
 * `models.fast.api_key` directly. Voxyflow has been multi-provider for a
 * long time — that field embarked new users in the wrong direction.
 * It now lives only in Settings, surfaced via a drawer that wraps the
 * existing ModelPanel (no duplication).
 *
 * Migration: users with a stored "sk-any" fake key are not migrated; the
 * settings panel transparently lets them re-declare real endpoints.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { useThemeStore, type Theme } from '../stores/useThemeStore';
import { authFetch } from '../lib/authClient';
import { ProvidersExplainerStep } from '../components/Onboarding/ProvidersExplainerStep';

// ── Types ─────────────────────────────────────────────────────────────────────

interface OnboardingData {
  user_name: string;
  assistant_name: string;
  theme: Theme;
  font_size: 'small' | 'medium' | 'large';
}

type Step = 'identity' | 'providers';

// ── Component ─────────────────────────────────────────────────────────────────

export function OnboardingPage() {
  const navigate = useNavigate();
  const { setTheme, theme: currentTheme } = useThemeStore();

  const [step, setStep] = useState<Step>('identity');
  const [data, setData] = useState<OnboardingData>({
    user_name: '',
    assistant_name: 'Voxy',
    theme: currentTheme,
    font_size: 'medium',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const update = (field: keyof OnboardingData, value: string) =>
    setData((prev) => ({ ...prev, [field]: value }));

  const handleTheme = (t: Theme) => {
    setData((prev) => ({ ...prev, theme: t }));
    setTheme(t);
  };

  const handleFontSize = (size: 'small' | 'medium' | 'large') => {
    setData((prev) => ({ ...prev, font_size: size }));
    const sizeMap: Record<string, string> = { small: '15px', medium: '16px', large: '18px' };
    document.documentElement.style.setProperty('--font-size-base', sizeMap[size] || '16px');
  };

  /**
   * Final submit — fired from the providers step (Continue or Skip).
   * We DO NOT touch `models.*` here: the real config lives in Settings,
   * accessed via the drawer in step 2. Backend defaults / what the user
   * already configured in the drawer are left untouched.
   */
  const finalize = async () => {
    setSubmitting(true);
    setError('');

    // Fetch current settings so we merge instead of overwriting other panels.
    let current: Record<string, unknown> = {};
    try {
      const res = await fetch('/api/settings');
      if (res.ok) current = await res.json();
    } catch {
      // non-fatal — backend may be initialising
    }

    const personality = ((current.personality as Record<string, unknown>) || {});
    const settings: Record<string, unknown> = {
      ...current,
      personality: {
        ...personality,
        bot_name: data.assistant_name,
      },
      onboarding_complete: true,
      user_name: data.user_name,
      assistant_name: data.assistant_name,
    };

    try {
      const response = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      // Persist theme + font + onboarding flag locally
      localStorage.setItem('voxyflow-theme', data.theme);
      localStorage.setItem('voxyflow-font-size', data.font_size);
      localStorage.setItem('onboarding_complete', 'true');
      try {
        localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
      } catch {
        /* ignore quota errors */
      }

      // Update USER.md if a name was provided
      if (data.user_name) {
        try {
          await authFetch('/api/settings/personality/files/USER.md', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              content: `# USER.md — About You\n\n- **Name:** ${data.user_name}\n- **Preferred Language:** \n- **Timezone:** \n- **Notes:**\n\n## Preferences\n\n---\n_The more your assistant knows, the better it can help._\n`,
            }),
          });
        } catch {
          /* non-critical */
        }
      }

      navigate('/', { replace: true });
      window.location.reload();
    } catch (err) {
      setSubmitting(false);
      setError('Failed to save settings. Is the backend running?');
      console.error('[Onboarding] Failed:', err);
    }
  };

  const pillClass = (active: boolean) =>
    `px-4 py-2 rounded-lg text-sm font-medium border transition-colors cursor-pointer ${
      active
        ? 'bg-primary text-primary-foreground border-primary'
        : 'bg-transparent text-muted-foreground border-border hover:bg-accent'
    }`;

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-background p-4 overflow-auto">
      <div
        className="w-full max-w-2xl rounded-2xl border border-border bg-card p-8 shadow-lg space-y-6"
        data-testid="onboarding-page"
      >
        {/* Step indicator */}
        <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <span
            className={
              step === 'identity'
                ? 'text-foreground font-medium'
                : 'opacity-60'
            }
          >
            1 · Welcome
          </span>
          <span>›</span>
          <span
            className={
              step === 'providers'
                ? 'text-foreground font-medium'
                : 'opacity-60'
            }
          >
            2 · Models &amp; Providers
          </span>
        </div>

        {step === 'identity' && (
          <div className="space-y-6" data-testid="onboarding-step-identity">
            {/* Header */}
            <div className="text-center space-y-2">
              <div className="text-4xl">🎙️</div>
              <h1 className="text-2xl font-bold">Welcome to Voxyflow</h1>
              <p className="text-sm text-muted-foreground">
                Your voice-first workspace assistant. Let&apos;s get you set
                up.
              </p>
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                setStep('providers');
              }}
              className="space-y-5"
              autoComplete="off"
            >
              <Field
                label="Your name"
                hint="Used to personalize your assistant"
              >
                <Input
                  value={data.user_name}
                  onChange={(e) => update('user_name', e.target.value)}
                  placeholder="What should I call you?"
                  autoFocus
                />
              </Field>

              <Field
                label="Assistant name"
                hint="Give your assistant a name"
              >
                <Input
                  value={data.assistant_name}
                  onChange={(e) => update('assistant_name', e.target.value)}
                  placeholder="Voxy"
                />
              </Field>

              <hr className="border-border" />

              <Field label="Theme">
                <div className="flex gap-2">
                  <button
                    type="button"
                    className={pillClass(data.theme === 'dark')}
                    onClick={() => handleTheme('dark')}
                  >
                    🌙 Dark
                  </button>
                  <button
                    type="button"
                    className={pillClass(data.theme === 'light')}
                    onClick={() => handleTheme('light')}
                  >
                    ☀️ Light
                  </button>
                </div>
              </Field>

              <Field label="Font size">
                <div className="flex gap-2">
                  {(['small', 'medium', 'large'] as const).map((size) => (
                    <button
                      key={size}
                      type="button"
                      className={pillClass(data.font_size === size)}
                      onClick={() => handleFontSize(size)}
                    >
                      {size.charAt(0).toUpperCase() + size.slice(1)}
                    </button>
                  ))}
                </div>
              </Field>

              <Button
                type="submit"
                className="w-full h-10 text-base"
                data-testid="onboarding-identity-next"
              >
                Continue
              </Button>
            </form>
          </div>
        )}

        {step === 'providers' && (
          <div className="space-y-4">
            <ProvidersExplainerStep
              onContinue={finalize}
              onSkip={finalize}
            />
            {error && (
              <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
                {error}
              </div>
            )}
            {submitting && (
              <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={16} className="animate-spin" />
                Saving...
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Field helper ──────────────────────────────────────────────────────────────

function Field({
  label,
  hint,
  children,
}: {
  label: React.ReactNode;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
