/// <reference lib="webworker" />
import { precacheAndRoute, cleanupOutdatedCaches } from 'workbox-precaching';
import { registerRoute } from 'workbox-routing';
import { NetworkFirst } from 'workbox-strategies';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>;
};

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

registerRoute(
  ({ url }) => /\.(?:js|css)$/.test(url.pathname),
  new NetworkFirst({ cacheName: 'assets-v2', networkTimeoutSeconds: 5 })
);

interface PushPayload {
  title?: string;
  body?: string;
  url?: string;
  icon?: string;
  tag?: string;
}

self.addEventListener('push', (event: PushEvent) => {
  if (!event.data) return;
  let data: PushPayload = {};
  try {
    data = event.data.json();
  } catch {
    data = { title: 'Voxyflow', body: event.data.text() };
  }
  const { title, body, url, icon, tag } = data;
  event.waitUntil(
    self.registration.showNotification(title || 'Voxyflow', {
      body: body || '',
      icon: icon || '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: url || '/' },
      tag: tag || 'voxyflow',
    })
  );
});

self.addEventListener('notificationclick', (event: NotificationEvent) => {
  event.notification.close();
  const url = (event.notification.data?.url as string) || '/';
  event.waitUntil(
    (async () => {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const c of all) {
        if ('focus' in c) {
          try {
            await (c as WindowClient).navigate(url);
          } catch {
            /* ignore */
          }
          return (c as WindowClient).focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
      return undefined;
    })()
  );
});

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event: ExtendableEvent) => {
  event.waitUntil(self.clients.claim());
});
