import { test, expect } from '@playwright/test';
import { createWorkspaceViaUI, deleteWorkspace, sendChat, listCards, pollUntil } from './helpers';

/**
 * S4 — Bulk-by-list ops: the dispatcher should archive several cards in ONE
 * tool call (card_ids), not loop one-by-one. Validates the generic _BULK_TOOLS
 * fan-out end-to-end.
 */
test.describe('S4 · Bulk ops via list of ids', () => {
  let wsId = '';
  test.afterEach(async ({ request }) => {
    if (wsId) await deleteWorkspace(request, wsId);
    wsId = '';
  });

  test('archive all cards at once', async ({ page }) => {
    const ws = await createWorkspaceViaUI(page, `QA_S4_${Date.now()}`);
    wsId = ws.id;

    // Seed 4 active cards via API.
    for (let i = 0; i < 4; i++) {
      await page.request.post(`/api/workspaces/${ws.id}/cards`, {
        data: { title: `Bulk card ${i + 1}`, status: 'todo', priority: 1 },
      });
    }
    const before = await listCards(page.request, ws.id);
    expect(before.length).toBeGreaterThanOrEqual(4);

    const t0 = Date.now();
    await sendChat(
      page,
      "Archive toutes les cartes de ce tableau d'un seul coup (en une seule opération bulk, pas une par une).",
      { replyTimeout: 90_000 },
    );

    // All active cards should end up archived (board emptied).
    const emptied = await pollUntil(async () => {
      const cards = await listCards(page.request, ws.id);
      return cards.length === 0 ? true : null;
    }, { timeout: 60_000 });

    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    console.log(`archived all in ${elapsed}s — board empty: ${!!emptied}`);
    expect(emptied, 'cards were not all archived').toBeTruthy();
  });
});
