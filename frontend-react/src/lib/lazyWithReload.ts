import { lazy } from 'react';
import type { ComponentType, LazyExoticComponent } from 'react';

const RELOAD_FLAG = 'voxy:chunk-reload';

/**
 * `React.lazy` that survives deploys.
 *
 * Hashed chunk filenames change on every build, so a tab loaded before a
 * deploy fails with "Failed to fetch dynamically imported module" when it
 * first visits a lazy route afterwards. On that failure, reload the page
 * once to pick up the new index.html; the sessionStorage flag prevents a
 * reload loop when the import fails for a different reason (e.g. offline).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- mirrors React.lazy's own constraint
export function lazyWithReload<T extends ComponentType<any>>(
  factory: () => Promise<{ default: T }>,
): LazyExoticComponent<T> {
  return lazy(async () => {
    try {
      const mod = await factory();
      sessionStorage.removeItem(RELOAD_FLAG);
      return mod;
    } catch (err) {
      if (!sessionStorage.getItem(RELOAD_FLAG)) {
        sessionStorage.setItem(RELOAD_FLAG, '1');
        window.location.reload();
        // The page is reloading — keep Suspense showing its fallback.
        return new Promise<{ default: T }>(() => {});
      }
      throw err;
    }
  });
}
