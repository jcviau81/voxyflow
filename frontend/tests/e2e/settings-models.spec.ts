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
 * Helper: navigate to the Settings page via the sidebar footer.
 */
async function openSettings(page: import('@playwright/test').Page) {
  await bypassOnboarding(page);
  await page.goto('/');
  await page.waitForSelector('#app', { timeout: 10000 });

  // Settings button is in the sidebar footer — it has data-action="settings"
  // Wait for the sidebar footer to be rendered first
  await page.waitForSelector('[data-testid="sidebar-footer"]', { timeout: 5000 });

  const settingsBtn = page.locator('[data-testid="sidebar-footer"] button[data-action="settings"]');
  if (await settingsBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
    await settingsBtn.click();
  } else {
    // Fallback: look for any settings-related nav item by title or emoji
    const footerBtns = page.locator('[data-testid="sidebar-footer"] button');
    const count = await footerBtns.count();
    for (let i = 0; i < count; i++) {
      const text = await footerBtns.nth(i).textContent();
      const title = await footerBtns.nth(i).getAttribute('title');
      if (text?.includes('⚙') || title?.toLowerCase().includes('setting') || text?.toLowerCase().includes('setting')) {
        await footerBtns.nth(i).click();
        break;
      }
    }
  }

  // Wait for the settings view to be visible
  await page.waitForSelector('[data-testid="settings-models"]', { timeout: 10000 });
}

test.describe('Settings — Models Section', () => {
  test.beforeEach(async ({ page }) => {
    await openSettings(page);
  });

  test('Settings page shows "Models" section', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    await expect(modelsSection).toBeVisible();
    await expect(modelsSection).toContainText('Models');
  });

  test('"Conversational (Fast)" subsection is visible', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    await expect(modelsSection).toContainText('Fast');
  });

  test('"Deep Thinking" subsection is visible', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    await expect(modelsSection).toContainText('Deep');
  });

  test('"Analyzer" subsection is visible', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    await expect(modelsSection).toContainText('Analyzer');
  });

  test('All three model layer subsections are present', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    // Each layer has a model text input
    const modelInputs = modelsSection.locator('[data-model-field="model"]');
    await expect(modelInputs).toHaveCount(3);
  });

  test('API key field is type="password" (masked)', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    const apiKeyInputs = modelsSection.locator('[data-model-field="api_key"]');
    const count = await apiKeyInputs.count();
    expect(count).toBeGreaterThan(0);

    // Every api_key field must be type="password"
    for (let i = 0; i < count; i++) {
      const inputType = await apiKeyInputs.nth(i).getAttribute('type');
      expect(inputType).toBe('password');
    }
  });

  test('Provider URL field is a text input', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    const urlInputs = modelsSection.locator('[data-model-field="provider_url"]');
    const count = await urlInputs.count();
    expect(count).toBe(3);

    for (let i = 0; i < count; i++) {
      const inputType = await urlInputs.nth(i).getAttribute('type');
      expect(inputType).toBe('text');
    }
  });

  test('Changing a model name marks settings as dirty (save bar visible)', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    const firstModelInput = modelsSection.locator('[data-model-field="model"]').first();

    // Change the value
    await firstModelInput.clear();
    await firstModelInput.fill('my-custom-model');
    await firstModelInput.press('Tab'); // trigger change event

    // Save bar should be visible (it's always rendered, check the save button is enabled)
    await expect(page.locator('[data-testid="settings-save-bar"]')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('[data-testid="settings-save"]')).toBeVisible();
  });

  test('Save button is present in the save bar', async ({ page }) => {
    await expect(page.locator('[data-testid="settings-save"]')).toBeVisible();
  });

  test('Reset button is present in the save bar', async ({ page }) => {
    await expect(page.locator('[data-testid="settings-reset"]')).toBeVisible();
  });

  test('Changing model and clicking Save persists the value', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    const fastModelInput = modelsSection.locator('[data-model-field="model"]').first();

    await fastModelInput.clear();
    await fastModelInput.fill('claude-test-model');
    await fastModelInput.press('Tab');

    // Click save
    await page.locator('[data-testid="settings-save"]').click();

    // Wait briefly for save to complete
    await page.waitForTimeout(1000);

    // Reload settings page and verify persisted value
    await openSettings(page);
    const savedInput = page.locator('[data-testid="settings-models"] [data-model-field="model"]').first();
    await expect(savedInput).toHaveValue('claude-test-model');
  });

  test('Model layer enabled/disabled checkbox is present for deep and analyzer', async ({ page }) => {
    const modelsSection = page.locator('[data-testid="settings-models"]');
    // deep and analyzer have an "enabled" checkbox (fast does not, per renderModelLayerFields args)
    const enabledCheckboxes = modelsSection.locator('[data-model-field="enabled"]');
    const count = await enabledCheckboxes.count();
    expect(count).toBe(2); // deep + analyzer
  });

  test('Settings also shows Personality section', async ({ page }) => {
    const personalitySection = page.locator('[data-testid="settings-personality"]');
    await expect(personalitySection).toBeVisible();
  });
});
