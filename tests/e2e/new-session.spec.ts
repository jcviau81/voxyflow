import { test, expect } from '@playwright/test';

test.describe('New Session Button', () => {
  test('New session button clears chat', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Send a message first
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Test message');
    await input.press('Enter');
    await page.waitForTimeout(5000);

    // Click new session
    await page.locator('[data-testid="new-session-btn"]').click();

    // Chat should be cleared
    const messages = await page.locator('.message-bubble').count();
    expect(messages).toBe(0);

    // Welcome prompt should show again
    await expect(page.locator('[data-testid="welcome-prompt"]')).toBeVisible();
  });

  test('Ctrl+Shift+N keyboard shortcut triggers new session', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Send a message first
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Hello world');
    await input.press('Enter');
    await page.waitForTimeout(5000);

    // Use keyboard shortcut
    await page.keyboard.press('Control+Shift+N');
    await page.waitForTimeout(500);

    // Chat should be cleared
    const messages = await page.locator('.message-bubble').count();
    expect(messages).toBe(0);

    // Welcome prompt should show again
    await expect(page.locator('[data-testid="welcome-prompt"]')).toBeVisible();
  });
});
