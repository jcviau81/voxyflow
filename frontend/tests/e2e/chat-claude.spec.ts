import { test, expect } from '@playwright/test';

test.describe('Chat → Claude Integration', () => {
  // Proxy adds ~10-15s latency; increase test timeout
  test.setTimeout(60000);

  test('Chat sends message and receives Claude response', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Make sure chat input is visible
    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 10000 });

    // Type message and send
    await input.fill('Hello, who are you?');
    await input.press('Enter');

    // Wait for assistant response to appear (proxy may add ~10-15s latency)
    const assistantMsg = page.locator('.message-bubble.message-assistant');
    await assistantMsg.waitFor({ state: 'visible', timeout: 45000 });

    // Get content once streaming is done (wait for non-empty stable text)
    await page.waitForFunction(
      () => {
        const msgs = document.querySelectorAll('.message-bubble.message-assistant');
        if (!msgs.length) return false;
        const last = msgs[msgs.length - 1];
        return last.textContent && last.textContent.trim().length > 10;
      },
      { timeout: 45000 }
    );

    const lastMsg = assistantMsg.last();
    const responseText = await lastMsg.textContent();
    console.log('Claude response received:', responseText?.substring(0, 150));

    expect(responseText).toBeTruthy();
    expect(responseText!.trim().length).toBeGreaterThan(10);
  });
});
