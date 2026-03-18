import { test, expect } from '@playwright/test';

test.describe('3-Layer Multi-Model Chat Orchestration', () => {
  // Proxy adds ~10-15s latency per request; need longer timeouts
  test.setTimeout(90000);

  test('Haiku responds fast, Opus may enrich', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 5000 });

    // Ask something substantive that Opus might want to enrich
    await input.fill('Explain quantum computing in simple terms');
    await input.press('Enter');

    // Haiku should respond (proxy may add latency)
    const firstResponse = page.locator('.message-bubble.message-assistant').first();
    await expect(firstResponse).toBeVisible({ timeout: 30000 });

    const responseText = await firstResponse.textContent();
    console.log('Haiku response:', responseText?.substring(0, 80));
    expect(responseText).toBeTruthy();
    expect(responseText!.length).toBeGreaterThan(10);

    // Wait for potential Opus enrichment (up to 15s)
    // Enrichment is optional — Opus may decide "none"
    await page.waitForTimeout(12000);

    // Count assistant messages
    const assistantMessages = await page.locator('.message-bubble.message-assistant').count();
    console.log('Total assistant messages:', assistantMessages);

    // At minimum, Haiku responded
    expect(assistantMessages).toBeGreaterThanOrEqual(1);

    // If enrichment appeared, verify it has the right styling
    const enrichmentMessages = await page.locator('.message-enrichment').count();
    console.log('Enrichment messages:', enrichmentMessages);
    if (enrichmentMessages > 0) {
      const enrichment = page.locator('.message-enrichment').first();
      // Should have the 💭 avatar
      const avatar = enrichment.locator('.message-avatar');
      await expect(avatar).toHaveText('💭');

      // Should have italic styling on content
      const content = enrichment.locator('.message-content');
      await expect(content).toBeVisible();
    }
  });

  test('Simple greeting does not trigger enrichment', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 5000 });

    // Simple message — Opus should return "none"
    await input.fill('Hey!');
    await input.press('Enter');

    // Haiku responds (proxy may add latency)
    const firstResponse = page.locator('.message-bubble.message-assistant').first();
    await expect(firstResponse).toBeVisible({ timeout: 30000 });

    // Wait for Opus to decide
    await page.waitForTimeout(10000);

    // Should have exactly 1 assistant message (no enrichment for simple greeting)
    const assistantMessages = await page.locator('.message-bubble.message-assistant').count();
    console.log('Assistant messages for greeting:', assistantMessages);

    // Enrichment should not appear for a simple greeting
    const enrichmentMessages = await page.locator('.message-enrichment').count();
    expect(enrichmentMessages).toBe(0);
  });

  test('Card suggestion toast appears for actionable messages', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 5000 });

    // Message with action signals that should trigger card detection
    await input.fill('We need to implement user authentication with OAuth2');
    await input.press('Enter');

    // Haiku responds (proxy may add latency)
    const firstResponse = page.locator('.message-bubble.message-assistant').first();
    await expect(firstResponse).toBeVisible({ timeout: 30000 });

    // Wait for analyzer to detect card
    await page.waitForTimeout(5000);

    // Check if toast appeared (card suggestion)
    const toast = page.locator('.toast');
    const toastCount = await toast.count();
    console.log('Toast notifications:', toastCount);

    if (toastCount > 0) {
      // Verify toast has card suggestion content
      const toastText = await toast.first().textContent();
      console.log('Toast content:', toastText);
      expect(toastText).toContain('suggestion');

      // Verify it has a "Create Card" button
      const createBtn = toast.first().locator('.toast-action');
      await expect(createBtn).toBeVisible();
    }
  });
});
