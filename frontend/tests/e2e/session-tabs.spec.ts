import { test, expect } from '@playwright/test';

/**
 * Bypass the onboarding screen by intercepting the /api/settings GET response
 * to always return onboarding_complete: true. This avoids race conditions from
 * parallel tests mutating shared backend state.
 */
async function bypassOnboarding(page: import('@playwright/test').Page) {
  await page.route('**/api/settings', async (route, request) => {
    if (request.method() === 'GET') {
      // Fetch the real settings and patch onboarding_complete
      const response = await route.fetch();
      const json = await response.json().catch(() => ({}));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...json, onboarding_complete: true }),
      });
    } else {
      // Allow PUT/POST through unchanged
      await route.continue();
    }
  });
}

/**
 * Helper: create a project and navigate to project chat view (which shows SessionTabBar).
 * SessionTabBar is shown for project and card chat levels, not general chat.
 * General chat uses a single resettable session in the unified header.
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
    await bypassOnboarding(page);
    await page.goto('/');
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

  test('Clicking "+" (session-tab-add) clears the current session (reset behavior)', async ({ page }) => {
    // General chat has single-session reset — clicking "+" resets the current session
    // rather than adding a new tab. Tab count stays at 1.
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(1);

    // The + button inside the session-tabs area has class session-tab-add
    const addBtn = page.locator('[data-testid="session-tabs"] .session-tab-add');
    await addBtn.click();

    // Tab count stays at 1 (reset, not add)
    await expect(tabs).toHaveCount(1);
  });

  test('"new-session-btn" in bottom bar resets the current session', async ({ page }) => {
    // The new-session-btn resets the current session in-place (no new tab)
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(1);

    const newSessionBtn = page.locator('[data-testid="new-session-btn"]');
    await newSessionBtn.click();

    // Tab count stays at 1 — session was reset, not duplicated
    await expect(tabs).toHaveCount(1);
  });

  test('Active session tab is highlighted', async ({ page }) => {
    const tabs = page.locator('[data-testid="session-tabs"] .session-tab');
    await expect(tabs).toHaveCount(1);
    // The single tab should be active
    await expect(tabs.first()).toHaveClass(/active/);
  });

  test('Session tabs container is in the top bar', async ({ page }) => {
    const topBar = page.locator('[data-testid="chat-top-bar"]');
    await expect(topBar).toBeVisible({ timeout: 5000 });

    // Session tabs are part of the top bar
    const sessionTabs = topBar.locator('[data-testid="session-tabs"]');
    await expect(sessionTabs).toBeVisible({ timeout: 3000 });
  });
});

test.describe('Session Tabs — Project Chat (SessionTabBar)', () => {
  test.beforeEach(async ({ page }) => {
    await bypassOnboarding(page);
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForSelector('#app', { timeout: 10000 });
    // Navigate to project view (opens kanban)
    await createProjectAndOpenChat(page);
    // Wait for the ProjectHeader to become visible with project tabs.
    // The project header only shows when activeTab is a project (not 'main'),
    // which happens AFTER the async project creation completes and openProjectTab is called.
    await page.waitForFunction(
      () => {
        const header = document.querySelector('[data-testid="project-header"]') as HTMLElement | null;
        return header && header.style.display !== 'none' && header.querySelector('.project-header__tabs') !== null;
      },
      { timeout: 10000 }
    );
    // The app shows kanban after project creation, but appState.currentView may still be 'chat'
    // (App.switchView bypasses appState when called internally). To ensure the Chat button
    // triggers a real view switch, we first click Kanban (which syncs appState.currentView to
    // 'kanban'), then click Chat.
    const kanbanBtn = page.locator('.project-header__tab[data-view="kanban"]');
    await kanbanBtn.waitFor({ timeout: 5000 });
    await kanbanBtn.click();
    // Now appState.currentView = 'kanban' — clicking Chat will trigger switchView('chat')
    const chatViewBtn = page.locator('.project-header__tab[data-view="chat"]');
    await chatViewBtn.waitFor({ timeout: 8000 });
    await chatViewBtn.click();
    await page.waitForSelector('[data-testid="session-tab-bar"]', { timeout: 15000 });
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
    const firstTab = tabBar.locator('.session-tab').first();
    await firstTab.hover();
    const firstCloseBtn = tabBar.locator('.session-tab-close').first();
    await firstCloseBtn.click({ force: true });
    await expect(tabBar.locator('.session-tab')).toHaveCount(1);
  });

  test('Close button is present in the DOM (resets session when only 1 session exists)', async ({ page }) => {
    const tabBar = page.locator('[data-testid="session-tab-bar"]');
    await expect(tabBar.locator('.session-tab')).toHaveCount(1);

    // The close button exists in the DOM (may be CSS-hidden until hover).
    // Clicking it when there's only 1 session resets the session rather than being disabled.
    const closeBtn = tabBar.locator('.session-tab-close').first();
    await expect(closeBtn).toBeAttached();
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
