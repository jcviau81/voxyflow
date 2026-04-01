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
  const [status, setStatus] = useState<'loading' | 'complete' | 'needs_onboarding'>('loading');

  useEffect(() => {
    // Fast path: if localStorage says complete, trust it
    if (localStorage.getItem('onboarding_complete') === 'true') {
      setStatus('complete');
      return;
    }

    // Otherwise check the backend
    fetch('/api/settings')
      .then((r) => r.json())
      .then((data) => {
        if (data.onboarding_complete) {
          localStorage.setItem('onboarding_complete', 'true');
          setStatus('complete');
        } else {
          setStatus('needs_onboarding');
        }
      })
      .catch(() => {
        // Backend unreachable — let the app load anyway (it'll show errors elsewhere)
        setStatus('complete');
      });
  }, []);

  if (status === 'loading') {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-background">
        <Loader2 size={24} className="animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (status === 'needs_onboarding') {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
