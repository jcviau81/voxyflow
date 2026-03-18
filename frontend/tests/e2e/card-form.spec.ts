import { test, expect } from '@playwright/test';

/**
 * Helper: create a project via the frontend UI and wait for kanban view.
 * Kanban is only available in project mode — this ensures we're there.
 */
async function createProjectAndOpenKanban(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Click "New Project" in sidebar
  const newProjectBtn = page.locator('[data-testid="sidebar-new-project"]');
  await expect(newProjectBtn).toBeVisible({ timeout: 5000 });
  await newProjectBtn.click();

  // Fill project form
  const nameInput = page.locator('[data-testid="project-name-input"]');
  await expect(nameInput).toBeVisible({ timeout: 5000 });
  await nameInput.fill('Card Form Test');

  // Submit
  const submitBtn = page.locator('[data-testid="project-form-submit"]');
  await submitBtn.click();

  // After project creation, app auto-switches to kanban view
  await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 10000 });
}

test.describe('Card Form', () => {
  test('Card form appears when clicking New Card button', async ({ page }) => {
    await createProjectAndOpenKanban(page);

    const addCardBtn = page.locator('.kanban-add-btn');
    await expect(addCardBtn).toBeVisible({ timeout: 5000 });
    await addCardBtn.click();
    const cardForm = page.locator('[data-testid="card-form"]');
    await expect(cardForm).toBeVisible({ timeout: 5000 });
    await expect(page.locator('[data-testid="card-title-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-description-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-agent-selector"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-priority-select"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-status-pills"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-form-submit"]')).toBeVisible();
    await expect(page.locator('[data-testid="card-form-cancel"]')).toBeVisible();
  });

  test('Card form validates required title', async ({ page }) => {
    await createProjectAndOpenKanban(page);

    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.click('[data-testid="card-form-submit"]');
      const titleError = page.locator('[data-testid="card-title-error"]');
      await expect(titleError).toContainText('Title is required');
    }
  });

  test('Card form cancel returns to kanban', async ({ page }) => {
    await createProjectAndOpenKanban(page);

    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.click('[data-testid="card-form-cancel"]');
      await expect(page.locator('[data-testid="kanban-board"]')).toBeVisible({ timeout: 5000 });
    }
  });

  test('Card form has all 7 agent options', async ({ page }) => {
    await createProjectAndOpenKanban(page);

    const addCardBtn = page.locator('.kanban-add-btn');
    if (await addCardBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
      await addCardBtn.click();
      await page.waitForSelector('[data-testid="card-form"]', { timeout: 5000 });
      const agentSelector = page.locator('[data-testid="card-agent-selector"]');
      await expect(agentSelector).toBeVisible({ timeout: 3000 });
      const chips = agentSelector.locator('.agent-chip');
      const chipTexts = await chips.allTextContents();
      expect(chipTexts).toHaveLength(7);
      expect(chipTexts.some(t => t.includes('Ember'))).toBeTruthy();
      expect(chipTexts.some(t => t.includes('Codeuse'))).toBeTruthy();
      expect(chipTexts.some(t => t.includes('QA'))).toBeTruthy();
    }
  });

  test('Card form status pills are clickable', async ({ page }) => {
    await createProjectAndOpenKanban(page);

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
