import { test, expect } from '@playwright/test';

const API_URL = process.env.VOXYFLOW_API_URL || 'http://localhost:8000';
const PROJECT_PATH = process.env.VOXYFLOW_PROJECT_PATH || '~/.openclaw/workspace/voxyflow';

test.describe('Tech Stack Detection', () => {
  test('API: detects technologies in voxyflow project', async ({ request }) => {
    const response = await request.get(
      `${API_URL}/api/tech/detect?project_path=${encodeURIComponent(PROJECT_PATH)}`
    );
    expect(response.ok()).toBe(true);

    const data = await response.json();
    expect(data.path).toBeTruthy();
    expect(data.technologies).toBeInstanceOf(Array);
    expect(data.technologies.length).toBeGreaterThan(0);
    expect(data.total_files).toBeGreaterThan(0);
    expect(data.file_counts).toBeTruthy();

    // Voxyflow should detect at least these
    const techNames = data.technologies.map((t: { name: string }) => t.name);
    expect(techNames).toContain('Python');
    expect(techNames).toContain('Node.js');
    expect(techNames).toContain('TypeScript');

    // Each tech should have required fields
    for (const tech of data.technologies) {
      expect(tech.name).toBeTruthy();
      expect(tech.icon).toBeTruthy();
      expect(tech.category).toBeTruthy();
      expect(tech.source).toBeTruthy();
    }

    // File counts should have common extensions
    // toHaveProperty('.ts') treats the dot as a path separator — use bracket access
    expect(data.file_counts['.ts']).toBeDefined();
    expect(data.file_counts['.ts']).toBeGreaterThan(0);
    expect(data.file_counts['.py']).toBeDefined();
    expect(data.file_counts['.py']).toBeGreaterThan(0);
  });

  test('API: returns error for non-existent path', async ({ request }) => {
    const response = await request.get(
      `${API_URL}/api/tech/detect?project_path=/nonexistent/path/xyz`
    );
    expect(response.ok()).toBe(true);

    const data = await response.json();
    expect(data.error).toBe('Path not found');
    expect(data.technologies).toEqual([]);
  });

  test('API: detects framework dependencies from package.json', async ({ request }) => {
    const response = await request.get(
      `${API_URL}/api/tech/detect?project_path=${encodeURIComponent(PROJECT_PATH + '/frontend')}`
    );
    expect(response.ok()).toBe(true);

    const data = await response.json();
    const techNames = data.technologies.map((t: { name: string }) => t.name);

    // Frontend should detect TypeScript and Playwright at minimum
    expect(techNames).toContain('TypeScript');
  });

  test('API: detects Python frameworks from requirements.txt', async ({ request }) => {
    const response = await request.get(
      `${API_URL}/api/tech/detect?project_path=${encodeURIComponent(PROJECT_PATH + '/backend')}`
    );
    expect(response.ok()).toBe(true);

    const data = await response.json();
    const techNames = data.technologies.map((t: { name: string }) => t.name);

    // Backend should detect Python + FastAPI
    expect(techNames).toContain('Python');
    expect(techNames).toContain('FastAPI');
  });
});
