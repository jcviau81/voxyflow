import { test, expect } from '@playwright/test';

test('Capture all console errors on page load', async ({ page }) => {
  const errors: string[] = [];
  const warnings: string[] = [];
  const logs: string[] = [];
  
  // Listen to ALL console messages
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
    else if (msg.type() === 'warning') warnings.push(msg.text());
    else logs.push(msg.text());
  });
  
  // Listen to page errors (uncaught exceptions)
  page.on('pageerror', error => {
    errors.push(`PAGE ERROR: ${error.message}`);
  });
  
  // Navigate and wait for full load
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle' });
  
  // Wait extra time for async operations
  await page.waitForTimeout(5000);
  
  // Click around to trigger more potential errors
  // Try clicking sidebar items
  const sidebarItems = await page.locator('[data-testid="sidebar"] a, [data-testid="sidebar"] button').all();
  for (const item of sidebarItems) {
    try { await item.click({ timeout: 2000 }); } catch {}
    await page.waitForTimeout(500);
  }
  
  // Try switching views
  for (const view of ['chat', 'kanban', 'projects']) {
    const viewBtn = page.locator(`[data-view="${view}"]`);
    if (await viewBtn.isVisible()) {
      await viewBtn.click();
      await page.waitForTimeout(1000);
    }
  }
  
  // Print all findings
  console.log('=== CONSOLE ERRORS ===');
  errors.forEach(e => console.log(`❌ ${e}`));
  console.log(`\n=== WARNINGS (${warnings.length}) ===`);
  warnings.forEach(w => console.log(`⚠️ ${w}`));
  console.log(`\n=== LOGS (${logs.length}) ===`);
  logs.slice(0, 20).forEach(l => console.log(`📝 ${l}`));
  
  // Take screenshot
  await page.screenshot({ path: '/tmp/voxyflow-screenshot.png', fullPage: true });
  
  // Report
  console.log(`\n=== SUMMARY ===`);
  console.log(`Errors: ${errors.length}`);
  console.log(`Warnings: ${warnings.length}`);
  console.log(`Logs: ${logs.length}`);
  
  // Fail test if there are errors
  if (errors.length > 0) {
    console.log('\n=== ALL ERRORS FOR FIXING ===');
    errors.forEach((e, i) => console.log(`Error ${i+1}: ${e}`));
  }
});
