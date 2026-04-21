/**
 * pushService — Web Push subscription client.
 *
 * Wraps the Notification API + PushManager flow and mirrors subscriptions to
 * the backend so the server can deliver push events (worker done, autonomy
 * heartbeat, ...) via VAPID.
 *
 * Usage:
 *   if (isPushSupported()) await enablePush();
 *   await ensureRegistered();  // safe to call on every mount
 */

import { authFetch } from '../lib/authClient';
import { apiFetch } from '../lib/apiClient';

const LS_ENDPOINT_KEY = 'voxyflow.push.endpoint';

// ── Types ──────────────────────────────────────────────────────────────────

export interface PushSubscriptionRow {
  id: string;
  endpoint: string;
  user_agent?: string | null;
  created?: string | null;
  created_at?: string | null;
}

export type EnableResult = { ok: true } | { ok: false; reason: string };

// ── Helpers ────────────────────────────────────────────────────────────────

/** Decode a base64url-encoded VAPID public key to a Uint8Array. */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = window.atob(base64);
  // Allocate a fresh ArrayBuffer (not SharedArrayBuffer) so the result is
  // accepted by PushManager.subscribe which requires BufferSource<ArrayBuffer>.
  const buffer = new ArrayBuffer(raw.length);
  const output = new Uint8Array(buffer);
  for (let i = 0; i < raw.length; i++) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}

// ── Capability / permission ────────────────────────────────────────────────

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  );
}

export function getPermission(): NotificationPermission {
  if (!isPushSupported()) return 'denied';
  return Notification.permission;
}

// ── Enable / disable ───────────────────────────────────────────────────────

export async function enablePush(): Promise<EnableResult> {
  if (!isPushSupported()) {
    return { ok: false, reason: 'not-supported' };
  }

  let permission = Notification.permission;
  if (permission !== 'granted') {
    permission = await Notification.requestPermission();
  }
  if (permission !== 'granted') {
    return { ok: false, reason: 'permission-denied' };
  }

  let publicKey: string;
  try {
    const resp = await apiFetch<{ public_key: string }>('/api/push/vapid-public-key');
    publicKey = resp.public_key;
  } catch (e) {
    return { ok: false, reason: `vapid-fetch-failed: ${(e as Error).message}` };
  }

  let applicationServerKey: ArrayBuffer;
  try {
    applicationServerKey = urlBase64ToUint8Array(publicKey).buffer as ArrayBuffer;
  } catch (e) {
    return { ok: false, reason: `vapid-decode-failed: ${(e as Error).message}` };
  }

  let reg: ServiceWorkerRegistration;
  try {
    reg = await navigator.serviceWorker.ready;
  } catch (e) {
    return { ok: false, reason: `sw-not-ready: ${(e as Error).message}` };
  }

  // If a stale subscription exists (e.g. server regenerated its VAPID keypair),
  // browsers refuse to subscribe again with a different applicationServerKey.
  // Unsubscribe first so we always start clean.
  try {
    const existing = await reg.pushManager.getSubscription();
    if (existing) {
      await existing.unsubscribe();
    }
  } catch {
    /* non-fatal — subscribe() below will surface the real error */
  }

  let sub: PushSubscription;
  try {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey,
    });
  } catch (e) {
    const err = e as Error;
    return { ok: false, reason: `subscribe-failed: ${err.name || 'Error'}: ${err.message}` };
  }

  const json = sub.toJSON() as {
    endpoint?: string;
    keys?: { p256dh?: string; auth?: string };
  };

  try {
    const res = await authFetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: json.endpoint,
        keys: json.keys,
        userAgent: navigator.userAgent,
      }),
    });
    if (!res.ok) {
      return { ok: false, reason: `backend-register-failed: HTTP ${res.status}` };
    }
  } catch (e) {
    return { ok: false, reason: `backend-register-failed: ${(e as Error).message}` };
  }

  try {
    if (sub.endpoint) localStorage.setItem(LS_ENDPOINT_KEY, sub.endpoint);
  } catch {
    /* ignore storage errors */
  }

  return { ok: true };
}

export async function disablePush(): Promise<void> {
  let endpoint: string | null = null;

  if (isPushSupported()) {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        endpoint = sub.endpoint;
        try {
          await sub.unsubscribe();
        } catch {
          /* ignore — still try backend cleanup */
        }
      }
    } catch {
      /* ignore — fall back to localStorage */
    }
  }

  if (!endpoint) {
    try {
      endpoint = localStorage.getItem(LS_ENDPOINT_KEY);
    } catch {
      endpoint = null;
    }
  }

  if (endpoint) {
    try {
      await authFetch('/api/push/unsubscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint }),
      });
    } catch {
      /* ignore */
    }
  }

  try {
    localStorage.removeItem(LS_ENDPOINT_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Verify that the current browser is still subscribed.
 *
 * Idempotent, safe on every mount. Does NOT prompt for permission.
 * Returns true iff a live subscription exists and matches the cached endpoint.
 */
export async function ensureRegistered(): Promise<boolean> {
  if (!isPushSupported()) return false;
  if (Notification.permission !== 'granted') return false;

  let reg: ServiceWorkerRegistration;
  try {
    reg = await navigator.serviceWorker.ready;
  } catch {
    return false;
  }

  let sub: PushSubscription | null = null;
  try {
    sub = await reg.pushManager.getSubscription();
  } catch {
    return false;
  }

  let cached: string | null = null;
  try {
    cached = localStorage.getItem(LS_ENDPOINT_KEY);
  } catch {
    cached = null;
  }

  if (sub && sub.endpoint) {
    if (cached && cached === sub.endpoint) return true;
    // Live sub but our cache is stale — refresh cache and trust the sub.
    try {
      localStorage.setItem(LS_ENDPOINT_KEY, sub.endpoint);
    } catch {
      /* ignore */
    }
    return true;
  }

  // No live subscription — clear cache, do NOT auto-resubscribe.
  if (cached) {
    try {
      localStorage.removeItem(LS_ENDPOINT_KEY);
    } catch {
      /* ignore */
    }
  }
  return false;
}

// ── Test / listing ─────────────────────────────────────────────────────────

export async function sendTestNotification(): Promise<{ sent: number; failed: number }> {
  const res = await authFetch('/api/push/test', { method: 'POST' });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return (await res.json()) as { sent: number; failed: number };
}

export async function getSubscriptions(): Promise<PushSubscriptionRow[]> {
  const res = await apiFetch<{ subscriptions: PushSubscriptionRow[] } | PushSubscriptionRow[]>(
    '/api/push/subscriptions',
  );
  if (Array.isArray(res)) return res;
  return res?.subscriptions ?? [];
}

export async function unsubscribeByEndpoint(endpoint: string): Promise<void> {
  const res = await authFetch('/api/push/unsubscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint }),
  });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
}
