import { test, expect } from '@playwright/test';

test.describe('Welcome Flow', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to ensure fresh state (empty chat)
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.clear();
    });
    await page.reload();
  });

  test('General welcome prompt shows on empty chat', async ({ page }) => {
    await expect(page.locator('[data-testid="welcome-prompt"]')).toBeVisible();

    // Should have 4 action buttons
    const buttons = page.locator('.welcome-btn');
    await expect(buttons).toHaveCount(4);

    // Check action buttons exist
    await expect(page.locator('[data-action="chat"]')).toBeVisible();
    await expect(page.locator('[data-action="existing-project"]')).toBeVisible();
    await expect(page.locator('[data-action="brainstorm"]')).toBeVisible();
    await expect(page.locator('[data-action="review"]')).toBeVisible();
  });

  test('General welcome hides on "Just chatting" click', async ({ page }) => {
    await expect(page.locator('[data-testid="welcome-prompt"]')).toBeVisible();

    await page.locator('[data-action="chat"]').click();

    // Welcome should disappear (with animation)
    await expect(page.locator('[data-testid="welcome-prompt"]')).not.toBeVisible({ timeout: 2000 });
  });

  test('Welcome hides when user starts typing', async ({ page }) => {
    await expect(page.locator('[data-testid="welcome-prompt"]')).toBeVisible();

    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('hello');

    await expect(page.locator('[data-testid="welcome-prompt"]')).not.toBeVisible({ timeout: 2000 });
  });

  test('Welcome prompt does not show when messages exist', async ({ page }) => {
    // Send a message first to populate history
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('test message');
    await input.press('Enter');

    // Reload page
    await page.reload();

    // Welcome should NOT show since there are messages
    await expect(page.locator('[data-testid="welcome-prompt"]')).not.toBeVisible({ timeout: 2000 });
  });
});

test.describe('Layer Toggles', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
  });

  test('Layer toggle checkboxes are visible', async ({ page }) => {
    const opusToggle = page.locator('[data-testid="layer-toggle-opus"]');
    const analyzerToggle = page.locator('[data-testid="layer-toggle-analyzer"]');

    await expect(opusToggle).toBeVisible();
    await expect(analyzerToggle).toBeVisible();

    // Both should be checked by default
    await expect(opusToggle).toBeChecked();
    await expect(analyzerToggle).toBeChecked();
  });

  test('Layer toggles persist to localStorage', async ({ page }) => {
    const opusToggle = page.locator('[data-testid="layer-toggle-opus"]');

    // Uncheck Opus
    await opusToggle.uncheck();
    await expect(opusToggle).not.toBeChecked();

    // Check localStorage
    const stored = await page.evaluate(() => {
      return JSON.parse(localStorage.getItem('voxyflow_layer_toggles') || '{}');
    });
    expect(stored.opus).toBe(false);
    expect(stored.analyzer).toBe(true);

    // Reload page — toggle state should persist
    await page.reload();
    const opusToggleAfter = page.locator('[data-testid="layer-toggle-opus"]');
    await expect(opusToggleAfter).not.toBeChecked();
  });

  test('Haiku has no toggle checkbox', async ({ page }) => {
    // The model status bar should exist
    await expect(page.locator('[data-testid="model-status-bar"]')).toBeVisible();

    // There should be no toggle with data-layer="haiku"
    const haikuToggle = page.locator('.layer-toggle[data-layer="haiku"]');
    await expect(haikuToggle).toHaveCount(0);
  });
});
