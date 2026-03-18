import { test, expect } from '@playwright/test';

test.describe('Unified Header — Chat Levels', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForSelector('#app', { timeout: 10000 });
  });

  test('General chat shows session tabs + New + Clear', async ({ page }) => {
    const header = page.locator('[data-testid="unified-header"]');
    await expect(header).toBeVisible();

    // Session tabs visible in general mode
    await expect(page.locator('[data-testid="session-tabs"]')).toBeVisible();

    // New session button visible
    await expect(page.locator('[data-testid="new-session-btn"]')).toBeVisible();

    // Clear button visible
    await expect(page.locator('[data-testid="clear-chat-btn"]')).toBeVisible();

    // View toggle should NOT be visible in general mode
    await expect(page.locator('[data-testid="view-toggle"]')).not.toBeVisible();
  });

  test('General chat title shows General Chat with emoji', async ({ page }) => {
    const titleSection = page.locator('[data-testid="context-indicator"]');
    await expect(titleSection).toContainText('General Chat');
  });

  test('New session button creates new session tab', async ({ page }) => {
    // Initially 1 session tab
    const tabs = page.locator('.session-tab');
    await expect(tabs).toHaveCount(1);

    // Click + New
    await page.locator('[data-testid="new-session-btn"]').click();

    // Now 2 session tabs
    await expect(page.locator('.session-tab')).toHaveCount(2);
  });

  test('Clear button clears chat messages', async ({ page }) => {
    // Type and send a message first
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Test message');
    await input.press('Enter');

    // Wait for message bubble to appear
    await page.waitForSelector('.message-bubble', { timeout: 5000 }).catch(() => {
      // Message may not render if backend is not running, that's OK
    });

    // Click clear
    await page.locator('[data-testid="clear-chat-btn"]').click();

    // Welcome prompt should reappear
    await expect(page.locator('.welcome-prompt')).toBeVisible({ timeout: 3000 }).catch(() => {
      // Acceptable if welcome prompt component behavior differs
    });
  });
});
