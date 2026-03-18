import { test, expect } from '@playwright/test';

test.describe('Opportunities Panel', () => {
  test('panel is visible on desktop with empty state', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Panel should exist
    const panel = page.locator('[data-testid="opportunities-panel"]');
    await expect(panel).toBeVisible();

    // Empty state should show
    await expect(panel.locator('.opportunities-empty')).toBeVisible();
    await expect(panel.locator('.opportunities-empty')).toContainText('No suggestions yet');

    // Badge should show 0
    await expect(panel.locator('.opportunities-badge')).toHaveText('0');
  });

  test('card suggestions appear in panel', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const panel = page.locator('[data-testid="opportunities-panel"]');
    await expect(panel).toBeVisible();

    // Send actionable message that triggers card suggestions
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill(
      'We need to implement user authentication with OAuth2 and add rate limiting'
    );
    await input.press('Enter');

    // Wait for opportunity card to appear in panel
    await page.waitForSelector('.opportunity-card', { timeout: 30000 });

    const cards = await panel.locator('.opportunity-card').count();
    expect(cards).toBeGreaterThanOrEqual(1);

    // Accept button should be visible
    await expect(panel.locator('.opp-accept').first()).toBeVisible();

    // Badge should reflect count
    const badge = panel.locator('.opportunities-badge');
    const badgeText = await badge.textContent();
    expect(parseInt(badgeText || '0')).toBeGreaterThanOrEqual(1);
  });

  test('dismiss removes card from panel', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const panel = page.locator('[data-testid="opportunities-panel"]');

    // Send message to trigger suggestion
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Build a REST API with authentication and caching');
    await input.press('Enter');

    // Wait for at least one opportunity card
    await page.waitForSelector('.opportunity-card', { timeout: 30000 });

    const initialCount = await panel.locator('.opportunity-card').count();
    expect(initialCount).toBeGreaterThanOrEqual(1);

    // Click dismiss on the first card
    await panel.locator('.opp-dismiss').first().click();

    // Card count should decrease
    const afterCount = await panel.locator('.opportunity-card').count();
    expect(afterCount).toBeLessThan(initialCount);
  });

  test('accept creates card and removes from panel', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const panel = page.locator('[data-testid="opportunities-panel"]');

    // Send message to trigger suggestion
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('We should add a payment integration with Stripe');
    await input.press('Enter');

    // Wait for opportunity card
    await page.waitForSelector('.opportunity-card', { timeout: 30000 });

    const initialCount = await panel.locator('.opportunity-card').count();

    // Click accept on the first card
    await panel.locator('.opp-accept').first().click();

    // Card should be removed from panel
    const afterCount = await panel.locator('.opportunity-card').count();
    expect(afterCount).toBeLessThan(initialCount);

    // Toast should confirm card creation
    await expect(page.locator('.toast').last()).toContainText('Card created');
  });

  test('mobile: panel is hidden and toggle works', async ({ page }) => {
    // Set mobile viewport
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Panel container should be off-screen (not visible)
    const container = page.locator('.opportunities-container');
    await expect(container).not.toBeInViewport();

    // Toggle button should be visible
    const toggle = page.locator('[data-testid="opportunities-toggle"]');
    await expect(toggle).toBeVisible();

    // Click toggle to open drawer
    await toggle.click();

    // Panel should now be visible
    await expect(container).toHaveClass(/open/);

    // Click toggle again to close
    await toggle.click();
    await expect(container).not.toHaveClass(/open/);
  });
});
