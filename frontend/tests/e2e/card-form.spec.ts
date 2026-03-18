import { test, expect } from '@playwright/test';

test.describe('Card Form', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.app-container', { timeout: 10000 });
  });

  test('Card form appears when clicking New Card button', async ({ page }) => {
    await page.keyboard.press('Control+2');
    await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 5000 });
    const addCardBtn = page.locator('.kanban-add-btn');
    await expect(addCardBtn).toBeVisible({ timeout: 5000 });
    await addCardBtn.click();
    const cardForm = page.locator('[data-testid="card-form"]');
    await expect(cardForm).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="card-title-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-description-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-agent-select"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-priority-select"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-status-pills"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-form-submit"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-form-cancel"]')).toBeVisible();
  });

  test('Card form validates required title', async ({ page }) => {
    await page.keyboard.press('Control+2');
    await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 5000 });
    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.click('[data-testid="card-form-submit"]');
      const titleError = page.locator('[data-testid="card-title-error"]');
      await expect(titleError).toContainText('Title is required');
    }
  });

  test('Card form cancel returns to kanban', async ({ page }) => {
    await page.keyboard.press('Control+2');
    await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 5000 });
    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.click('[data-testid="card-form-cancel"]');
      await expect(page.locator('[data-testid="kanban-board"]')).toBeVisible({ timeout: 5000 });
    }
  });

  test('Card form has all 7 agent options', async ({ page }) => {
    await page.keyboard.press('Control+2');
    await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 5000 });
    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.waitForSelector('[data-testid="card-form"]', { timeout: 5000 });
      const agentSelect = page.locator('[data-testid="card-agent-select"]');
      const options = await agentSelect.locator('option').allTextContents();
      expect(options).toHaveLength(7);
      expect(options).toContain('🔥 Ember');
      expect(options).toContain('💻 Codeuse');
      expect(options).toContain('🧪 QA/Tester');
    }
  });

  test('Card form status pills are clickable', async ({ page }) => {
    await page.keyboard.press('Control+2');
    await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 5000 });
    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.waitForSelector('[data-testid="card-form"]', { timeout: 5000 });
      const ideaPill = page.locator('.status-pill[data-status="idea"]');
      await expect(ideaPill).toHaveClass(/active/);
      const todoPill = page.locator('.status-pill[data-status="todo"]');
      await todoPill.click();
      await expect(todoPill).toHaveClass(/active/);
      await expect(ideaPill).not.toHaveClass(/active/);
    }
  });
});
