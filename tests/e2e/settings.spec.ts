import { test, expect } from '@playwright/test';

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

    // Verify all fields exist
    await expect(page.locator('[data-field="bot_name"]')).toBeVisible();
    await expect(page.locator('[data-field="preferred_language"]')).toBeVisible();
    await expect(page.locator('[data-field="soul_file"]')).toBeVisible();
    await expect(page.locator('[data-field="user_file"]')).toBeVisible();
    await expect(page.locator('[data-field="agents_file"]')).toBeVisible();
    await expect(page.locator('[data-field="custom_instructions"]')).toBeVisible();
    await expect(page.locator('[data-field="environment_notes"]')).toBeVisible();
    await expect(page.locator('[data-field="tone"]')).toBeVisible();
    await expect(page.locator('[data-field="warmth"]')).toBeVisible();

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

    await expect(page.locator('[data-field="bot_name"]')).toHaveValue('Ember');
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
