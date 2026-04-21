/**
 * NotificationsPanel — Web Push notifications settings.
 *
 * Features:
 *  - Browser support + permission status
 *  - Master "Enable browser notifications" toggle
 *  - Per-event toggles (worker_done, autonomy_result)
 *  - Send test notification
 *  - Active subscriptions list (debug)
 */

import { useEffect, useState } from 'react';
import {
  Bell,
  BellOff,
  Loader2,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Trash2,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useToastStore } from '../../stores/useToastStore';
import { authFetch } from '../../lib/authClient';
import {
  isPushSupported,
  getPermission,
  enablePush,
  disablePush,
  sendTestNotification,
  getSubscriptions,
  unsubscribeByEndpoint,
  type PushSubscriptionRow,
} from '../../services/pushService';

// ── Types ──────────────────────────────────────────────────────────────────

interface PushEventSettings {
  worker_done?: boolean;
  autonomy_result?: boolean;
}

interface PushSettings {
  enabled?: boolean;
  events?: PushEventSettings;
}

interface AppSettings {
  push?: PushSettings;
  [key: string]: unknown;
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Toggle({
  checked,
  disabled,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        checked ? 'bg-primary' : 'bg-muted'
      } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}

function SupportBadge({
  supported,
  permission,
}: {
  supported: boolean;
  permission: NotificationPermission;
}) {
  if (!supported) {
    return (
      <span className="flex items-center gap-1.5 text-sm text-destructive">
        <XCircle size={14} />
        Not supported in this browser
      </span>
    );
  }
  if (permission === 'granted') {
    return (
      <span className="flex items-center gap-1.5 text-sm text-green-500">
        <CheckCircle size={14} />
        Supported · permission granted
      </span>
    );
  }
  if (permission === 'denied') {
    return (
      <span className="flex items-center gap-1.5 text-sm text-destructive">
        <XCircle size={14} />
        Supported · permission denied (change in browser settings)
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-sm text-yellow-500">
      <AlertTriangle size={14} />
      Supported · permission not yet requested
    </span>
  );
}

// ── NotificationsPanel ────────────────────────────────────────────────────

export function NotificationsPanel() {
  const { showToast } = useToastStore();
  const queryClient = useQueryClient();

  const supported = isPushSupported();
  const [permission, setPermission] = useState<NotificationPermission>(
    supported ? getPermission() : 'denied',
  );
  const [subsOpen, setSubsOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  // Load settings
  const { data: settings, isLoading } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: () => fetch('/api/settings').then((r) => r.json()),
  });

  const push = settings?.push ?? {};
  const enabled = Boolean(push.enabled);
  const evWorker = push.events?.worker_done !== false; // default true when master is on
  const evAutonomy = push.events?.autonomy_result !== false;

  // Load subscriptions (debug)
  const subsQuery = useQuery<PushSubscriptionRow[]>({
    queryKey: ['push-subscriptions'],
    queryFn: getSubscriptions,
    enabled: subsOpen,
  });

  // Refresh permission status when the tab becomes visible again.
  useEffect(() => {
    const onVis = () => {
      if (supported) setPermission(getPermission());
    };
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, [supported]);

  // Patch settings helper — merges push.* into the current /api/settings blob.
  const patchSettings = useMutation({
    mutationFn: async (patch: PushSettings) => {
      const current = (await fetch('/api/settings').then((r) => r.json())) as AppSettings;
      const merged: AppSettings = {
        ...current,
        push: {
          ...(current.push ?? {}),
          ...patch,
          events: {
            ...((current.push ?? {}).events ?? {}),
            ...(patch.events ?? {}),
          },
        },
      };
      const res = await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(merged),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: (e) => {
      showToast(`Failed to save: ${e}`, 'error', 3000);
    },
  });

  const handleMasterToggle = async (next: boolean) => {
    if (!supported) {
      showToast('Push notifications are not supported in this browser', 'error', 3000);
      return;
    }
    setBusy(true);
    try {
      if (next) {
        const result = await enablePush();
        if (!result.ok) {
          const reason =
            result.reason === 'permission-denied'
              ? 'Permission denied'
              : result.reason === 'not-supported'
                ? 'Not supported'
                : `Could not enable: ${result.reason}`;
          showToast(reason, 'error', 4000);
          setPermission(getPermission());
          return;
        }
        setPermission(getPermission());
        await patchSettings.mutateAsync({ enabled: true });
        showToast('Browser notifications enabled', 'success', 2500);
      } else {
        await disablePush();
        await patchSettings.mutateAsync({ enabled: false });
        showToast('Browser notifications disabled', 'success', 2000);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleEventToggle = (key: keyof PushEventSettings, next: boolean) => {
    patchSettings.mutate({ events: { [key]: next } });
  };

  const handleTest = async () => {
    try {
      const res = await sendTestNotification();
      if (res.sent > 0) {
        showToast(`Test sent to ${res.sent} subscription(s)`, 'success', 3000);
      } else if (res.failed > 0) {
        showToast(`Test failed for ${res.failed} subscription(s)`, 'error', 3000);
      } else {
        showToast('No active subscriptions to send to', 'info', 3000);
      }
    } catch (e) {
      showToast(`Test failed: ${e}`, 'error', 3000);
    }
  };

  const handleDeleteSub = async (endpoint: string) => {
    try {
      await unsubscribeByEndpoint(endpoint);
      showToast('Subscription removed', 'success', 2000);
      queryClient.invalidateQueries({ queryKey: ['push-subscriptions'] });
    } catch (e) {
      showToast(`Delete failed: ${e}`, 'error', 3000);
    }
  };

  if (isLoading) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground text-sm">
        <Loader2 size={16} className="animate-spin" />
        Loading…
      </div>
    );
  }

  const perEventDisabled = !enabled || !supported;

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-notifications">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Bell size={16} />
        Notifications
      </h3>

      {/* ── How notifications work ── */}
      <p className="text-xs text-muted-foreground leading-relaxed">
        Notifications work two ways: <strong>in-page</strong> (all browsers) while
        Voxyflow is open, and <strong>Web Push</strong> (Firefox, Chrome, Edge) even
        when it is closed. Enable below to get both.
      </p>

      {/* ── Browser support ── */}
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3 space-y-2">
        <SupportBadge supported={supported} permission={permission} />
        {supported && permission !== 'granted' && (
          <p className="text-xs text-muted-foreground leading-relaxed">
            Click <strong>Enable</strong> to grant browser notification permission.
            In-page notifications will start working immediately; Web Push may
            require additional browser support (Brave on Linux has a known GCM
            issue).
          </p>
        )}
      </div>

      {/* ── Master toggle ── */}
      <div className="setting-row flex items-center justify-between gap-4">
        <div className="setting-info space-y-0.5">
          <div className="setting-label text-sm font-medium">Enable browser notifications</div>
          <div className="setting-description text-xs text-muted-foreground">
            Voxyflow will deliver push notifications to this browser via VAPID when background
            events occur.
          </div>
        </div>
        <div className="flex items-center gap-2">
          {busy && <Loader2 size={14} className="animate-spin text-muted-foreground" />}
          <Toggle
            checked={enabled}
            disabled={!supported || busy}
            onChange={handleMasterToggle}
            ariaLabel="Enable browser notifications"
          />
        </div>
      </div>

      {/* ── Per-event toggles ── */}
      <div className="space-y-1">
        <h4 className="text-sm font-medium text-foreground">Event types</h4>
        <p className="text-xs text-muted-foreground mb-3">
          Choose which server events trigger a notification on this browser.
        </p>

        <div className="setting-row flex items-center justify-between gap-4 py-3 border-b border-border">
          <div className="setting-info space-y-0.5">
            <div className="setting-label text-sm font-medium">Worker finished</div>
            <div className="setting-description text-xs text-muted-foreground">
              A delegated worker completed (or failed) its task.
            </div>
          </div>
          <Toggle
            checked={evWorker}
            disabled={perEventDisabled}
            onChange={(v) => handleEventToggle('worker_done', v)}
            ariaLabel="Worker finished notifications"
          />
        </div>

        <div className="setting-row flex items-center justify-between gap-4 py-3 border-b border-border last:border-0">
          <div className="setting-info space-y-0.5">
            <div className="setting-label text-sm font-medium">Autonomy heartbeat</div>
            <div className="setting-description text-xs text-muted-foreground">
              Periodic autonomy-loop status updates.
            </div>
          </div>
          <Toggle
            checked={evAutonomy}
            disabled={perEventDisabled}
            onChange={(v) => handleEventToggle('autonomy_result', v)}
            ariaLabel="Autonomy heartbeat notifications"
          />
        </div>
      </div>

      {/* ── Test ── */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTest}
          disabled={!enabled || !supported}
          className="btn-primary h-8 px-4 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1.5"
        >
          <Bell size={14} />
          Send test notification
        </button>
        {!enabled && (
          <span className="text-xs text-muted-foreground">Enable notifications first</span>
        )}
      </div>

      {/* ── Subscriptions list (debug) ── */}
      <div>
        <button
          type="button"
          onClick={() => setSubsOpen((v) => !v)}
          className="flex items-center gap-1.5 text-sm font-medium text-foreground hover:text-primary transition-colors"
        >
          {subsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Active subscriptions
        </button>

        {subsOpen && (
          <div className="mt-3 space-y-2">
            {subsQuery.isLoading && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 size={12} className="animate-spin" />
                Loading…
              </div>
            )}
            {subsQuery.isError && (
              <div className="text-xs text-destructive">Failed to load subscriptions</div>
            )}
            {subsQuery.data && subsQuery.data.length === 0 && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <BellOff size={12} />
                No subscriptions registered.
              </div>
            )}
            {subsQuery.data?.map((s) => {
              const created = s.created ?? s.created_at ?? '';
              const ep = s.endpoint ?? '';
              const shortEp = ep.length > 60 ? `${ep.slice(0, 57)}…` : ep;
              return (
                <div
                  key={s.id || ep}
                  className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs flex items-start justify-between gap-3"
                >
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div className="font-mono text-foreground truncate" title={ep}>
                      {shortEp}
                    </div>
                    {s.user_agent && (
                      <div className="text-muted-foreground truncate" title={s.user_agent}>
                        {s.user_agent}
                      </div>
                    )}
                    {created && (
                      <div className="text-muted-foreground/70">Created: {created}</div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteSub(ep)}
                    className="shrink-0 h-7 px-2 rounded-md border border-destructive/40 text-destructive hover:bg-destructive/10 flex items-center gap-1"
                    aria-label="Delete subscription"
                  >
                    <Trash2 size={12} />
                    Delete
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
