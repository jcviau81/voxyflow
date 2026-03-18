import { test, expect } from '@playwright/test';

test.describe('FreeBoard', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to ensure fresh state
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // Navigate to freeboard view
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    await boardBtn.waitFor({ timeout: 5000 });
    await boardBtn.click();
    await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });
  });

  test('FreeBoard renders in general chat view', async ({ page }) => {
    const board = page.locator('[data-testid="freeboard"]');
    await expect(board).toBeVisible({ timeout: 5000 });
  });

  test('"+ Add" button is visible on the FreeBoard', async ({ page }) => {
    const addBtn = page.locator('[data-testid="freeboard-add-btn"]');
    await expect(addBtn).toBeVisible({ timeout: 5000 });
    await expect(addBtn).toContainText('Add');
  });

  test('"+ Add" button shows the quick-add form', async ({ page }) => {
    const addBtn = page.locator('[data-testid="freeboard-add-btn"]');
    await addBtn.click();
    await expect(page.locator('.freeboard-add-form')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('.freeboard-add-form-title')).toBeVisible();
  });

  test('Add form contains title input, body textarea, and color swatches', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await expect(page.locator('.freeboard-add-form-title')).toBeVisible();
    await expect(page.locator('.freeboard-add-form-body')).toBeVisible();
    await expect(page.locator('.freeboard-color-row')).toBeVisible();
    await expect(page.locator('.freeboard-form-submit')).toBeVisible();
    await expect(page.locator('.freeboard-form-cancel')).toBeVisible();
  });

  test('Adding a card with a title shows it in the grid', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    const titleInput = page.locator('.freeboard-add-form-title');
    await titleInput.fill('My Test Note');
    await page.locator('.freeboard-form-submit').click();

    // Card should appear in grid
    await expect(page.locator('.freeboard-card')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('.freeboard-card-title')).toContainText('My Test Note');
  });

  test('Adding a card with Enter key in title field submits the form', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    const titleInput = page.locator('.freeboard-add-form-title');
    await titleInput.fill('Quick Note');
    await titleInput.press('Enter');

    await expect(page.locator('.freeboard-card')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('.freeboard-card-title')).toContainText('Quick Note');
  });

  test('Adding a card with a color sets the correct color class', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Colored Note');

    // Click the "blue" color swatch
    const blueSwatch = page.locator('.freeboard-color-swatch--blue');
    await blueSwatch.click();
    await expect(blueSwatch).toHaveClass(/selected/);

    await page.locator('.freeboard-form-submit').click();

    // Card should have the blue color class
    await expect(page.locator('.freeboard-card--blue')).toBeVisible({ timeout: 3000 });
  });

  test('Adding a card with no color has no color modifier class', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Plain Note');
    await page.locator('.freeboard-form-submit').click();

    const card = page.locator('.freeboard-card').first();
    await expect(card).toBeVisible({ timeout: 3000 });
    // Should not have any color modifier class
    await expect(card).not.toHaveClass(/freeboard-card--yellow/);
    await expect(card).not.toHaveClass(/freeboard-card--blue/);
    await expect(card).not.toHaveClass(/freeboard-card--green/);
  });

  test('Deleting a card removes it from the board', async ({ page }) => {
    // Add a card first
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Note to Delete');
    await page.locator('.freeboard-form-submit').click();
    await expect(page.locator('.freeboard-card')).toBeVisible({ timeout: 3000 });

    // Hover over the card to reveal action buttons
    await page.locator('.freeboard-card').hover();
    const deleteBtn = page.locator('.freeboard-card-btn--delete').first();
    await expect(deleteBtn).toBeVisible({ timeout: 3000 });
    await deleteBtn.click();

    // Card should be gone
    await expect(page.locator('.freeboard-card')).not.toBeVisible({ timeout: 3000 });
  });

  test('Empty state shows when no cards exist', async ({ page }) => {
    const emptyState = page.locator('.freeboard-empty');
    await expect(emptyState).toBeVisible({ timeout: 3000 });
    await expect(emptyState).toContainText('No notes yet');
  });

  test('Empty state disappears after adding a card', async ({ page }) => {
    await expect(page.locator('.freeboard-empty')).toBeVisible({ timeout: 3000 });

    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('First Note');
    await page.locator('.freeboard-form-submit').click();

    await expect(page.locator('.freeboard-empty')).not.toBeVisible({ timeout: 3000 });
  });

  test('Cancel button hides the add form without adding a card', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Cancelled Note');
    await page.locator('.freeboard-form-cancel').click();

    await expect(page.locator('.freeboard-add-form')).not.toBeVisible({ timeout: 2000 });
    await expect(page.locator('.freeboard-card')).not.toBeVisible();
  });

  test('Escape key in title input closes the form', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await expect(page.locator('.freeboard-add-form')).toBeVisible({ timeout: 3000 });
    await page.locator('.freeboard-add-form-title').press('Escape');
    await expect(page.locator('.freeboard-add-form')).not.toBeVisible({ timeout: 2000 });
  });

  test('Promote button is present on each card', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Promotable Note');
    await page.locator('.freeboard-form-submit').click();
    await expect(page.locator('.freeboard-card')).toBeVisible({ timeout: 3000 });

    await page.locator('.freeboard-card').hover();
    await expect(page.locator('.freeboard-card-btn--promote')).toBeVisible({ timeout: 3000 });
  });
});
