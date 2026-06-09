import { expect, type Page, type APIRequestContext } from '@playwright/test';

/**
 * Shared helpers for live scenario specs. They drive the real backend-served
 * app on :8000 (no auth), bypass onboarding, and provide robust waits for the
 * LLM-driven, streaming, WS-realtime flows.
 */

/** Bypass the onboarding guard for a clean browser profile. */
export async function bypassOnboarding(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem('onboarding_complete', 'true');
    } catch { /* ignore */ }
  });
}

/** Navigate with onboarding bypassed and wait for the SPA to settle. */
export async function gotoApp(page: Page, path = '/') {
  await bypassOnboarding(page);
  await page.goto(path);
  await page.waitForLoadState('networkidle');
}

/**
 * Open a workspace board by id and confirm we actually landed on it. When a
 * workspace was created via the API *after* the SPA cached its workspace list,
 * a direct /workspace/:id nav can fall back to Home — so we wait for the
 * workspace tab and reload once if it didn't open.
 */
export async function openWorkspace(page: Page, id: string) {
  await bypassOnboarding(page);
  await page.goto(`/workspace/${id}`);
  const tab = page.locator(`[data-testid="tab-${id}"]`);
  try {
    await expect(tab).toBeVisible({ timeout: 8_000 });
  } catch {
    await page.reload();
    await expect(tab).toBeVisible({ timeout: 15_000 });
  }
  await page.waitForLoadState('networkidle');
  await expect(page.locator('[data-testid="kanban-board"]')).toBeVisible({ timeout: 15_000 });
}

export interface Workspace { id: string; title: string }

/**
 * Create a workspace the way a real user does — via the UI form — so it lands
 * in the store and becomes the active board immediately (no API/cache race).
 * Returns the new workspace id parsed from the resulting /workspace/:id URL.
 */
export async function createWorkspaceViaUI(page: Page, title: string): Promise<Workspace> {
  await gotoApp(page, '/workspaces');
  await page.locator('[data-testid="new-workspace-btn"]').click();
  const form = page.locator('[data-testid="workspace-form"]');
  await expect(form).toBeVisible({ timeout: 10_000 });
  await page.locator('[data-testid="workspace-name-input"]').fill(title);
  await page.locator('[data-testid="workspace-form-submit"]').click();

  // Submit creates the workspace and returns to the list (no auto-nav). The
  // new card is now in the store — click it to open its board (activates it).
  await expect(form).toBeHidden({ timeout: 10_000 });
  await page.getByText(title, { exact: true }).first().click();
  await page.waitForURL(/\/workspace\/[0-9a-f-]+/, { timeout: 15_000 });
  await expect(page.locator('[data-testid="kanban-board"]')).toBeVisible({ timeout: 15_000 });
  const m = page.url().match(/\/workspace\/([0-9a-f-]+)/);
  const id = m?.[1] ?? '';
  expect(id, 'could not parse workspace id from URL').not.toEqual('');
  return { id, title };
}

export async function createWorkspace(request: APIRequestContext, title: string, description = ''): Promise<Workspace> {
  const res = await request.post('/api/workspaces', { data: { title, description } });
  expect(res.ok(), `create workspace failed: ${res.status()}`).toBeTruthy();
  const ws = await res.json();
  return { id: ws.id, title: ws.title ?? title };
}

export async function deleteWorkspace(request: APIRequestContext, id: string) {
  try { await request.delete(`/api/workspaces/${id}`); } catch { /* best effort */ }
}

export async function listCards(request: APIRequestContext, workspaceId: string): Promise<any[]> {
  const res = await request.get(`/api/workspaces/${workspaceId}/cards`);
  if (!res.ok()) return [];
  return res.json();
}

/** Worker tasks the backend currently knows about for a workspace (active + recent). */
export async function workersForWorkspace(request: APIRequestContext, workspaceId: string): Promise<any[]> {
  const res = await request.get(`/api/workers/snapshot?workspace_id=${encodeURIComponent(workspaceId)}`);
  if (!res.ok()) return [];
  const data = await res.json();
  const workers = (data.workers ?? []) as any[];
  return workers.filter((w) => w.workspaceId === workspaceId);
}

/** Poll until `fn` returns a truthy value or the timeout elapses. */
export async function pollUntil<T>(fn: () => Promise<T>, opts: { timeout?: number; interval?: number } = {}): Promise<T | null> {
  const timeout = opts.timeout ?? 60_000;
  const interval = opts.interval ?? 1500;
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const v = await fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, interval));
  }
  return null;
}

/** Count chat message bubbles currently rendered. */
export async function bubbleCount(page: Page): Promise<number> {
  return page.locator('[data-message-id]').count();
}

/**
 * Send a chat message and wait until an assistant reply has rendered AND
 * finished streaming. Robust to the non-deterministic LLM: waits for the
 * bubble count to grow and for the last bubble's text to stabilise.
 */
export async function sendChat(
  page: Page,
  text: string,
  opts: { replyTimeout?: number; settleMs?: number } = {},
) {
  const replyTimeout = opts.replyTimeout ?? 90_000;
  const settleMs = opts.settleMs ?? 2500;

  const textarea = page.locator('[data-testid="chat-input-textarea"]');
  await expect(textarea).toBeVisible({ timeout: 15_000 });
  const before = await bubbleCount(page);

  await textarea.click();
  await textarea.fill(text);
  await page.locator('[data-testid="chat-input-send"]').click();

  // Wait for user + assistant bubbles to appear (count grows by >=2).
  await expect.poll(async () => bubbleCount(page), { timeout: replyTimeout, intervals: [500] })
    .toBeGreaterThanOrEqual(before + 2);

  // Wait for the last bubble's text to stop changing (streaming finished).
  let last = '';
  let stableSince = Date.now();
  const deadline = Date.now() + replyTimeout;
  while (Date.now() < deadline) {
    const cur = (await page.locator('[data-message-id]').last().innerText().catch(() => '')) || '';
    if (cur !== last) { last = cur; stableSince = Date.now(); }
    else if (Date.now() - stableSince > settleMs) break;
    await page.waitForTimeout(400);
  }
  return last;
}

/** Locate the most recent assistant (non-user) bubble text. */
export async function lastAssistantText(page: Page): Promise<string> {
  const bubbles = page.locator('[data-message-id]');
  const n = await bubbles.count();
  for (let i = n - 1; i >= 0; i--) {
    const b = bubbles.nth(i);
    const cls = (await b.getAttribute('class')) || '';
    if (!cls.includes('self-end')) {
      return (await b.innerText().catch(() => '')) || '';
    }
  }
  return '';
}
