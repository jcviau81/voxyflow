import { test, expect } from '@playwright/test';

test.describe('Voxyflow E2E', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForSelector('#app', { timeout: 10000 });
  });

  test('App loads and renders UI', async ({ page }) => {
    const sidebar = page.locator('[data-testid="sidebar"]');
    await expect(sidebar).toBeVisible();

    const chatWindow = page.locator('[data-testid="chat-window"]');
    await expect(chatWindow).toBeVisible();
  });

  test('Chat input is functional', async ({ page }) => {
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Test message');
    await expect(input).toHaveValue('Test message');
  });

  test('Voice input button visible on desktop', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });

    const voiceBtn = page.locator('[data-testid="voice-input-btn"]');
    await expect(voiceBtn).toBeVisible();
  });

  test('Kanban board renders columns', async ({ page }) => {
    // Kanban requires project context — create a project via UI
    const newProjectBtn = page.locator('[data-testid="sidebar-new-project"]');
    await expect(newProjectBtn).toBeVisible({ timeout: 5000 });
    await newProjectBtn.click();

    // Fill project form
    const nameInput = page.locator('[data-testid="project-name-input"]');
    await expect(nameInput).toBeVisible({ timeout: 5000 });
    await nameInput.fill('Kanban Test Project');

    // Submit — app auto-switches to kanban view after project creation
    const submitBtn = page.locator('[data-testid="project-form-submit"]');
    await submitBtn.click();

    await page.waitForSelector('[data-testid="kanban-column"]', { timeout: 10000 });

    const columns = page.locator('[data-testid="kanban-column"]');
    const count = await columns.count();

    // Should have 4 columns: Idea, Todo, In Progress, Done
    expect(count).toBe(4);
  });

  test('Project list is accessible via sidebar', async ({ page }) => {
    // Projects are now shown directly in the sidebar
    const sidebar = page.locator('[data-testid="sidebar"]');
    await expect(sidebar).toBeVisible();

    // The sidebar should have a projects section
    const projectSection = page.locator('.sidebar-projects');
    await expect(projectSection).toBeVisible({ timeout: 5000 });
  });

  test('Context indicator exists', async ({ page }) => {
    // Breadcrumbs were replaced by context indicator
    const contextIndicator = page.locator('[data-testid="context-indicator"]');
    await expect(contextIndicator).toBeVisible();
  });

  test('Dark theme CSS variables loaded', async ({ page }) => {
    const bgColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue('--color-bg');
    });
    expect(bgColor).toBeTruthy();
  });
});
