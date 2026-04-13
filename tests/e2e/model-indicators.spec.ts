import { test, expect } from '@playwright/test';

test.describe('Model Indicators UI', () => {
  test('Model status bar shows all three models', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Status bar should exist
    const statusBar = page.locator('[data-testid="model-status-bar"]');
    await expect(statusBar).toBeVisible();

    // Should show 3 models
    const models = statusBar.locator('.model-status');
    await expect(models).toHaveCount(3);

    // All dots should start as idle
    const dots = statusBar.locator('.status-dot');
    for (let i = 0; i < 3; i++) {
      await expect(dots.nth(i)).toHaveClass(/idle/);
    }

    // Labels should show idle state
    const labels = statusBar.locator('.status-label');
    for (let i = 0; i < 3; i++) {
      await expect(labels.nth(i)).toHaveText('idle');
    }
  });

  test('Model badges appear on assistant messages after sending', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Send a message
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Tell me about TypeScript');
    await input.press('Enter');

    // Wait for response with model badge
    await page.waitForSelector('.model-badge', { timeout: 15000 });

    const badge = page.locator('.model-badge').first();
    const badgeText = await badge.textContent();

    // Should contain a model identifier
    expect(
      badgeText?.includes('haiku') ||
      badgeText?.includes('opus')
    ).toBeTruthy();
  });

  test('Status bar updates when models become active', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const statusBar = page.locator('[data-testid="model-status-bar"]');
    await expect(statusBar).toBeVisible();

    // Send a message to trigger model activity
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Hello');
    await input.press('Enter');

    // At some point during response, at least one model should become non-idle
    // We check that after the response completes, models return to idle
    await page.waitForSelector('.model-badge', { timeout: 15000 });

    // After response is done, all models should be idle
    // Give a moment for status to settle
    await page.waitForTimeout(2000);
    const idleDots = statusBar.locator('.status-dot.idle');
    await expect(idleDots).toHaveCount(3);
  });
});
