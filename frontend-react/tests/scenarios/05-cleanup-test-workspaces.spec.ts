import { test, expect } from '@playwright/test';
import { gotoApp, createWorkspace, sendChat, deleteWorkspace, pollUntil } from './helpers';

/**
 * S5 — Pattern-delete of test workspaces, INLINE (regression for the
 * 2026-06-10 incident: "Efface les workspaces de test" dead-ended into a
 * worker delegation because workspace.list spilled past the CLI size cap).
 *
 * Per the dispatcher decision table, a pattern delete the user did not
 * itemize gets ONE short confirmation, then an inline bulk delete
 * (workspace_ids list) — and NO worker is ever spawned. We accept both the
 * confirm-first path and the direct path (the model may treat "QA_S5 test
 * workspaces" as explicitly designated).
 */
test.describe('S5 · Cleanup test workspaces inline', () => {
  const created: string[] = [];

  test.afterEach(async ({ request }) => {
    for (const id of created) await deleteWorkspace(request, id); // best-effort
    created.length = 0;
  });

  test('pattern delete is confirmed once and runs inline, no worker', async ({ page }) => {
    // Seed 3 disposable workspaces via API.
    const stamp = Date.now();
    for (let i = 1; i <= 3; i++) {
      const ws = await createWorkspace(page.request, `QA_S5_Cleanup_${stamp}_${i}`, 'scenario seed');
      created.push(ws.id);
    }

    const beforeTasks = await page.request.get('/api/worker-tasks?limit=20')
      .then((r) => r.json()).then((d) => new Set((d.tasks ?? []).map((t: any) => t.id)));

    await gotoApp(page, '/');
    const reply = await sendChat(
      page,
      `Efface les workspaces de test (ceux dont le nom commence par QA_S5_Cleanup_${stamp}).`,
      { replyTimeout: 120_000 },
    );
    console.log('first reply (head):', reply.slice(0, 200).replace(/\n/g, ' '));

    const allGone = async () => {
      const list = await page.request.get('/api/workspaces').then((r) => r.json());
      const remaining = list.filter((w: any) => (w.title || '').startsWith(`QA_S5_Cleanup_${stamp}`));
      return remaining.length === 0 ? true : null;
    };

    // Direct path: already deleted. Confirm path: answer the confirmation.
    let gone = await pollUntil(allGone, { timeout: 20_000, interval: 2000 });
    if (!gone) {
      const reply2 = await sendChat(page, 'Oui, vas-y.', { replyTimeout: 120_000 });
      console.log('after confirmation (head):', reply2.slice(0, 200).replace(/\n/g, ' '));
      gone = await pollUntil(allGone, { timeout: 60_000, interval: 2000 });
    }
    expect(gone, 'test workspaces were not deleted').toBeTruthy();

    // The whole flow must have stayed inline — zero new worker tasks.
    const afterTasks = await page.request.get('/api/worker-tasks?limit=20')
      .then((r) => r.json()).then((d) => (d.tasks ?? []).map((t: any) => t.id));
    const newTasks = afterTasks.filter((id: string) => !beforeTasks.has(id));
    expect(newTasks, `expected NO worker spawned, got: ${JSON.stringify(newTasks)}`).toHaveLength(0);
  });
});
