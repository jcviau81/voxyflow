import { test, expect } from '@playwright/test';

test.describe('Idea Board', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage before each test
    await page.goto('http://localhost:3000');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
  });

  test('Idea board visible in general mode', async ({ page }) => {
    await expect(page.locator('[data-testid="idea-board"]')).toBeVisible();
  });

  test('Can add idea manually', async ({ page }) => {
    await page.locator('[data-testid="add-idea-btn"]').click();
    await page.locator('.idea-input').fill('Test idea');
    await page.locator('.idea-input').press('Enter');
    await expect(page.locator('.idea-card')).toBeVisible();
    await expect(page.locator('.idea-content')).toHaveText('Test idea');
  });

  test('Can delete an idea', async ({ page }) => {
    // Add an idea first
    await page.locator('[data-testid="add-idea-btn"]').click();
    await page.locator('.idea-input').fill('Idea to delete');
    await page.locator('.idea-input').press('Enter');
    await expect(page.locator('.idea-card')).toBeVisible();

    // Hover and delete
    await page.locator('.idea-card').hover();
    await page.locator('.idea-delete').click();
    await expect(page.locator('.idea-card')).not.toBeVisible();
    await expect(page.locator('.idea-empty')).toBeVisible();
  });

  test('Shows empty state when no ideas', async ({ page }) => {
    await expect(page.locator('.idea-empty')).toBeVisible();
    await expect(page.locator('.idea-empty')).toHaveText('No ideas yet. Start brainstorming!');
  });

  test('Ideas persist across reloads', async ({ page }) => {
    // Add an idea
    await page.locator('[data-testid="add-idea-btn"]').click();
    await page.locator('.idea-input').fill('Persistent idea');
    await page.locator('.idea-input').press('Enter');
    await expect(page.locator('.idea-card')).toBeVisible();

    // Reload
    await page.reload();
    await expect(page.locator('.idea-card')).toBeVisible();
    await expect(page.locator('.idea-content')).toHaveText('Persistent idea');
  });
});
