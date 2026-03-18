import { test, expect } from '@playwright/test';

test.describe('Streaming Responses (SSE)', () => {
  test('First token appears quickly via streaming', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 10000 });

    // Record the time before sending
    const sendTime = Date.now();

    // Type and send a message
    await input.fill('Say hello in one sentence.');
    await input.press('Enter');

    // Wait for a streaming cursor to appear (indicates streaming started)
    // OR an assistant message with content — whichever comes first
    await page.waitForFunction(
      () => {
        const msgs = document.querySelectorAll('.message-bubble.message-assistant');
        if (!msgs.length) return false;
        const last = msgs[msgs.length - 1];
        // Either has streaming cursor or has some content
        return (
          last.querySelector('.streaming-cursor') !== null ||
          (last.textContent && last.textContent.trim().length > 0)
        );
      },
      { timeout: 10000 },
    );

    const firstTokenTime = Date.now();
    const firstTokenLatency = firstTokenTime - sendTime;
    console.log(`First token latency: ${firstTokenLatency}ms`);

    // First token should appear in < 30s (proxy adds ~10-15s latency)
    expect(firstTokenLatency).toBeLessThan(30000);

    // Wait for streaming to complete (cursor disappears, content stabilizes)
    await page.waitForFunction(
      () => {
        const msgs = document.querySelectorAll('.message-bubble.message-assistant');
        if (!msgs.length) return false;
        const last = msgs[msgs.length - 1];
        // No streaming cursor = done
        return (
          last.querySelector('.streaming-cursor') === null &&
          last.textContent &&
          last.textContent.trim().length > 5
        );
      },
      { timeout: 30000 },
    );

    // Verify the final message rendered correctly
    const lastMsg = page.locator('.message-bubble.message-assistant').last();
    const responseText = await lastMsg.textContent();
    console.log('Final streamed response:', responseText?.substring(0, 150));

    expect(responseText).toBeTruthy();
    expect(responseText!.trim().length).toBeGreaterThan(5);
  });

  test('Message renders correctly after stream completes', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    const input = page.locator('[data-testid="chat-input"]');
    await expect(input).toBeVisible({ timeout: 10000 });

    await input.fill('What is 2+2? Answer in one word.');
    await input.press('Enter');

    // Wait for full response (no streaming cursor)
    await page.waitForFunction(
      () => {
        const msgs = document.querySelectorAll('.message-bubble.message-assistant');
        if (!msgs.length) return false;
        const last = msgs[msgs.length - 1];
        return (
          last.querySelector('.streaming-cursor') === null &&
          last.textContent &&
          last.textContent.trim().length > 0
        );
      },
      { timeout: 30000 },
    );

    // Verify no streaming cursor remains
    const cursors = await page.locator('.streaming-cursor').count();
    expect(cursors).toBe(0);

    // Verify message content exists in the DOM
    const lastMsg = page.locator('.message-bubble.message-assistant .message-content').last();
    const html = await lastMsg.innerHTML();
    expect(html.length).toBeGreaterThan(0);
  });
});
