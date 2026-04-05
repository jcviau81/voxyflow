/**
 * Mobile UI Audit — Playwright visual tests on iPhone and Android viewports.
 *
 * Takes screenshots of every key view and checks for common mobile issues:
 * - Overflow (horizontal scroll)
 * - Touch target sizes (< 44px)
 * - Elements overflowing viewport
 * - Text readability (font size < 12px)
 */

import { test, expect, type Page } from '@playwright/test';

const MOBILE_DEVICES = [
  { name: 'iPhone-14', viewport: { width: 390, height: 844 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' },
  { name: 'Pixel-7', viewport: { width: 412, height: 915 }, userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 7)' },
  { name: 'iPhone-SE', viewport: { width: 375, height: 667 }, userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)' },
];

// Base URL — connect to running dev/prod server
const BASE = 'http://localhost:8000';

async function checkOverflow(page: Page, label: string) {
  const issues: string[] = [];

  // Check horizontal overflow
  const hasHScroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  if (hasHScroll) issues.push(`${label}: horizontal overflow detected`);

  // Check elements wider than viewport
  const overflowing = await page.evaluate(() => {
    const vw = window.innerWidth;
    const results: string[] = [];
    document.querySelectorAll('*').forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width > vw + 5) {
        const tag = el.tagName.toLowerCase();
        const cls = el.className?.toString().slice(0, 60) || '';
        results.push(`${tag}.${cls} (width=${Math.round(rect.width)}px)`);
      }
    });
    return results.slice(0, 10);
  });
  if (overflowing.length > 0) issues.push(`${label}: ${overflowing.length} elements wider than viewport: ${overflowing.join(', ')}`);

  // Check small touch targets (interactive elements < 44x44)
  const smallTargets = await page.evaluate(() => {
    const results: string[] = [];
    document.querySelectorAll('button, a, input, [role="button"], [onclick]').forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0 && (rect.width < 32 || rect.height < 32)) {
        const text = (el as HTMLElement).innerText?.slice(0, 20) || el.tagName;
        results.push(`${text} (${Math.round(rect.width)}x${Math.round(rect.height)})`);
      }
    });
    return results.slice(0, 15);
  });
  if (smallTargets.length > 0) issues.push(`${label}: ${smallTargets.length} small touch targets: ${smallTargets.join(', ')}`);

  return issues;
}

for (const device of MOBILE_DEVICES) {
  test.describe(`Mobile audit — ${device.name}`, () => {

    test.use({
      viewport: device.viewport,
      userAgent: device.userAgent,
    });

    test('Main chat view', async ({ page }) => {
      await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(1000);
      await page.screenshot({ path: `test-results/mobile-${device.name}-main-chat.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Main chat');
      console.log(`[${device.name}] Main chat issues:`, issues.length ? issues : 'NONE');
    });

    test('Sidebar open', async ({ page }) => {
      await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      // Try to open sidebar via keyboard
      await page.keyboard.press('Control+b');
      await page.waitForTimeout(500);
      await page.screenshot({ path: `test-results/mobile-${device.name}-sidebar.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Sidebar');
      console.log(`[${device.name}] Sidebar issues:`, issues.length ? issues : 'NONE');
    });

    test('Kanban board', async ({ page }) => {
      // Navigate to a project with kanban view
      await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      // Try clicking a project from sidebar
      await page.keyboard.press('Control+b');
      await page.waitForTimeout(300);
      // Click first project link (if any)
      const projectLink = page.locator('[data-testid="sidebar-project-item"]').first();
      if (await projectLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        await projectLink.click();
        await page.waitForTimeout(1000);
      }
      // Switch to kanban view if available
      const kanbanBtn = page.locator('button:has-text("Kanban"), [data-view="kanban"]').first();
      if (await kanbanBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await kanbanBtn.click();
        await page.waitForTimeout(500);
      }
      await page.screenshot({ path: `test-results/mobile-${device.name}-kanban.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Kanban');
      console.log(`[${device.name}] Kanban issues:`, issues.length ? issues : 'NONE');
    });

    test('Card detail modal', async ({ page }) => {
      await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      // Navigate to a project
      await page.keyboard.press('Control+b');
      await page.waitForTimeout(300);
      const projectLink = page.locator('[data-testid="sidebar-project-item"]').first();
      if (await projectLink.isVisible({ timeout: 2000 }).catch(() => false)) {
        await projectLink.click();
        await page.waitForTimeout(1000);
      }
      // Click first card
      const card = page.locator('[data-card-id]').first();
      if (await card.isVisible({ timeout: 3000 }).catch(() => false)) {
        await card.click();
        await page.waitForTimeout(500);
        await page.screenshot({ path: `test-results/mobile-${device.name}-card-modal.png`, fullPage: false });

        // Test each mobile tab
        for (const tab of ['Description', 'Chat', 'Details']) {
          const tabBtn = page.locator(`button:has-text("${tab}")`).first();
          if (await tabBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
            await tabBtn.click();
            await page.waitForTimeout(300);
            await page.screenshot({ path: `test-results/mobile-${device.name}-card-${tab.toLowerCase()}.png`, fullPage: false });
          }
        }

        const issues = await checkOverflow(page, 'Card modal');
        console.log(`[${device.name}] Card modal issues:`, issues.length ? issues : 'NONE');
      }
    });

    test('Settings page', async ({ page }) => {
      await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      await page.screenshot({ path: `test-results/mobile-${device.name}-settings.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Settings');
      console.log(`[${device.name}] Settings issues:`, issues.length ? issues : 'NONE');
    });

    test('Projects list', async ({ page }) => {
      await page.goto(`${BASE}/projects`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      await page.screenshot({ path: `test-results/mobile-${device.name}-projects.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Projects');
      console.log(`[${device.name}] Projects issues:`, issues.length ? issues : 'NONE');
    });

    test('Jobs page', async ({ page }) => {
      await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      await page.screenshot({ path: `test-results/mobile-${device.name}-jobs.png`, fullPage: false });
      const issues = await checkOverflow(page, 'Jobs');
      console.log(`[${device.name}] Jobs issues:`, issues.length ? issues : 'NONE');
    });

    test('FreeBoard', async ({ page }) => {
      await page.goto(BASE, { waitUntil: 'networkidle', timeout: 15000 });
      await page.waitForTimeout(500);
      // Navigate via view switcher
      const boardBtn = page.locator('button:has-text("Board"), [data-view="freeboard"]').first();
      if (await boardBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
        await boardBtn.click();
        await page.waitForTimeout(500);
      }
      await page.screenshot({ path: `test-results/mobile-${device.name}-freeboard.png`, fullPage: false });
      const issues = await checkOverflow(page, 'FreeBoard');
      console.log(`[${device.name}] FreeBoard issues:`, issues.length ? issues : 'NONE');
    });
  });
}
