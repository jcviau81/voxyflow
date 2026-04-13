/**
 * OnboardingPage — First-launch setup form.
 *
 * Migrated from frontend/src/components/Onboarding/OnboardingPage.ts.
 * Single scrollable page that collects essential config, saves via
 * PUT /api/settings, then navigates into the main app.
 */

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Input } from '../components/ui/input';
import { Button } from '../components/ui/button';
import { useThemeStore, type Theme } from '../stores/useThemeStore';
import { Loader2 } from 'lucide-react';

// ── Types ─────────────────────────────────────────────────────────────────

interface OnboardingData {
  user_name: string;
  assistant_name: string;
  api_url: string;
  api_key: string;
  fast_model: string;
  deep_model: string;
  theme: Theme;
  font_size: 'small' | 'medium' | 'large';
}

// ── Component ─────────────────────────────────────────────────────────────

export function OnboardingPage() {
  const navigate = useNavigate();
  const { setTheme, theme: currentTheme } = useThemeStore();

  const [data, setData] = useState<OnboardingData>({
    user_name: '',
    assistant_name: 'Voxy',
    api_url: 'http://localhost:3457/v1',
    api_key: 'sk-any',
    fast_model: 'claude-sonnet-4-5',
    deep_model: 'claude-opus-4-5',
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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');

    const settings = {
      personality: {
        bot_name: data.assistant_name,
        preferred_language: 'both',
        soul_file: './personality/SOUL.md',
        user_file: './personality/USER.md',
        agents_file: './personality/AGENTS.md',
        custom_instructions: '',
        environment_notes: '',
        tone: 'casual',
        warmth: 'warm',
      },
      models: {
        fast: {
          provider_url: data.api_url,
          api_key: data.api_key,
          model: data.fast_model,
          enabled: true,
        },
        deep: {
          provider_url: data.api_url,
          api_key: data.api_key,
          model: data.deep_model,
          enabled: true,
        },
      },
      voice: {
        stt_engine: 'native',
        stt_model: 'medium',
        stt_language: 'auto',
        tts_enabled: true,
        tts_auto_play: false,
        tts_url: 'http://localhost:5500',
        tts_voice: 'default',
        tts_speed: 1.0,
        volume: 80,
      },
      scheduler: {
        enabled: true,
        heartbeat_interval_minutes: 2,
        rag_index_interval_minutes: 15,
      },
      onboarding_complete: true,
      user_name: data.user_name,
      assistant_name: data.assistant_name,
    };

    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      // Persist theme + font to localStorage
      localStorage.setItem('voxyflow-theme', data.theme);
      localStorage.setItem('voxyflow-font-size', data.font_size);
      localStorage.setItem('onboarding_complete', 'true');
      try { localStorage.setItem('voxyflow_settings', JSON.stringify(settings)); } catch { /* ignore */ }

      // Update USER.md if name provided
      if (data.user_name) {
        try {
          await fetch('/api/settings/personality/files/USER.md', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              content: `# USER.md — About You\n\n- **Name:** ${data.user_name}\n- **Preferred Language:** \n- **Timezone:** \n- **Notes:**\n\n## Preferences\n\n---\n_The more your assistant knows, the better it can help._\n`,
            }),
          });
        } catch { /* non-critical */ }
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
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-8 shadow-lg space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="text-4xl">🎙️</div>
          <h1 className="text-2xl font-bold">Welcome to Voxyflow</h1>
          <p className="text-sm text-muted-foreground">
            Your voice-first project assistant. Let's get you set up.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5" autoComplete="off">
          {/* Your Name */}
          <Field label="Your name" hint="Used to personalize your assistant">
            <Input
              value={data.user_name}
              onChange={(e) => update('user_name', e.target.value)}
              placeholder="What should I call you?"
              autoFocus
            />
          </Field>

          {/* Assistant Name */}
          <Field label="Assistant name" hint="Give your assistant a name">
            <Input
              value={data.assistant_name}
              onChange={(e) => update('assistant_name', e.target.value)}
              placeholder="Voxy"
            />
          </Field>

          <hr className="border-border" />

          {/* LLM API URL */}
          <Field label="LLM API URL" hint="OpenAI-compatible API endpoint">
            <Input
              value={data.api_url}
              onChange={(e) => update('api_url', e.target.value)}
              placeholder="http://localhost:3457/v1"
            />
          </Field>

          {/* API Key */}
          <Field label="API Key" hint="Leave as-is for local proxies">
            <Input
              value={data.api_key}
              onChange={(e) => update('api_key', e.target.value)}
              placeholder="sk-any"
            />
          </Field>

          {/* Fast Model */}
          <Field label={<>Fast model <span className="ml-1 text-xs text-muted-foreground font-normal">conversational</span></>}>
            <Input
              value={data.fast_model}
              onChange={(e) => update('fast_model', e.target.value)}
              placeholder="claude-sonnet-4-5"
            />
          </Field>

          {/* Deep Model */}
          <Field label={<>Deep model <span className="ml-1 text-xs text-muted-foreground font-normal">analysis</span></>}>
            <Input
              value={data.deep_model}
              onChange={(e) => update('deep_model', e.target.value)}
              placeholder="claude-opus-4-5"
            />
          </Field>

          <hr className="border-border" />

          {/* Theme */}
          <Field label="Theme">
            <div className="flex gap-2">
              <button type="button" className={pillClass(data.theme === 'dark')} onClick={() => handleTheme('dark')}>
                🌙 Dark
              </button>
              <button type="button" className={pillClass(data.theme === 'light')} onClick={() => handleTheme('light')}>
                ☀️ Light
              </button>
            </div>
          </Field>

          {/* Font Size */}
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

          {/* Error */}
          {error && (
            <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          {/* Submit */}
          <Button type="submit" className="w-full h-10 text-base" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 size={16} className="animate-spin mr-2" />
                Setting up...
              </>
            ) : (
              "Let's go 🚀"
            )}
          </Button>
        </form>
      </div>
    </div>
  );
}

// ── Field helper ──────────────────────────────────────────────────────────

function Field({ label, hint, children }: { label: React.ReactNode; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm font-medium">{label}</label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
