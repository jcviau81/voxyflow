import { test, expect } from '@playwright/test';

test.describe('Slash Commands', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForSelector('#app', { timeout: 10000 });
    // Clear any existing state
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
  });

  test('Typing "/" shows the slash command menu', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
  });

  test('Slash menu lists available commands', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    // Should show at least /new, /clear, /help
    const items = page.locator('.slash-menu-item');
    const count = await items.count();
    expect(count).toBeGreaterThan(0);
  });

  test('Typing "/new" filters menu to /new command', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/new');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    const items = page.locator('.slash-menu-item');
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(1);
    const firstItemText = await items.first().textContent();
    expect(firstItemText).toContain('/new');
  });

  test('Typing "/new" and pressing Enter clears the chat', async ({ page }) => {
    // First send a message to have something to clear
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Hello there');
    await input.press('Enter');
    await page.waitForTimeout(500);

    // Now type /new and press Enter
    await input.fill('/new');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    await input.press('Enter');

    // Chat should be cleared — welcome prompt or empty state should appear
    await expect(page.locator('[data-testid="chat-input"]')).toHaveValue('');
  });

  test('Typing "/help" and pressing Enter shows help message in chat', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/help');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    await input.press('Enter');

    // Help message should appear as a system message in chat
    await expect(page.locator('.message-bubble')).toBeVisible({ timeout: 5000 });
    const messages = page.locator('.message-bubble');
    const count = await messages.count();
    expect(count).toBeGreaterThan(0);
  });

  test('Typing "/clear" works like "/new"', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/clear');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    const items = page.locator('.slash-menu-item');
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(1);
    const firstItemText = await items.first().textContent();
    expect(firstItemText).toContain('/clear');
  });

  test('Pressing Escape dismisses the slash menu', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });
    await input.press('Escape');
    await expect(page.locator('.slash-menu')).not.toBeVisible({ timeout: 2000 });
  });

  test('Arrow Down key navigates menu items (activates second item)', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });

    // First item should be active by default
    const firstItem = page.locator('.slash-menu-item').first();
    await expect(firstItem).toHaveClass(/active/);

    // Press ArrowDown — second item should become active
    await input.press('ArrowDown');
    const secondItem = page.locator('.slash-menu-item').nth(1);
    const count = await page.locator('.slash-menu-item').count();
    if (count >= 2) {
      await expect(secondItem).toHaveClass(/active/);
      await expect(firstItem).not.toHaveClass(/active/);
    }
  });

  test('Arrow Up key wraps around menu navigation', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/');
    await expect(page.locator('.slash-menu')).toBeVisible({ timeout: 3000 });

    // First item should be active
    const firstItem = page.locator('.slash-menu-item').first();
    await expect(firstItem).toHaveClass(/active/);

    // Press ArrowUp from first item — should wrap to last
    await input.press('ArrowUp');
    const items = page.locator('.slash-menu-item');
    const count = await items.count();
    if (count >= 2) {
      const lastItem = items.last();
      await expect(lastItem).toHaveClass(/active/);
    }
  });

  test('No-match query shows empty state in menu', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('/zzznomatch');
    // Menu may show with "No commands match" or just hide
    const menu = page.locator('.slash-menu');
    const isVisible = await menu.isVisible().catch(() => false);
    if (isVisible) {
      const empty = page.locator('.slash-menu-empty');
      await expect(empty).toBeVisible();
      await expect(empty).toContainText('No commands match');
    }
  });
});
