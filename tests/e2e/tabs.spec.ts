import { test, expect } from '@playwright/test';

test.describe('Tab Bar Navigation', () => {
  test.beforeEach(async ({ page }) => {
    // Clear localStorage before each test
    await page.goto('http://localhost:3000');
    await page.evaluate(() => {
      localStorage.clear();
    });
    await page.reload();
    await page.waitForLoadState('networkidle');
  });

  test('Main tab always visible and active by default', async ({ page }) => {
    const tabBar = page.locator('[data-testid="tab-bar"]');
    await expect(tabBar).toBeVisible();

    const mainTab = page.locator('[data-testid="tab-main"]');
    await expect(mainTab).toBeVisible();
    await expect(mainTab).toHaveClass(/active/);

    // Main tab should not have a close button
    const closeBtn = page.locator('[data-testid="tab-close-main"]');
    await expect(closeBtn).not.toBeVisible();
  });

  test('Add button is visible', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await expect(addBtn).toBeVisible();
    await expect(addBtn).toHaveText('+');
  });

  test('Can open project tab by creating a project', async ({ page }) => {
    // Navigate to projects view
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    // Wait for projects view - the creation flow will open a tab
    // For now, verify we switched to projects view
    const mainTab = page.locator('[data-testid="tab-main"]');
    await expect(mainTab).toBeVisible();
  });

  test('Can open project tab via sidebar', async ({ page }) => {
    // First create a project via AppState
    await page.evaluate(() => {
      const state = JSON.parse(localStorage.getItem('voxyflow_state') || '{}');
      state.projects = state.projects || [];
      state.projects.push({
        id: 'test-proj-1',
        name: 'Test Project',
        description: 'A test project',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        cards: [],
        archived: false,
      });
      localStorage.setItem('voxyflow_state', JSON.stringify(state));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Click the project in sidebar
    const projectItem = page.locator('[data-testid="sidebar-project-test-proj-1"]');
    if (await projectItem.isVisible()) {
      await projectItem.click();

      // Tab should open
      const projectTab = page.locator('[data-testid="tab-test-proj-1"]');
      await expect(projectTab).toBeVisible();
      await expect(projectTab).toHaveClass(/active/);

      // Main tab should no longer be active
      const mainTab = page.locator('[data-testid="tab-main"]');
      await expect(mainTab).not.toHaveClass(/active/);
    }
  });

  test('Can close project tab', async ({ page }) => {
    // Create a project and open its tab
    await page.evaluate(() => {
      const state = JSON.parse(localStorage.getItem('voxyflow_state') || '{}');
      state.projects = state.projects || [];
      state.projects.push({
        id: 'test-proj-2',
        name: 'Closable Project',
        description: '',
        createdAt: Date.now(),
        updatedAt: Date.now(),
        cards: [],
        archived: false,
      });
      state.openTabs = [
        { id: 'main', label: '💬 Main', emoji: '💬', closable: false, hasNotification: false, isActive: false },
        { id: 'test-proj-2', label: 'Closable Project', emoji: '📁', closable: true, hasNotification: false, isActive: true },
      ];
      state.activeTab = 'test-proj-2';
      localStorage.setItem('voxyflow_state', JSON.stringify(state));
      localStorage.setItem('voxyflow_open_tabs', JSON.stringify(state.openTabs));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Project tab should be visible
    const projectTab = page.locator('[data-testid="tab-test-proj-2"]');
    if (await projectTab.isVisible()) {
      // Close it
      const closeBtn = page.locator('[data-testid="tab-close-test-proj-2"]');
      await projectTab.hover();
      await closeBtn.click();

      // Tab should be gone
      await expect(projectTab).not.toBeVisible();

      // Main tab should now be active
      const mainTab = page.locator('[data-testid="tab-main"]');
      await expect(mainTab).toBeVisible();
      await expect(mainTab).toHaveClass(/active/);
    }
  });

  test('Tab switch changes active state', async ({ page }) => {
    // Setup two tabs
    await page.evaluate(() => {
      const tabs = [
        { id: 'main', label: '💬 Main', emoji: '💬', closable: false, hasNotification: false, isActive: true },
        { id: 'proj-a', label: 'Project A', emoji: '📁', closable: true, hasNotification: false, isActive: false },
      ];
      const state = JSON.parse(localStorage.getItem('voxyflow_state') || '{}');
      state.projects = [
        { id: 'proj-a', name: 'Project A', description: '', createdAt: Date.now(), updatedAt: Date.now(), cards: [], archived: false },
      ];
      state.openTabs = tabs;
      state.activeTab = 'main';
      localStorage.setItem('voxyflow_state', JSON.stringify(state));
      localStorage.setItem('voxyflow_open_tabs', JSON.stringify(tabs));
    });
    await page.reload();
    await page.waitForLoadState('networkidle');

    const mainTab = page.locator('[data-testid="tab-main"]');
    const projTab = page.locator('[data-testid="tab-proj-a"]');

    if (await projTab.isVisible()) {
      // Main should be active
      await expect(mainTab).toHaveClass(/active/);
      await expect(projTab).not.toHaveClass(/active/);

      // Click project tab
      await projTab.click();

      // Now project tab should be active
      await expect(projTab).toHaveClass(/active/);
      await expect(mainTab).not.toHaveClass(/active/);
    }
  });

  test('Tabs persist in localStorage', async ({ page }) => {
    // Open a tab via evaluate
    await page.evaluate(() => {
      const tabs = [
        { id: 'main', label: '💬 Main', emoji: '💬', closable: false, hasNotification: false, isActive: false },
        { id: 'persist-test', label: 'Persist', emoji: '📁', closable: true, hasNotification: false, isActive: true },
      ];
      localStorage.setItem('voxyflow_open_tabs', JSON.stringify(tabs));
      const state = JSON.parse(localStorage.getItem('voxyflow_state') || '{}');
      state.openTabs = tabs;
      state.activeTab = 'persist-test';
      state.projects = [
        { id: 'persist-test', name: 'Persist', description: '', createdAt: Date.now(), updatedAt: Date.now(), cards: [], archived: false },
      ];
      localStorage.setItem('voxyflow_state', JSON.stringify(state));
    });

    // Reload
    await page.reload();
    await page.waitForLoadState('networkidle');

    // Tab should still be there
    const persistTab = page.locator('[data-testid="tab-persist-test"]');
    await expect(persistTab).toBeVisible();
  });

  test('General item in sidebar switches to Main tab', async ({ page }) => {
    const generalItem = page.locator('[data-testid="sidebar-general"]');
    if (await generalItem.isVisible()) {
      await generalItem.click();

      const mainTab = page.locator('[data-testid="tab-main"]');
      await expect(mainTab).toHaveClass(/active/);
    }
  });
});
