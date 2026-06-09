import { test, expect } from '@playwright/test';
import { createWorkspaceViaUI, deleteWorkspace } from './helpers';

/**
 * S1 — Board realtime CRUD (deterministic, no LLM).
 *
 * Validates the Axe-A fluidity goal: when a card is created / updated / deleted
 * out-of-band (here via the API, the same path a worker or another client
 * uses), the open Kanban board reflects it LIVE via the cards:changed WS event
 * — no manual reload.
 */
test.describe('S1 · Board realtime CRUD', () => {
  let wsId = '';

  test.afterEach(async ({ request }) => {
    if (wsId) await deleteWorkspace(request, wsId);
    wsId = '';
  });

  test('cards created/moved/deleted via API appear live on the board', async ({ page }) => {
    const ws = await createWorkspaceViaUI(page, `QA_S1_${Date.now()}`);
    wsId = ws.id;
    const board = page.locator('[data-testid="kanban-board"]');
    // New workspaces may be seeded with starter cards — track only OUR card by
    // its unique title rather than assuming an empty board.

    // --- CREATE out-of-band, expect it live ---
    const title = `Réserver le vol ${Date.now() % 100000}`;
    const created = await page.request.post(`/api/workspaces/${ws.id}/cards`, {
      data: { title, description: 'live-create probe', status: 'todo', priority: 1 },
    });
    expect(created.ok()).toBeTruthy();
    const card = await created.json();

    await expect(page.locator('[data-testid="kanban-card"]').filter({ hasText: title }))
      .toBeVisible({ timeout: 12_000 });
    console.log('✓ live CREATE reflected on board');

    // --- MOVE to in-progress out-of-band, expect it under the new column live ---
    const moved = await page.request.patch(`/api/cards/${card.id}`, {
      data: { status: 'in-progress' },
    });
    expect(moved.ok()).toBeTruthy();

    const inProgressCol = page.locator('[data-testid="kanban-column-in-progress"]');
    await expect(inProgressCol.getByText(title, { exact: false }))
      .toBeVisible({ timeout: 12_000 });
    console.log('✓ live MOVE reflected on board');

    // --- DELETE out-of-band, expect it to vanish live ---
    const del = await page.request.delete(`/api/cards/${card.id}?force=true`);
    expect(del.ok(), `delete failed: ${del.status()}`).toBeTruthy();

    await expect(page.locator('[data-testid="kanban-card"]').filter({ hasText: title }))
      .toHaveCount(0, { timeout: 12_000 });
    console.log('✓ live DELETE reflected on board');
  });
});
