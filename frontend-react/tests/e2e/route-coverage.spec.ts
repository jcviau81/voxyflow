/**
 * Route coverage smoke + stale-chunk recovery.
 *
 * 1. Every top-level route renders without tripping the router error
 *    boundary ("Unexpected Application Error!").
 * 2. lazyWithReload: when a lazy chunk request fails (simulating a tab
 *    that survived a deploy and asks for a dead chunk hash), the app
 *    reloads itself once and recovers instead of crashing.
 *
 * Prerequisites: backend on :8000. The server behind baseURL must do SPA
 * fallback (vite dev or Caddy — NOT the bare python http.server); the
 * suite skips itself when fallback is missing. Override the target with
 * PW_BASE_URL, e.g.:
 *   npm run dev -- --port 3100 &
 *   PW_BASE_URL=http://localhost:3100 npx playwright test route-coverage
 */

import { test, expect } from '@playwright/test';

if (process.env.PW_BASE_URL) {
  test.use({ baseURL: process.env.PW_BASE_URL });
}

const ROUTES = ['/', '/workspaces', '/settings', '/jobs'];

test.beforeEach(async ({ page, request, baseURL }) => {
  // Bare static servers 404 on client-side routes — nothing to test there.
  const probe = await request.get(`${baseURL}/settings`);
  test.skip(
    !probe.ok() || !(probe.headers()['content-type'] ?? '').includes('text/html'),
    `server at ${baseURL} has no SPA fallback`,
  );
  await page.addInitScript(() => {
    try {
      localStorage.setItem('onboarding_complete', 'true');
    } catch {
      /* ignore */
    }
  });
});

test.describe('Route coverage', () => {
  for (const route of ROUTES) {
    test(`renders ${route} without an application error`, async ({ page }) => {
      await page.goto(route);
      await page.waitForLoadState('networkidle');

      await expect(page.getByText('Unexpected Application Error!')).toHaveCount(0);
      await expect(page.getByText(/failed to fetch dynamically imported module/i)).toHaveCount(0);
      // The app rendered something, not a blank page.
      await expect(page.locator('#app > *').first()).toBeAttached();
    });
  }
});

test.describe('Stale chunk recovery (lazyWithReload)', () => {
  test('a failing settings chunk triggers one reload and recovers', async ({ page }) => {
    // Fail the first request for the SettingsPage module (hashed chunk in a
    // build, source module in vite dev), then let every retry through —
    // exactly what a deploy-under-an-open-tab followed by a reload looks like.
    let failed = 0;
    await page.route('**/SettingsPage*', (route) => {
      if (failed === 0) {
        failed += 1;
        return route.abort('failed');
      }
      return route.continue();
    });

    let documentLoads = 0;
    page.on('load', () => {
      documentLoads += 1;
    });

    await page.goto('/settings');
    // lazyWithReload must reload the document once after the aborted chunk.
    await expect.poll(() => documentLoads, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
    await page.waitForLoadState('networkidle');

    expect(failed).toBe(1); // the abort actually happened
    await expect(page.getByText('Unexpected Application Error!')).toHaveCount(0);
    await expect(page.getByText(/failed to fetch dynamically imported module/i)).toHaveCount(0);
    await expect(page).toHaveURL(/\/settings/);

    // Success path clears the reload guard so the next deploy can reload again.
    const flag = await page.evaluate(() => sessionStorage.getItem('voxy:chunk-reload'));
    expect(flag).toBeNull();
  });
});
