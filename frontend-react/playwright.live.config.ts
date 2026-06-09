import { defineConfig, devices } from '@playwright/test';

/**
 * Live scenario config — drives the REAL deployed app (backend-served prod
 * bundle on :8000), not the Vite dev server. Used for end-to-end QA scenarios
 * that exercise the dispatcher, real workers (claude CLI), and realtime UI.
 *
 * Run: npx playwright test --config=playwright.live.config.ts
 * Requires: backend up on :8000, claude CLI logged in (workers).
 */
export default defineConfig({
  testDir: './tests/scenarios',
  fullyParallel: false,        // serial — don't hammer the LLM concurrently
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  timeout: 5 * 60_000,         // worker delegations can take minutes
  expect: { timeout: 20_000 },
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report-live' }]],
  outputDir: 'test-results-live',
  use: {
    baseURL: process.env.LIVE_BASE_URL || 'http://localhost:8000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
});
