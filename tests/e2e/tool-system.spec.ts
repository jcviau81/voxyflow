import { test, expect } from '@playwright/test';

test.describe('Tool System — AI Agent Tools', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('http://localhost:3000');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.waitForLoadState('networkidle');
  });

  test('Tool definitions API returns registered tools', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/tools/definitions');
    expect(response.status()).toBe(200);

    const tools = await response.json();
    expect(Array.isArray(tools)).toBe(true);
    expect(tools.length).toBeGreaterThan(0);

    // Verify expected tools are registered
    const toolNames = tools.map((t: any) => t.name);
    expect(toolNames).toContain('create_project');
    expect(toolNames).toContain('create_card');
    expect(toolNames).toContain('move_card');
    expect(toolNames).toContain('list_projects');
    expect(toolNames).toContain('search_cards');
    expect(toolNames).toContain('open_project');
    expect(toolNames).toContain('show_kanban');
    expect(toolNames).toContain('show_chat');
  });

  test('Tool definitions have proper schema', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/tools/definitions');
    const tools = await response.json();

    for (const tool of tools) {
      expect(tool).toHaveProperty('name');
      expect(tool).toHaveProperty('description');
      expect(tool).toHaveProperty('parameters');
      expect(typeof tool.name).toBe('string');
      expect(typeof tool.description).toBe('string');
    }
  });

  test('Execute create_project tool via API', async ({ request }) => {
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: {
          title: 'Test Project from Tool',
          description: 'Created via tool system',
        },
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.data.title).toBe('Test Project from Tool');
    expect(result.data.id).toBeTruthy();
    expect(result.ui_action).toBe('open_project_tab');
  });

  test('Execute list_projects tool via API', async ({ request }) => {
    // Create a project first
    await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: { title: 'Listable Project' },
      },
    });

    // List projects
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'list_projects',
        params: {},
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(Array.isArray(result.data)).toBe(true);
    expect(result.data.length).toBeGreaterThan(0);
  });

  test('Execute create_card tool via API', async ({ request }) => {
    // Create project first
    const projResp = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: { title: 'Card Host Project' },
      },
    });
    const project = (await projResp.json()).data;

    // Create card
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_card',
        params: {
          project_id: project.id,
          title: 'Test Card from Tool',
          description: 'Testing card creation',
          priority: 2,
        },
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.data.title).toBe('Test Card from Tool');
    expect(result.data.id).toBeTruthy();
    expect(result.ui_action).toBe('refresh_kanban');
  });

  test('Execute move_card tool via API', async ({ request }) => {
    // Create project + card
    const projResp = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: { title: 'Move Test Project' },
      },
    });
    const project = (await projResp.json()).data;

    const cardResp = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_card',
        params: { project_id: project.id, title: 'Moveable Card' },
      },
    });
    const card = (await cardResp.json()).data;

    // Move card
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'move_card',
        params: { card_id: card.id, new_status: 'in_progress' },
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.data.new_status).toBe('in_progress');
    expect(result.data.old_status).toBe('idea');
  });

  test('Execute unknown tool returns error', async ({ request }) => {
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'nonexistent_tool',
        params: {},
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(false);
    expect(result.error).toContain('Unknown tool');
  });

  test('Navigation tools return UI actions', async ({ request }) => {
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'show_kanban',
        params: {},
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.ui_action).toBe('show_kanban');
    expect(result.data.view).toBe('kanban');
  });

  test('get_project_status returns summary', async ({ request }) => {
    // Create project + cards in different statuses
    const projResp = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: { title: 'Status Test Project' },
      },
    });
    const project = (await projResp.json()).data;

    // Create cards in various statuses
    for (const status of ['idea', 'todo', 'in_progress', 'done']) {
      await request.post('http://localhost:8000/api/tools/execute', {
        data: {
          name: 'create_card',
          params: { project_id: project.id, title: `Card ${status}`, status },
        },
      });
    }

    // Get status
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'get_project_status',
        params: { project_id: project.id },
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.data.total_cards).toBe(4);
    expect(result.data.completion_pct).toBe(25.0);
  });

  test('search_cards finds matching cards', async ({ request }) => {
    // Create project + card
    const projResp = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_project',
        params: { title: 'Search Test' },
      },
    });
    const project = (await projResp.json()).data;

    await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'create_card',
        params: {
          project_id: project.id,
          title: 'Fix authentication bug',
          description: 'OAuth flow is broken',
        },
      },
    });

    // Search
    const response = await request.post('http://localhost:8000/api/tools/execute', {
      data: {
        name: 'search_cards',
        params: { query: 'authentication' },
      },
    });

    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.success).toBe(true);
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].title).toContain('authentication');
  });
});
