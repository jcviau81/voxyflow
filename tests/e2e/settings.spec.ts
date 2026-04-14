import { test, expect } from '@playwright/test';

// Helper to navigate to settings
async function navigateToSettings(page: import('@playwright/test').Page) {
  await page.goto('/');
  const settingsNav = page.locator('.sidebar-item:has-text("Settings"), .sidebar-item:has-text("⚙")');
  if (await settingsNav.count() > 0) {
    await settingsNav.first().click();
  }
}

test.describe('Settings - GitHub Integration', () => {
  test('GitHub settings section shows status', async ({ page }) => {
    await navigateToSettings(page);

    // Verify GitHub section exists
    const githubSection = page.locator('[data-testid="settings-github"]');
    await expect(githubSection).toBeVisible({ timeout: 5000 });

    // Check that status elements are present
    await expect(page.locator('#github-connection-status')).toBeVisible();
    await expect(page.locator('#github-cli-status')).toBeVisible();

    // Verify token input exists
    await expect(page.locator('#github-token-input')).toBeVisible();

    // Verify test button exists
    await expect(page.locator('[data-testid="github-test-btn"]')).toBeVisible();
  });

  test('GitHub test button triggers status check', async ({ page }) => {
    await navigateToSettings(page);

    const githubSection = page.locator('[data-testid="settings-github"]');
    await expect(githubSection).toBeVisible({ timeout: 5000 });

    // Click test connection
    await page.locator('[data-testid="github-test-btn"]').click();

    // Should show some result (either success or error)
    const testResult = page.locator('#github-test-result');
    await expect(testResult).not.toBeEmpty({ timeout: 5000 });
  });
});

test.describe('Settings - Project Form GitHub Hint', () => {
  test('Project form shows GitHub setup hint when not connected', async ({ page }) => {
    await page.goto('/');

    // Navigate to projects
    const projectsNav = page.locator('.sidebar-item:has-text("Projects"), .sidebar-item:has-text("📁")');
    if (await projectsNav.count() > 0) {
      await projectsNav.first().click();
    }

    // Open create project form
    const createBtn = page.locator('[data-testid="create-project-btn"], button:has-text("New Project"), button:has-text("Create")');
    if (await createBtn.count() > 0) {
      await createBtn.first().click();
    }

    // Wait for form
    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible({ timeout: 5000 });

    // The GitHub setup hint should exist in the DOM
    const hint = page.locator('[data-testid="github-setup-hint"]');
    await expect(hint).toBeAttached({ timeout: 5000 });

    // GitHub input should still be visible regardless
    await expect(page.locator('[data-testid="project-github-input"]')).toBeVisible();
  });
});

test.describe('Settings - Personality Configuration', () => {
  test('Personality section renders with all fields', async ({ page }) => {
    await page.goto('/');

    // Navigate to settings via sidebar
    const settingsNav = page.locator('.sidebar-item:has-text("Settings"), .sidebar-item:has-text("⚙")');
    if (await settingsNav.count() > 0) {
      await settingsNav.first().click();
    }

    // Wait for personality section
    const personalitySection = page.locator('[data-testid="settings-personality"]');
    await expect(personalitySection).toBeVisible({ timeout: 5000 });

    // Verify core fields exist
    await expect(page.locator('[data-field="bot_name"]')).toBeVisible();
    await expect(page.locator('[data-field="preferred_language"]')).toBeVisible();
    await expect(page.locator('[data-field="custom_instructions"]')).toBeVisible();
    await expect(page.locator('[data-field="environment_notes"]')).toBeVisible();
    await expect(page.locator('[data-field="tone"]')).toBeVisible();
    await expect(page.locator('[data-field="warmth"]')).toBeVisible();

    // Verify file editors exist (replaced soul_file/user_file/agents_file inputs)
    await expect(page.locator('[data-testid="editor-soul"]')).toBeVisible();
    await expect(page.locator('[data-testid="editor-user"]')).toBeVisible();
    await expect(page.locator('[data-testid="editor-agents"]')).toBeVisible();
    await expect(page.locator('[data-testid="editor-identity"]')).toBeVisible();

    // Verify save bar
    await expect(page.locator('[data-testid="settings-save"]')).toBeVisible();
    await expect(page.locator('[data-testid="settings-reset"]')).toBeVisible();
  });

  test('Personality settings load defaults', async ({ page }) => {
    await page.goto('/');

    const settingsNav = page.locator('.sidebar-item:has-text("Settings"), .sidebar-item:has-text("⚙")');
    if (await settingsNav.count() > 0) {
      await settingsNav.first().click();
    }

    const personalitySection = page.locator('[data-testid="settings-personality"]');
    await expect(personalitySection).toBeVisible({ timeout: 5000 });

    await expect(page.locator('[data-field="bot_name"]')).toHaveValue('Voxy');
    await expect(page.locator('[data-field="tone"]')).toHaveValue('casual');
    await expect(page.locator('[data-field="warmth"]')).toHaveValue('warm');
  });

  test('Personality settings save and persist', async ({ page }) => {
    await page.goto('/');

    const settingsNav = page.locator('.sidebar-item:has-text("Settings"), .sidebar-item:has-text("⚙")');
    if (await settingsNav.count() > 0) {
      await settingsNav.first().click();
    }

    const personalitySection = page.locator('[data-testid="settings-personality"]');
    await expect(personalitySection).toBeVisible({ timeout: 5000 });

    // Change bot name
    const botName = page.locator('[data-field="bot_name"]');
    await botName.clear();
    await botName.fill('TestBot');

    // Change tone
    await page.locator('[data-field="tone"]').selectOption('formal');

    // Click save
    await page.locator('[data-testid="settings-save"]').click();

    // Wait for save confirmation
    await expect(page.locator('.save-status')).toContainText('Saved', { timeout: 5000 });

    // Reload page and navigate back
    await page.reload();
    const settingsNav2 = page.locator('.sidebar-item:has-text("Settings"), .sidebar-item:has-text("⚙")');
    if (await settingsNav2.count() > 0) {
      await settingsNav2.first().click();
    }

    await expect(page.locator('[data-testid="settings-personality"]')).toBeVisible({ timeout: 5000 });

    // Verify persisted values
    await expect(page.locator('[data-field="bot_name"]')).toHaveValue('TestBot');
    await expect(page.locator('[data-field="tone"]')).toHaveValue('formal');
  });
});
