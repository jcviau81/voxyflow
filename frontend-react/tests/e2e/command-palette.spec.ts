/**
 * Command Palette — e2e tests.
 *
 * Verifies the global Cmd/Ctrl+K palette:
 *   - Ctrl+K opens it, Escape closes it
 *   - typing filters; selecting a workspace navigates to /workspace/:id
 *
 * Prerequisites: backend running on :8000 (same as the other specs),
 * at least one active workspace.
 */

import { test, expect, type Page } from '@playwright/test';

interface RawWorkspace {
  id: string;
  title?: string;
  name?: string;
}

async function fetchFirstWorkspace(page: Page): Promise<RawWorkspace | null> {
  const res = await page.request.get('/api/workspaces?archived=false');
  if (!res.ok()) return null;
  const list = (await res.json()) as RawWorkspace[];
  return list.length > 0 ? list[0] : null;
}

test.describe('Command Palette', () => {
  test.beforeEach(async ({ page }) => {
    // Skip the onboarding redirect — the palette lives in the AppShell.
    await page.addInitScript(() => {
      try {
        localStorage.setItem('onboarding_complete', 'true');
      } catch {
        /* ignore */
      }
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('opens with Ctrl+K and closes with Escape', async ({ page }) => {
    await page.keyboard.press('Control+k');
    const palette = page.getByTestId('command-palette');
    await expect(palette).toBeVisible();

    // Input is focused and ready for typing
    await expect(page.getByTestId('command-palette-input')).toBeFocused();

    await page.keyboard.press('Escape');
    await expect(palette).toBeHidden();
  });

  test('typing a workspace name and pressing Enter navigates to it', async ({ page }) => {
    const workspace = await fetchFirstWorkspace(page);
    test.skip(!workspace, 'No workspaces available on this backend');

    const name = (workspace!.title ?? workspace!.name ?? '').trim();
    test.skip(!name, 'Workspace has no usable name');

    await page.keyboard.press('Control+k');
    await expect(page.getByTestId('command-palette')).toBeVisible();

    // Typing immediately filters
    await page.getByTestId('command-palette-input').fill(name);

    // The workspace entry should be among the results; select it via keyboard only
    const item = page.locator('[cmdk-item]', { hasText: name }).first();
    await expect(item).toBeVisible();

    // Walk the selection down until the workspace entry is selected, then Enter.
    // (Ranking puts it at/near the top; bounded loop keeps the test robust.)
    for (let i = 0; i < 10; i++) {
      const selected = await item.getAttribute('data-selected');
      if (selected === 'true') break;
      await page.keyboard.press('ArrowDown');
    }
    await expect(item).toHaveAttribute('data-selected', 'true');
    await page.keyboard.press('Enter');

    await expect(page).toHaveURL(new RegExp(`/workspace/${workspace!.id}`));
    await expect(page.getByTestId('command-palette')).toBeHidden();
  });

  test('palette lists the New card action', async ({ page }) => {
    await page.keyboard.press('Control+k');
    await expect(page.getByTestId('command-palette')).toBeVisible();
    await expect(page.getByTestId('command-palette-new-card')).toBeVisible();
    await page.keyboard.press('Escape');
  });
});
