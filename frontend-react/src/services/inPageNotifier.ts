/**
 * inPageNotifier — best-effort in-page browser notifications.
 *
 * Complements the Web Push flow so notifications still fire in browsers
 * without working GCM (e.g. Brave on Linux) whenever the Voxyflow tab is
 * open. Uses the same `tag` as Web Push so browsers dedupe if both arrive.
 */

export interface InPageNotificationOpts {
  title: string;
  body: string;
  url?: string;
  tag?: string;
  icon?: string;
}

export async function showInPageNotification(opts: InPageNotificationOpts): Promise<void> {
  if (typeof window === 'undefined' || !('Notification' in window)) return;
  if (Notification.permission !== 'granted') return;

  try {
    const n = new Notification(opts.title, {
      body: opts.body,
      tag: opts.tag,
      icon: opts.icon || '/icon-192.png',
      data: { url: opts.url },
    });
    n.onclick = () => {
      try {
        window.focus();
        const target = opts.url;
        if (target && target !== window.location.pathname + window.location.search) {
          window.location.href = target;
        }
      } catch {
        /* ignore — onclick is best-effort */
      }
      n.close();
    };
  } catch {
    /* some browsers throw (non-visible tab, missing SW, etc.) — swallow */
  }
}
