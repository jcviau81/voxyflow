/**
 * OnboardingGuard — redirects to /onboarding if setup hasn't been completed.
 *
 * Checks localStorage first (fast), then validates against the backend settings.
 * The "Reset Onboarding" button in AboutPanel clears the localStorage flag,
 * which triggers the redirect on next load.
 */

import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

interface OnboardingGuardProps {
  children: React.ReactNode;
}

export function OnboardingGuard({ children }: OnboardingGuardProps) {
  const [status, setStatus] = useState<'loading' | 'complete' | 'needs_onboarding' | 'backend_unreachable'>('loading');

  useEffect(() => {
    const syncNames = (data: Record<string, unknown>) => {
      try {
        const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
        if (data.user_name) stored.user_name = data.user_name;
        if (data.assistant_name) stored.assistant_name = data.assistant_name;
        const personality = data.personality as Record<string, unknown> | undefined;
        if (personality?.bot_name) {
          if (!stored.personality) stored.personality = {};
          (stored.personality as Record<string, unknown>).bot_name = personality.bot_name;
        }
        localStorage.setItem('voxyflow_settings', JSON.stringify(stored));
      } catch { /* ignore */ }
    };

    // Fast path: if localStorage says complete, still sync names from backend
    if (localStorage.getItem('onboarding_complete') === 'true') {
      setStatus('complete');
      fetch('/api/settings').then((r) => r.json()).then(syncNames).catch(() => {});
      return;
    }

    // Otherwise check the backend
    fetch('/api/settings')
      .then((r) => r.json())
      .then((data: Record<string, unknown>) => {
        syncNames(data);
        if (data.onboarding_complete) {
          localStorage.setItem('onboarding_complete', 'true');
          setStatus('complete');
        } else {
          setStatus('needs_onboarding');
        }
      })
      .catch(() => {
        // Backend unreachable and we have no cached onboarding flag — don't silently
        // let the user through (that masks first-run setup as "done"). Ask to retry.
        setStatus('backend_unreachable');
      });
  }, []);

  if (status === 'loading') {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-background">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (status === 'backend_unreachable') {
    return (
      <div className="fixed inset-0 flex flex-col items-center justify-center bg-background p-6 text-center">
        <p className="text-foreground mb-2">Can't reach the Voxyflow backend.</p>
        <p className="text-muted-foreground text-sm mb-4">
          Make sure the backend service is running, then retry.
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="px-4 py-2 rounded bg-primary text-primary-foreground text-sm"
        >
          Retry
        </button>
      </div>
    );
  }

  if (status === 'needs_onboarding') {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
