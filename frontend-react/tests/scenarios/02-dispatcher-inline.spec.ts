import { test, expect } from '@playwright/test';
import {
  createWorkspaceViaUI, deleteWorkspace, sendChat, listCards, workersForWorkspace, pollUntil,
} from './helpers';

/**
 * S2 — Dispatcher does simple CRUD INLINE (Axe D1).
 *
 * The user asks Voxy (in natural language) to create several cards. With the
 * D1 prompt change, the dispatcher should create them itself via inline MCP
 * tools — NOT spawn a worker subprocess. We assert:
 *   - the cards actually get created in this workspace (the work happened), and
 *   - no worker task was spawned for this workspace (it was done inline).
 */
test.describe('S2 · Dispatcher inline CRUD', () => {
  let wsId = '';
  test.afterEach(async ({ request }) => {
    if (wsId) await deleteWorkspace(request, wsId);
    wsId = '';
  });

  test('asking Voxy to create cards is handled inline, no worker spawned', async ({ page }) => {
    const ws = await createWorkspaceViaUI(page, `QA_S2_${Date.now()}`);
    wsId = ws.id;

    const before = await listCards(page.request, ws.id);
    const beforeTitles = new Set(before.map((c) => (c.title || '').toLowerCase()));

    const reply = await sendChat(
      page,
      "Crée trois cartes dans ce tableau, directement : « Acheter les billets d'avion », " +
      "« Réserver l'hôtel », « Préparer l'itinéraire ». Ne délègue pas, fais-le toi-même.",
      { replyTimeout: 120_000 },
    );
    console.log('assistant reply (head):', reply.slice(0, 200).replace(/\n/g, ' '));

    // The 3 new cards should show up (created inline by the dispatcher).
    const newCards = await pollUntil(async () => {
      const cards = await listCards(page.request, ws.id);
      const fresh = cards.filter((c) => !beforeTitles.has((c.title || '').toLowerCase()));
      return fresh.length >= 3 ? fresh : null;
    }, { timeout: 90_000 });

    expect(newCards, 'expected >=3 new cards created inline').not.toBeNull();
    console.log('new cards created:', (newCards || []).map((c) => c.title));

    // Sanity: titles relate to the request.
    const blob = (newCards || []).map((c) => (c.title || '').toLowerCase()).join(' | ');
    expect(blob).toMatch(/billet|hôtel|hotel|itin/);

    // D1 assertion: no worker subprocess was spawned for this workspace.
    const workers = await workersForWorkspace(page.request, ws.id);
    console.log('workers spawned for this workspace:', workers.map((w) => `${w.action}:${w.status}`));
    expect(workers.length, `expected NO worker (inline path), got: ${JSON.stringify(workers)}`).toBe(0);
  });
});
