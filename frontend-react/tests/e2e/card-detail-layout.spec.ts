import { test, expect } from '@playwright/test';

/**
 * Card Detail Modal — layout balance tests.
 *
 * Verifies that the three-column layout (description | chat | sidebar)
 * renders with reasonable proportions on a desktop viewport.
 *
 * Prerequisites: backend running on :8000, at least one project with cards.
 */

test.describe('Card Detail Modal Layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  /**
   * Open the first visible card on the kanban board to trigger the modal.
   */
  async function openFirstCard(page: import('@playwright/test').Page) {
    // Wait for the kanban board
    const board = page.locator('[data-testid="kanban-board"]');
    await expect(board).toBeVisible({ timeout: 10_000 });

    // Click the first card element in any column
    const firstCard = board.locator('[draggable="true"]').first();
    await expect(firstCard).toBeVisible({ timeout: 5_000 });
    await firstCard.click();

    // Wait for the card detail modal body to appear
    const body = page.locator('[data-testid="card-detail-body"]');
    await expect(body).toBeVisible({ timeout: 5_000 });
  }

  test('Three columns are visible on desktop', async ({ page }) => {
    await openFirstCard(page);

    const description = page.locator('[data-testid="card-detail-description"]');
    const chat = page.locator('[data-testid="card-detail-chat"]');
    const sidebar = page.locator('[data-testid="card-detail-sidebar"]');

    await expect(description).toBeVisible();
    await expect(chat).toBeVisible();
    await expect(sidebar).toBeVisible();
  });

  test('Sidebar is at least 400px wide', async ({ page }) => {
    await openFirstCard(page);

    const sidebar = page.locator('[data-testid="card-detail-sidebar"]');
    const box = await sidebar.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThanOrEqual(400);
  });

  test('Chat column is wider than the sidebar', async ({ page }) => {
    await openFirstCard(page);

    const chat = page.locator('[data-testid="card-detail-chat"]');
    const sidebar = page.locator('[data-testid="card-detail-sidebar"]');

    const chatBox = await chat.boundingBox();
    const sidebarBox = await sidebar.boundingBox();

    expect(chatBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();
    expect(chatBox!.width).toBeGreaterThan(sidebarBox!.width);
  });

  test('Column proportions are balanced (no column < 20% of modal)', async ({ page }) => {
    await openFirstCard(page);

    const body = page.locator('[data-testid="card-detail-body"]');
    const description = page.locator('[data-testid="card-detail-description"]');
    const chat = page.locator('[data-testid="card-detail-chat"]');
    const sidebar = page.locator('[data-testid="card-detail-sidebar"]');

    const bodyBox = await body.boundingBox();
    const descBox = await description.boundingBox();
    const chatBox = await chat.boundingBox();
    const sidebarBox = await sidebar.boundingBox();

    expect(bodyBox).not.toBeNull();
    const totalWidth = bodyBox!.width;

    // Each column should occupy at least 20% of the modal width
    expect(descBox!.width / totalWidth).toBeGreaterThanOrEqual(0.20);
    expect(chatBox!.width / totalWidth).toBeGreaterThanOrEqual(0.20);
    expect(sidebarBox!.width / totalWidth).toBeGreaterThanOrEqual(0.20);

    // Log actual proportions for debugging
    console.log('Layout proportions:', {
      description: `${((descBox!.width / totalWidth) * 100).toFixed(1)}%`,
      chat: `${((chatBox!.width / totalWidth) * 100).toFixed(1)}%`,
      sidebar: `${((sidebarBox!.width / totalWidth) * 100).toFixed(1)}%`,
    });
  });

  test('Sidebar does not overflow beyond the modal', async ({ page }) => {
    await openFirstCard(page);

    const body = page.locator('[data-testid="card-detail-body"]');
    const sidebar = page.locator('[data-testid="card-detail-sidebar"]');

    const bodyBox = await body.boundingBox();
    const sidebarBox = await sidebar.boundingBox();

    expect(bodyBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();

    // Sidebar right edge should not exceed body right edge
    const bodyRight = bodyBox!.x + bodyBox!.width;
    const sidebarRight = sidebarBox!.x + sidebarBox!.width;
    expect(sidebarRight).toBeLessThanOrEqual(bodyRight + 1); // 1px tolerance
  });
});
