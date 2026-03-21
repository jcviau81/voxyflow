import { test, expect } from '@playwright/test';

// Note: The IdeaBoard component was replaced by FreeBoard.
// These tests have been updated to use the FreeBoard component.
// See freeboard.spec.ts for comprehensive FreeBoard tests.

/**
 * Helper: delete all unassigned cards via the API to get a clean state.
 */
async function clearAllMainBoardCards(page: import('@playwright/test').Page) {
  await page.evaluate(async () => {
    const res = await fetch('/api/cards/unassigned');
    if (!res.ok) return;
    const cards = await res.json();
    for (const card of cards) {
      await fetch(`/api/cards/${card.id}`, { method: 'DELETE' });
    }
  });
}

test.describe('Idea Board', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage before each test
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // Clear backend cards for clean state
    await clearAllMainBoardCards(page);
    // Navigate to freeboard view (replaced IdeaBoard)
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    await boardBtn.waitFor({ timeout: 5000 });
    await boardBtn.click();
    await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });
    await page.waitForTimeout(500);
  });

  test('Idea board visible in general mode', async ({ page }) => {
    await expect(page.locator('[data-testid="freeboard"]')).toBeVisible();
  });

  test('Can add idea manually', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Test idea');
    await page.locator('.freeboard-add-form-title').press('Enter');
    const card = page.locator('.freeboard-card-title', { hasText: 'Test idea' });
    await expect(card).toBeVisible({ timeout: 5000 });
  });

  test('Can delete an idea', async ({ page }) => {
    // Add an idea first
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Idea to delete');
    await page.locator('.freeboard-add-form-title').press('Enter');
    const card = page.locator('.freeboard-card', { hasText: 'Idea to delete' }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Hover and delete
    await card.hover();
    await card.locator('.freeboard-card-btn--delete').click({ force: true });
    await expect(page.locator('.freeboard-card', { hasText: 'Idea to delete' })).not.toBeVisible({ timeout: 5000 });
  });

  test('Shows empty state when no ideas', async ({ page }) => {
    // Reload to pick up empty state after clearing
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    await boardBtn.waitFor({ timeout: 5000 });
    await boardBtn.click();
    await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });

    const emptyState = page.locator('.freeboard-empty');
    await expect(emptyState).toBeVisible({ timeout: 5000 });
    await expect(emptyState).toContainText('No cards yet');
  });

  test('Ideas persist across reloads', async ({ page }) => {
    // Add an idea
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Persistent idea');
    await page.locator('.freeboard-add-form-title').press('Enter');
    const card = page.locator('.freeboard-card-title', { hasText: 'Persistent idea' });
    await expect(card).toBeVisible({ timeout: 5000 });

    // Reload — freeboard view persists in localStorage
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // App should restore to freeboard view, or we can navigate there
    const freeboard = page.locator('[data-testid="freeboard"]');
    const generalToggle = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    // Wait for either freeboard or the nav button to appear
    await Promise.race([
      freeboard.waitFor({ timeout: 5000 }).catch(() => null),
      generalToggle.waitFor({ timeout: 5000 }).catch(() => null),
    ]);
    // If not already on freeboard, navigate there
    if (!await freeboard.isVisible()) {
      await generalToggle.click();
      await freeboard.waitFor({ timeout: 5000 });
    }

    await expect(page.locator('.freeboard-card-title', { hasText: 'Persistent idea' })).toBeVisible({ timeout: 5000 });
  });
});
