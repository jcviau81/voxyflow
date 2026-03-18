import { test, expect } from '@playwright/test';

/**
 * Helper: create a project and navigate to project chat view (which shows SessionTabBar).
 * SessionTabBar is shown for project and card chat levels, not general chat.
 * General chat uses its own session UI in the unified header.
 */
async function createProjectAndOpenChat(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const newProjectBtn = page.locator('[data-testid="sidebar-new-project"]');
  await expect(newProjectBtn).toBeVisible({ timeout: 5000 });
  await newProjectBtn.click();

  const nameInput = page.locator('[data-testid="project-name-input"]');
  await expect(nameInput).toBeVisible({ timeout: 5000 });
  await nameInput.fill('Session Tab Test Project');

  const submitBtn = page.locator('[data-testid="project-form-submit"]');
  await submitBtn.click();

  // After creation, app shows the project view (kanban)
  await page.waitForSelector('[data-testid="kanban-board"]', { timeout: 10000 });
}

test.describe('Session Tabs — General Chat (Unified Header)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
  });

  test('General chat shows session tabs in unified header', async ({ page }) => {
    await expect(page.locator('[data-testid="session-tabs"]')).toBeVisible({ timeout: 5000 });
  });

  test('Default session "Session 1" is shown', async ({ page }) => {
    const sessionTabs = page.locator('[data-testid="session-tabs"]');
    await expect(sessionTabs).toBeVisible({ timeout: 5000 });
    const tabs = sessionTabs.locator('.session-tab');
    await expect(tabs).toHaveCount(1);
    await expect(tabs.first()).toContainText('Session 1');
  });

  test('Clicking "+" (new-session-btn) creates a new session tab', async ({ page }) => {
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(1);

    const newSessionBtn = page.locator('[data-testid="new-session-btn"]');
    await newSessionBtn.click();

    await expect(page.locator('[data-testid="session-tabs"] .session-tab')).toHaveCount(2);
  });

  test('New session tab is automatically activated', async ({ page }) => {
    await page.locator('[data-testid="new-session-btn"]').click();
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(2);
    // The newest tab should be active
    const lastTab = tabs.last();
    await expect(lastTab).toHaveClass(/active/);
  });

  test('Switching between sessions loads different history', async ({ page }) => {
    // Session 1: type a message
    const input = page.locator('[data-testid="chat-input"]');
    await input.fill('Session 1 message');
    await input.press('Enter');
    await page.waitForTimeout(300);

    // Create session 2
    await page.locator('[data-testid="new-session-btn"]').click();

    // Session 2 should have no messages (clean slate)
    const messages = page.locator('.message-bubble');
    const countInSession2 = await messages.count();
    expect(countInSession2).toBe(0);

    // Switch back to session 1
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await tabs.first().click();
    // Session 1 should have the message we typed
    await expect(page.locator('.message-bubble')).toBeVisible({ timeout: 3000 });
  });

  test('Max 5 sessions: + button becomes disabled at limit', async ({ page }) => {
    const newSessionBtn = page.locator('[data-testid="new-session-btn"]');

    // Create up to the max (start at 1, need 4 more clicks)
    for (let i = 0; i < 4; i++) {
      await newSessionBtn.click();
      await page.waitForTimeout(200);
    }

    // Should have 5 tabs now
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(5);

    // + button should be disabled
    await expect(newSessionBtn).toBeDisabled();
  });
});

test.describe('Session Tabs — Project Chat (SessionTabBar)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // Navigate to project view
    await createProjectAndOpenChat(page);
    // Switch to chat view within project
    const viewToggle = page.locator('[data-testid="view-toggle"]');
    if (await viewToggle.isVisible({ timeout: 3000 }).catch(() => false)) {
      await viewToggle.click();
    }
  });

  test('Opening a project shows the session tab bar', async ({ page }) => {
    await expect(page.locator('[data-testid="session-tab-bar"]')).toBeVisible({ timeout: 5000 });
  });

  test('Default session "Session 1" is shown in project tab bar', async ({ page }) => {
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar).toBeVisible({ timeout: 5000 });
    const tabs = tabBar.locator('.session-tab');
    await expect(tabs).toHaveCount(1);
    await expect(tabs.first()).toContainText('Session 1');
  });

  test('Clicking "+" creates a new session tab in project', async ({ page }) => {
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar).toBeVisible({ timeout: 5000 });
    const tabs = tabBar.locator('.session-tab');
    await expect(tabs).toHaveCount(1);

    const addBtn = page.locator('[data-testid="session-tab-new"]');
    await addBtn.click();
    await expect(tabBar.locator('.session-tab')).toHaveCount(2);
  });

  test('Closing a session (×) removes the tab', async ({ page }) => {
    const addBtn = page.locator('[data-testid="session-tab-new"]');
    await addBtn.click();
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar.locator('.session-tab')).toHaveCount(2);

    // Close the first tab using its × button
    const firstCloseBtn = tabBar.locator('.session-tab-close').first();
    await firstCloseBtn.click();
    await expect(tabBar.locator('.session-tab')).toHaveCount(1);
  });

  test('Close button is disabled when only 1 session exists', async ({ page }) => {
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar.locator('.session-tab')).toHaveCount(1);

    const closeBtn = tabBar.locator('.session-tab-close').first();
    await expect(closeBtn).toBeDisabled();
  });

  test('Max 5 sessions: + button disabled at limit in project', async ({ page }) => {
    const addBtn = page.locator('[data-testid="session-tab-new"]');
    // Create 4 more (start at 1)
    for (let i = 0; i < 4; i++) {
      await addBtn.click();
      await page.waitForTimeout(200);
    }
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar.locator('.session-tab')).toHaveCount(5);
    await expect(addBtn).toBeDisabled();
  });
});
