import { test, expect } from '@playwright/test';

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

test.describe('FreeBoard', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage to ensure fresh state
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // Clear backend cards so tests start with a clean board
    await clearAllMainBoardCards(page);
    // Navigate to freeboard view
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    await boardBtn.waitFor({ timeout: 5000 });
    await boardBtn.click();
    await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });
    // Wait for the grid to re-render after clearing
    await page.waitForTimeout(500);
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
    const card = page.locator('.freeboard-card-title', { hasText: 'My Test Note' });
    await expect(card).toBeVisible({ timeout: 5000 });
  });

  test('Adding a card with Enter key in title field submits the form', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    const titleInput = page.locator('.freeboard-add-form-title');
    await titleInput.fill('Quick Note');
    await titleInput.press('Enter');

    const card = page.locator('.freeboard-card-title', { hasText: 'Quick Note' });
    await expect(card).toBeVisible({ timeout: 5000 });
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
    const blueCard = page.locator('.freeboard-card--blue .freeboard-card-title', { hasText: 'Colored Note' });
    await expect(blueCard).toBeVisible({ timeout: 5000 });
  });

  test('Adding a card with no color has no color modifier class', async ({ page }) => {
    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Plain Note');
    await page.locator('.freeboard-form-submit').click();

    const card = page.locator('.freeboard-card', { hasText: 'Plain Note' }).first();
    await expect(card).toBeVisible({ timeout: 5000 });
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
    const card = page.locator('.freeboard-card', { hasText: 'Note to Delete' }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    // Hover over the card to reveal action buttons
    await card.hover();
    const deleteBtn = card.locator('.freeboard-card-btn--delete');
    await expect(deleteBtn).toBeVisible({ timeout: 3000 });
    await deleteBtn.click();

    // Card should be gone
    await expect(page.locator('.freeboard-card', { hasText: 'Note to Delete' })).not.toBeVisible({ timeout: 5000 });
  });

  test('Empty state shows when no cards exist', async ({ page }) => {
    // Board was cleared in beforeEach; reload to pick up empty state
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    await page.waitForSelector('[data-testid="unified-header"]', { timeout: 10000 });
    // Navigate to freeboard — the button may already be visible or we may already be there
    const freeboard = page.locator('[data-testid="freeboard"]');
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    if (!await freeboard.isVisible({ timeout: 2000 }).catch(() => false)) {
      await boardBtn.waitFor({ timeout: 10000 });
      await boardBtn.click();
      await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });
    }

    const emptyState = page.locator('.freeboard-empty');
    await expect(emptyState).toBeVisible({ timeout: 3000 });
    await expect(emptyState).toContainText('No cards yet');
  });

  test('Empty state disappears after adding a card', async ({ page }) => {
    // Reload to see empty state
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    await page.waitForSelector('[data-testid="unified-header"]', { timeout: 10000 });
    // Navigate to freeboard
    const freeboard = page.locator('[data-testid="freeboard"]');
    const boardBtn = page.locator('[data-testid="general-view-toggle"] [data-view="freeboard"]');
    if (!await freeboard.isVisible({ timeout: 2000 }).catch(() => false)) {
      await boardBtn.waitFor({ timeout: 10000 });
      await boardBtn.click();
      await page.waitForSelector('[data-testid="freeboard"]', { timeout: 5000 });
    }

    await expect(page.locator('.freeboard-empty')).toBeVisible({ timeout: 8000 });

    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('First Note');
    await page.locator('.freeboard-form-submit').click();

    await expect(page.locator('.freeboard-empty')).not.toBeVisible({ timeout: 5000 });
  });

  test('Cancel button hides the add form without adding a card', async ({ page }) => {
    // Count existing cards before
    const cardCountBefore = await page.locator('.freeboard-card').count();

    await page.locator('[data-testid="freeboard-add-btn"]').click();
    await page.locator('.freeboard-add-form-title').fill('Cancelled Note');
    await page.locator('.freeboard-form-cancel').click();

    await expect(page.locator('.freeboard-add-form')).not.toBeVisible({ timeout: 2000 });
    // No new card with that title should appear
    await expect(page.locator('.freeboard-card', { hasText: 'Cancelled Note' })).not.toBeVisible();
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
    const card = page.locator('.freeboard-card', { hasText: 'Promotable Note' }).first();
    await expect(card).toBeVisible({ timeout: 5000 });

    await card.hover();
    await expect(card.locator('.freeboard-card-btn--promote')).toBeVisible({ timeout: 3000 });
  });
});
