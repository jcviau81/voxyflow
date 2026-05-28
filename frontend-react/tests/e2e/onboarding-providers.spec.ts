/**
 * Onboarding "Models & Providers" explainer step — Playwright e2e tests.
 *
 * Verifies the refactored onboarding flow (replaces the legacy
 * "LLM API URL + fake API key" form):
 *   - Step 1 (identity) navigates to Step 2 (providers explainer)
 *   - Step 2 renders the two cards (My Providers + Worker Classes)
 *   - "Configure providers" / "Configure worker classes" buttons open the
 *     reused Settings ModelPanel inside a dialog (drawer pattern)
 *   - Dialog can be dismissed and the user stays in the onboarding flow
 *   - The ✓ "configured" badge appears once endpoints.length >= 1
 *   - "Skip for now" finalises onboarding and routes to /
 *
 * The vocabulary is locked: "Models & Providers", "My Providers",
 * "Worker Classes" — and the obsolete "My Machines" copy must NOT appear.
 *
 * Prerequisites: backend running on :8000, frontend served on :18789.
 * The test forces the onboarding screen by clearing the local storage flag
 * before each test.
 */

import { test, expect, type Page, type Route } from '@playwright/test';

const LEGACY_COPY_FORBIDDEN = ['My Machines', 'myMachines'];

async function gotoOnboarding(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem('onboarding_complete');
      localStorage.removeItem('voxyflow_settings');
    } catch {
      /* ignore */
    }
  });
  await page.goto('/onboarding');
  await page.waitForLoadState('networkidle');
}

async function advanceToProvidersStep(page: Page) {
  // Fill identity step then click Continue.
  await page.getByPlaceholder('What should I call you?').fill('JC');
  await page.getByTestId('onboarding-identity-next').click();
  await expect(page.getByTestId('onboarding-providers-step')).toBeVisible();
}

test.describe('Onboarding · Models & Providers explainer', () => {
  test('renders the two explainer cards with correct copy', async ({ page }) => {
    await gotoOnboarding(page);
    await advanceToProvidersStep(page);

    // Cards present
    await expect(page.getByTestId('onboarding-card-my-providers')).toBeVisible();
    await expect(page.getByTestId('onboarding-card-worker-classes')).toBeVisible();

    // Locked vocabulary
    await expect(page.getByText('Models & Providers').first()).toBeVisible();
    await expect(page.getByText('My Providers').first()).toBeVisible();
    await expect(page.getByText('Worker Classes').first()).toBeVisible();

    // Obsolete copy must NOT appear
    for (const forbidden of LEGACY_COPY_FORBIDDEN) {
      await expect(page.getByText(forbidden, { exact: false })).toHaveCount(0);
    }
  });

  test('"Configure providers" opens the Models & Providers dialog', async ({ page }) => {
    await gotoOnboarding(page);
    await advanceToProvidersStep(page);

    await page.getByTestId('onboarding-btn-configure-providers').click();

    const dialog = page.getByTestId('onboarding-providers-dialog');
    await expect(dialog).toBeVisible();
    // Dialog embeds the actual Settings ModelPanel
    await expect(dialog.getByTestId('settings-models')).toBeVisible();

    // Closing the dialog keeps the user on the onboarding step
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(page.getByTestId('onboarding-providers-step')).toBeVisible();
  });

  test('"Configure worker classes" opens the dialog scrolled to Worker Classes', async ({ page }) => {
    await gotoOnboarding(page);
    await advanceToProvidersStep(page);

    await page.getByTestId('onboarding-btn-configure-worker-classes').click();
    const dialog = page.getByTestId('onboarding-providers-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('[data-section="worker-classes"]')).toBeVisible();
  });

  test('badge ✓ "configured" appears when endpoints.length >= 1', async ({ page }) => {
    // Stub /api/settings to return one declared endpoint
    await page.route('**/api/settings', async (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            onboarding_complete: false,
            models: {
              endpoints: [
                {
                  id: 'ep-1',
                  name: 'Brain',
                  provider_type: 'ollama',
                  url: 'http://10.0.0.1:11434',
                  api_key: '',
                },
              ],
            },
          }),
        });
      }
      return route.continue();
    });

    await gotoOnboarding(page);
    await advanceToProvidersStep(page);

    await expect(page.getByTestId('onboarding-badge-configured')).toBeVisible();
  });

  test('"Skip for now" finalises onboarding and routes home', async ({ page }) => {
    // Capture the PUT /api/settings call so we can assert the legacy
    // "api_key: sk-any" payload is NOT being sent.
    let putBody: string | null = null;
    await page.route('**/api/settings', async (route: Route) => {
      if (route.request().method() === 'PUT') {
        putBody = route.request().postData();
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ok: true }),
        });
      }
      return route.continue();
    });

    await gotoOnboarding(page);
    await advanceToProvidersStep(page);

    await page.getByTestId('onboarding-btn-skip').click();
    await page.waitForURL((url) => !url.pathname.startsWith('/onboarding'), { timeout: 5_000 });

    // Legacy fake-key payload should not leak into the new flow.
    if (putBody) {
      expect(putBody).not.toContain('sk-any');
      expect(putBody).not.toContain('http://localhost:3457/v1');
    }
  });
});
