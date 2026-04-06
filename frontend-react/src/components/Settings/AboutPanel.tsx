/**
 * AboutPanel — Version info + service health bar.
 *
 * Mirrors renderAboutSection() + renderHealthBar() + loadServiceHealth()
 * from frontend/src/components/Settings/SettingsPage.ts (lines 1080–1131, 1369–1386).
 *
 * Features:
 *  - Service health dots (GET /api/health/services, auto-refresh every 30s)
 *  - Version info
 *  - Reset onboarding button (clears localStorage flag + reloads)
 */

import { useEffect, useState, useCallback } from 'react';
import { Info, RefreshCw } from 'lucide-react';
import { cn } from '../../lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────

interface ServiceHealth {
  name: string;
  status: 'ok' | 'down';
}

// ── HealthBar ──────────────────────────────────────────────────────────────

function HealthBar() {
  const [services, setServices] = useState<ServiceHealth[]>([]);
  const [checking, setChecking] = useState(true);

  const fetchHealth = useCallback(async () => {
    try {
      const response = await fetch('/api/health/services');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: { services?: Record<string, { status: string }> } = await response.json();
      const svcDict = data.services ?? {};
      setServices(
        Object.entries(svcDict)
          .filter(([, info]) => info.status !== 'not_configured')
          .map(([name, info]) => ({
            name: name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
            status: (info.status === 'ok' || info.status === 'not_applicable' ? 'ok' : 'down') as 'ok' | 'down',
          }))
      );
    } catch {
      setServices([
        { name: 'Claude Proxy', status: 'down' },
        { name: 'XTTS', status: 'down' },
        { name: 'ChromaDB', status: 'down' },
      ]);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30_000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-muted/20 px-4 py-2.5">
      <span className="text-xs font-medium text-muted-foreground flex items-center gap-1">
        <span className="text-green-500">●</span> Services
      </span>
      {checking ? (
        <span className="text-xs text-muted-foreground">Checking…</span>
      ) : (
        services.map((s) => (
          <span
            key={s.name}
            className={cn(
              'flex items-center gap-1.5 text-xs',
              s.status === 'ok' ? 'text-green-500' : 'text-destructive'
            )}
          >
            <span
              className={cn(
                'h-2 w-2 rounded-full',
                s.status === 'ok' ? 'bg-green-500' : 'bg-destructive'
              )}
            />
            {s.name}
          </span>
        ))
      )}
      <button
        type="button"
        onClick={fetchHealth}
        className="ml-auto text-muted-foreground hover:text-foreground transition-colors"
        title="Refresh service status"
      >
        <RefreshCw size={12} />
      </button>
    </div>
  );
}

// ── AboutPanel ─────────────────────────────────────────────────────────────

export function AboutPanel() {
  const handleResetOnboarding = async () => {
    // Clear the backend flag so OnboardingGuard redirects to /onboarding
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const settings = await res.json();
        await fetch('/api/settings', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...settings, onboarding_complete: false }),
        });
      }
    } catch { /* best-effort */ }
    localStorage.removeItem('onboarding_complete');
    location.reload();
  };

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-about">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Info size={16} />
        About Voxyflow
      </h3>

      {/* Service health */}
      <HealthBar />

      {/* Version info */}
      <div className="text-sm text-muted-foreground leading-relaxed">
        <div className="font-medium text-foreground">Voxyflow</div>
        <div>Voice-first project assistant</div>
        <div className="mt-1 font-mono text-xs">Version: 1.0.0</div>
      </div>

      {/* Reset onboarding */}
      <div className="setting-row flex items-center justify-between gap-4 pt-2 border-t border-border">
        <div className="setting-info space-y-0.5">
          <div className="setting-label text-sm font-medium">Reset Onboarding</div>
          <div className="setting-description text-xs text-muted-foreground">
            Show the first-launch setup screen again on next reload
          </div>
        </div>
        <button
          type="button"
          onClick={handleResetOnboarding}
          className="h-8 px-4 text-sm rounded-md border border-border hover:bg-accent transition-colors"
        >
          Reset Onboarding
        </button>
      </div>
    </div>
  );
}
