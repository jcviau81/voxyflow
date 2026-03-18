import { test, expect } from '@playwright/test';

test.describe('Opus Steering — Conservative Enrichment', () => {
  test('Simple greeting does not trigger Opus enrichment', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    // Send a simple greeting
    const input = page.locator('[data-testid="chat-input"], textarea, input[type="text"]').first();
    await input.fill('hi');
    await input.press('Enter');

    // Wait for Haiku response
    const haiku = page.locator('[data-model="haiku"], .message-haiku').first();
    await expect(haiku).toBeVisible({ timeout: 15000 });

    // Wait a reasonable time for Opus to potentially respond
    await page.waitForTimeout(5000);

    // No enrichment message should appear
    const enrichment = page.locator('[data-enrichment="true"], .message-opus, .enrichment');
    await expect(enrichment).toHaveCount(0);
  });

  test('Casual conversation does not trigger Opus enrichment', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"], textarea, input[type="text"]').first();
    await input.fill("what's up?");
    await input.press('Enter');

    // Wait for Haiku response
    const haiku = page.locator('[data-model="haiku"], .message-haiku').first();
    await expect(haiku).toBeVisible({ timeout: 15000 });

    // Wait for potential Opus response
    await page.waitForTimeout(5000);

    // No enrichment
    const enrichment = page.locator('[data-enrichment="true"], .message-opus, .enrichment');
    await expect(enrichment).toHaveCount(0);
  });

  test('Complex technical question may trigger Opus enrichment', async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"], textarea, input[type="text"]').first();
    await input.fill(
      'Explain the differences between optimistic and pessimistic concurrency control in distributed databases, and when you would choose one over the other.'
    );
    await input.press('Enter');

    // Wait for Haiku response first
    const haiku = page.locator('[data-model="haiku"], .message-haiku').first();
    await expect(haiku).toBeVisible({ timeout: 15000 });

    // Wait for Opus to potentially respond (not guaranteed — just verify flow works)
    await page.waitForTimeout(10000);

    // If enrichment appears, it should have content
    const enrichment = page.locator('[data-enrichment="true"], .message-opus, .enrichment');
    const count = await enrichment.count();
    if (count > 0) {
      const text = await enrichment.first().textContent();
      expect(text).toBeTruthy();
      expect(text!.length).toBeGreaterThan(10);
    }
    // If no enrichment, that's also valid — Opus decided Haiku was good enough
  });
});
