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
    // Navigate to kanban view
    await page.locator('[data-view="kanban"]').click();
    await page.waitForSelector('[data-testid="kanban-column"]', { timeout: 5000 });

    const columns = page.locator('[data-testid="kanban-column"]');
    const count = await columns.count();

    // Should have 4 columns: Idea, Todo, In Progress, Done
    expect(count).toBe(4);
  });

  test('Project list is accessible', async ({ page }) => {
    // Navigate to projects view
    await page.locator('[data-view="projects"]').click();
    const projectList = page.locator('[data-testid="project-list"]');
    await expect(projectList).toBeVisible();
  });

  test('Navigation breadcrumbs exist', async ({ page }) => {
    const breadcrumbs = page.locator('[data-testid="breadcrumbs"]');
    await expect(breadcrumbs).toBeVisible();
  });

  test('Dark theme CSS variables loaded', async ({ page }) => {
    const bgColor = await page.evaluate(() => {
      return getComputedStyle(document.documentElement).getPropertyValue('--color-bg');
    });
    expect(bgColor).toBeTruthy();
  });
});
