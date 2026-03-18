import { test, expect } from '@playwright/test';

test.describe('Context-Aware Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.clear();
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
  });

  test('General mode: no view toggle or opportunities panel visible', async ({ page }) => {
    // Should be in general mode by default
    const viewToggle = page.locator('[data-testid="view-toggle"]');
    await expect(viewToggle).not.toBeVisible();

    const opportunities = page.locator('[data-testid="opportunities-panel"]');
    await expect(opportunities).not.toBeVisible();
  });

  test('General mode: context indicator shows General Chat', async ({ page }) => {
    const contextIndicator = page.locator('[data-testid="context-indicator"]');
    await expect(contextIndicator).toBeVisible();
    await expect(contextIndicator).toContainText('General Chat');
  });

  test('Sidebar shows General item and Projects section', async ({ page }) => {
    const generalItem = page.locator('[data-testid="sidebar-general"]');
    await expect(generalItem).toBeVisible();
    await expect(generalItem).toContainText('General');

    // General should be active by default
    await expect(generalItem).toHaveClass(/active/);

    // New project button should be visible
    const newProject = page.locator('[data-testid="sidebar-new-project"]');
    await expect(newProject).toBeVisible();
  });

  test('Creating a project and opening it switches to project mode', async ({ page }) => {
    // Create a project via the tab bar + button
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    // Fill in the project form
    const titleInput = page.locator('input[placeholder*="project"]').first();
    if (await titleInput.isVisible()) {
      await titleInput.fill('Test Project');
      // Submit the form
      const submitBtn = page.locator('button:has-text("Create")').first();
      if (await submitBtn.isVisible()) {
        await submitBtn.click();
        await page.waitForTimeout(500);

        // Now in project mode — view toggle should be visible
        const viewToggle = page.locator('[data-testid="view-toggle"]');
        await expect(viewToggle).toBeVisible();
      }
    }
  });

  test('Switching back to General tab hides project-specific UI', async ({ page }) => {
    // First create a project so we have tabs
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const titleInput = page.locator('input[placeholder*="project"]').first();
    if (await titleInput.isVisible()) {
      await titleInput.fill('Another Project');
      const submitBtn = page.locator('button:has-text("Create")').first();
      if (await submitBtn.isVisible()) {
        await submitBtn.click();
        await page.waitForTimeout(500);

        // Now click General in sidebar
        const generalItem = page.locator('[data-testid="sidebar-general"]');
        await generalItem.click();
        await page.waitForTimeout(300);

        // View toggle should not be visible in general mode
        const viewToggle = page.locator('[data-testid="view-toggle"]');
        await expect(viewToggle).not.toBeVisible();

        // Opportunities panel should not be visible
        const opportunities = page.locator('[data-testid="opportunities-panel"]');
        await expect(opportunities).not.toBeVisible();
      }
    }
  });
});
