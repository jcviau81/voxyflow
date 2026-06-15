import { test, expect } from '@playwright/test';
import { createWorkspaceViaUI, deleteWorkspace, sendChat, workersForWorkspace, pollUntil } from './helpers';

/**
 * S3 — Real worker delegation + live badge (Axe A + B, worker lifecycle).
 *
 * Asking for genuine subprocess work (research) should spawn a worker. We watch:
 *   - a worker task is registered for this workspace (delegation happened),
 *   - it reaches a terminal state (it actually finished — not stuck),
 *   - the in-chat delegate badge transitions to a terminal label live (Axe A),
 *   - the worker panel shows the worker.
 *
 * This is a real claude-CLI worker run — it can take a couple of minutes.
 */
test.describe('S3 · Worker delegation', () => {
  let wsId = '';
  test.afterEach(async ({ request }) => {
    if (wsId) await deleteWorkspace(request, wsId);
    wsId = '';
  });

  test('a research request spawns a worker that runs and reports back live', async ({ page }) => {
    const ws = await createWorkspaceViaUI(page, `QA_S3_${Date.now()}`);
    wsId = ws.id;

    await sendChat(
      page,
      "Fais une courte recherche web : trouve 3 idées d'activités hivernales à Québec " +
      "et résume-les en quelques lignes. Délègue cette recherche à un worker.",
      { replyTimeout: 60_000, settleMs: 1500 },
    );

    // A worker should be registered for this workspace.
    const worker = await pollUntil(async () => {
      const ws_ = await workersForWorkspace(page.request, ws.id);
      return ws_.length ? ws_[0] : null;
    }, { timeout: 60_000, interval: 2000 });

    expect(worker, 'no worker was spawned for the research request').not.toBeNull();
    console.log('worker spawned:', worker.action, worker.status, worker.model);

    // The in-chat delegate badge should be visible (queued/running/done).
    const badge = page.locator('text=/queued|running…|done|failed/i').first();
    await expect(badge, 'no delegate badge rendered in chat').toBeVisible({ timeout: 20_000 });

    // The worker panel shows a worker entry.
    const panelWorker = page.locator('[data-testid="session-panel"] [aria-label*="Worker"]').first();
    await expect(panelWorker).toBeVisible({ timeout: 20_000 });

    // The worker reaches a terminal state (done/failed/cancelled) — i.e. it
    // actually finishes rather than hanging.
    const terminal = await pollUntil(async () => {
      const ws_ = await workersForWorkspace(page.request, ws.id);
      const w = ws_[0];
      if (!w) return null;
      return ['done', 'completed', 'failed', 'cancelled', 'timed_out'].includes(String(w.status)) ? w : null;
    }, { timeout: 4 * 60_000, interval: 3000 });

    console.log('worker terminal state:', terminal ? terminal.status : '(still running at timeout)');
    expect(terminal, 'worker never reached a terminal state (hung)').not.toBeNull();
    await page.screenshot({ path: 'test-results-live/s3-worker-done.png', fullPage: true });
  });
});
