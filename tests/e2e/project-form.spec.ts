import { test, expect } from '@playwright/test';

test.describe('Project Form — Inline Create/Edit', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForLoadState('networkidle');
  });

  test('Form appears when clicking "+" tab button', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();

    // Should say "Create Project"
    await expect(form.locator('h2')).toHaveText('Create Project');

    // Should have name input focused
    const nameInput = page.locator('[data-testid="project-name-input"]');
    await expect(nameInput).toBeVisible();
  });

  test('Form appears when clicking "New Project" in project list', async ({ page }) => {
    // Navigate to projects view first
    const projectsNav = page.locator('[data-testid="sidebar"] button', { hasText: 'Projects' });
    await projectsNav.click();

    const newBtn = page.locator('[data-testid="new-project-btn"]');
    await newBtn.click();

    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();
    await expect(form.locator('h2')).toHaveText('Create Project');
  });

  test('Validation: empty title shows error', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const submitBtn = page.locator('[data-testid="project-form-submit"]');
    await submitBtn.click();

    const error = page.locator('[data-testid="project-name-error"]');
    await expect(error).toHaveText('Project name is required');

    const nameInput = page.locator('[data-testid="project-name-input"]');
    await expect(nameInput).toHaveClass(/error/);
  });

  test('Validation: name shows valid state after typing', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const nameInput = page.locator('[data-testid="project-name-input"]');
    await nameInput.fill('Test Project');

    await expect(nameInput).toHaveClass(/valid/);
  });

  test('Submit creates project and opens tab', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const nameInput = page.locator('[data-testid="project-name-input"]');
    await nameInput.fill('My New Project');

    const descInput = page.locator('[data-testid="project-description-input"]');
    await descInput.fill('A test project');

    // Select an emoji
    const rocketEmoji = page.locator('[data-testid="emoji-option-🚀"]');
    await rocketEmoji.click();

    // Select a color
    const blueColor = page.locator('[data-testid="color-option-54a0ff"]');
    await blueColor.click();

    const submitBtn = page.locator('[data-testid="project-form-submit"]');
    await submitBtn.click();

    // Form should be gone
    const form = page.locator('[data-testid="project-form"]');
    await expect(form).not.toBeVisible();

    // A new tab should exist with the project name
    const tabBar = page.locator('[data-testid="tab-bar"]');
    await expect(tabBar).toContainText('My New Project');
  });

  test('Cancel returns to previous view', async ({ page }) => {
    // Start on projects view
    const projectsNav = page.locator('[data-testid="sidebar"] button', { hasText: 'Projects' });
    await projectsNav.click();

    // Verify we're on projects
    const projectList = page.locator('[data-testid="project-list"]');
    await expect(projectList).toBeVisible();

    // Open form
    const newBtn = page.locator('[data-testid="new-project-btn"]');
    await newBtn.click();

    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();

    // Cancel
    const cancelBtn = page.locator('[data-testid="project-form-cancel"]');
    await cancelBtn.click();

    // Form gone, back to project list
    await expect(form).not.toBeVisible();
    await expect(projectList).toBeVisible();
  });

  test('Edit mode pre-fills project data', async ({ page }) => {
    // Create a project first via the form
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const nameInput = page.locator('[data-testid="project-name-input"]');
    await nameInput.fill('Editable Project');

    const descInput = page.locator('[data-testid="project-description-input"]');
    await descInput.fill('Will be edited');

    const submitBtn = page.locator('[data-testid="project-form-submit"]');
    await submitBtn.click();

    // Now go to projects list
    const projectsNav = page.locator('[data-testid="sidebar"] button', { hasText: 'Projects' });
    await projectsNav.click();

    // Click edit on the project
    const editBtn = page.locator('.project-edit-btn').first();
    await editBtn.click();

    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();
    await expect(form.locator('h2')).toHaveText('Edit Project');

    // Check pre-filled values
    const editNameInput = page.locator('[data-testid="project-name-input"]');
    await expect(editNameInput).toHaveValue('Editable Project');

    const editDescInput = page.locator('[data-testid="project-description-input"]');
    await expect(editDescInput).toHaveValue('Will be edited');

    // Submit button should say "Save Changes"
    const editSubmitBtn = page.locator('[data-testid="project-form-submit"]');
    await expect(editSubmitBtn).toHaveText('Save Changes');

    // Should have status dropdown in edit mode
    const statusSelect = page.locator('[data-testid="project-status-select"]');
    await expect(statusSelect).toBeVisible();

    // Should have archive button
    const archiveBtn = page.locator('[data-testid="project-form-archive"]');
    await expect(archiveBtn).toBeVisible();
  });

  test('GitHub repo field exists in project form', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();

    // Verify GitHub input exists
    const githubInput = page.locator('[data-testid="project-github-input"]');
    await expect(githubInput).toBeVisible();

    // Verify Connect button exists
    const connectBtn = page.locator('[data-testid="github-connect-btn"]');
    await expect(connectBtn).toBeVisible();
    await expect(connectBtn).toHaveText('Connect');

    // Verify status area exists
    const githubStatus = page.locator('[data-testid="github-status"]');
    await expect(githubStatus).toBeAttached();
  });

  test('GitHub field validates input format', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    const githubInput = page.locator('[data-testid="project-github-input"]');
    await githubInput.fill('not-a-valid-input');

    // Mock the API to intercept
    await page.route('**/api/github/validate/**', async (route) => {
      await route.fulfill({ status: 404, body: JSON.stringify({ detail: 'Repository not found' }) });
    });

    const connectBtn = page.locator('[data-testid="github-connect-btn"]');
    await connectBtn.click();

    // Should show error (invalid format since no slash)
    const githubStatus = page.locator('[data-testid="github-status"]');
    await expect(githubStatus).toContainText('Invalid format');
  });

  test('GitHub field shows connected status on valid repo', async ({ page }) => {
    const addBtn = page.locator('[data-testid="tab-add"]');
    await addBtn.click();

    // Mock successful API response
    await page.route('**/api/github/validate/acme-org/example-app', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          valid: true,
          full_name: 'acme-org/example-app',
          description: 'Voice-first project assistant',
          default_branch: 'main',
          language: 'TypeScript',
          stars: 5,
          private: false,
          html_url: 'https://github.com/acme-org/example-app',
          clone_url: 'https://github.com/acme-org/example-app.git',
          updated_at: new Date().toISOString(),
        }),
      });
    });

    const githubInput = page.locator('[data-testid="project-github-input"]');
    await githubInput.fill('acme-org/example-app');

    const connectBtn = page.locator('[data-testid="github-connect-btn"]');
    await connectBtn.click();

    // Should show connected status
    const githubStatus = page.locator('[data-testid="github-status"]');
    await expect(githubStatus).toHaveClass(/connected/);
    await expect(githubStatus).toContainText('acme-org/example-app');
    await expect(githubStatus).toContainText('TypeScript');
  });

  test('No window.prompt calls exist', async ({ page }) => {
    // Override window.prompt to track calls
    await page.evaluate(() => {
      (window as unknown as Record<string, unknown>).__promptCalled = false;
      window.prompt = () => {
        (window as unknown as Record<string, unknown>).__promptCalled = true;
        return null;
      };
    });

    // Navigate to projects
    const projectsNav = page.locator('[data-testid="sidebar"] button', { hasText: 'Projects' });
    await projectsNav.click();

    // Click new project
    const newBtn = page.locator('[data-testid="new-project-btn"]');
    await newBtn.click();

    // Verify prompt was NOT called
    const promptCalled = await page.evaluate(() => (window as unknown as Record<string, unknown>).__promptCalled);
    expect(promptCalled).toBe(false);

    // Form should be shown instead
    const form = page.locator('[data-testid="project-form"]');
    await expect(form).toBeVisible();
  });
});
