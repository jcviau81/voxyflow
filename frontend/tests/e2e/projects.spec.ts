import { test, expect } from '@playwright/test';

const API = 'http://localhost:8000/api';

/**
 * Helper: create a project via API and return its data.
 */
async function createProject(
  request: import('@playwright/test').APIRequestContext,
  title: string,
  description = '',
) {
  const res = await request.post(`${API}/projects`, {
    data: { title, description },
  });
  expect(res.status()).toBe(201);
  return res.json();
}

/**
 * Helper: create a card for a project via API.
 */
async function createCard(
  request: import('@playwright/test').APIRequestContext,
  projectId: string,
  title: string,
  status = 'todo',
) {
  const res = await request.post(`${API}/projects/${projectId}/cards`, {
    data: { title, description: '', status, priority: 1 },
  });
  expect(res.status()).toBe(201);
  return res.json();
}

/**
 * Helper: list active projects.
 */
async function listActiveProjects(request: import('@playwright/test').APIRequestContext) {
  const res = await request.get(`${API}/projects`, { params: { archived: 'false' } });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

/**
 * Helper: list archived projects.
 */
async function listArchivedProjects(request: import('@playwright/test').APIRequestContext) {
  const res = await request.get(`${API}/projects`, { params: { archived: 'true' } });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

/**
 * Helper: delete a project (cleanup).
 */
async function deleteProject(
  request: import('@playwright/test').APIRequestContext,
  projectId: string,
) {
  await request.delete(`${API}/projects/${projectId}`);
}

test.describe('Projects API — CRUD & Lifecycle', () => {
  // Track created project IDs for cleanup
  const createdIds: string[] = [];

  test.afterEach(async ({ request }) => {
    // Cleanup all projects created during test
    for (const id of createdIds) {
      // Restore first in case it's archived (delete might work on archived too)
      await request.post(`${API}/projects/${id}/restore`).catch(() => {});
      await request.delete(`${API}/projects/${id}`).catch(() => {});
    }
    createdIds.length = 0;
  });

  test('Create a project', async ({ request }) => {
    const project = await createProject(request, 'Test Project Alpha', 'A test project');
    createdIds.push(project.id);

    expect(project.title).toBe('Test Project Alpha');
    expect(project.description).toBe('A test project');
    expect(project.status).toBe('active');
    expect(project.id).toBeTruthy();
    expect(project.created_at).toBeTruthy();
    expect(project.updated_at).toBeTruthy();
  });

  test('Created project appears in active project list', async ({ request }) => {
    const project = await createProject(request, 'Visible Project');
    createdIds.push(project.id);

    const projects = await listActiveProjects(request);
    const found = projects.find((p: any) => p.id === project.id);
    expect(found).toBeTruthy();
    expect(found.title).toBe('Visible Project');
  });

  test('Rename a project via PATCH', async ({ request }) => {
    const project = await createProject(request, 'Old Name');
    createdIds.push(project.id);

    const res = await request.patch(`${API}/projects/${project.id}`, {
      data: { title: 'New Name' },
    });
    expect(res.ok()).toBeTruthy();
    const updated = await res.json();
    expect(updated.title).toBe('New Name');

    // Verify via GET
    const getRes = await request.get(`${API}/projects/${project.id}`);
    expect(getRes.ok()).toBeTruthy();
    const fetched = await getRes.json();
    expect(fetched.title).toBe('New Name');
  });

  test('Archive a project — disappears from active list', async ({ request }) => {
    const project = await createProject(request, 'To Be Archived');
    createdIds.push(project.id);

    // Archive it
    const archiveRes = await request.post(`${API}/projects/${project.id}/archive`);
    expect(archiveRes.ok()).toBeTruthy();
    const archived = await archiveRes.json();
    expect(archived.status).toBe('archived');

    // Should NOT appear in active list
    const activeProjects = await listActiveProjects(request);
    const foundActive = activeProjects.find((p: any) => p.id === project.id);
    expect(foundActive).toBeFalsy();

    // Should appear in archived list
    const archivedProjects = await listArchivedProjects(request);
    const foundArchived = archivedProjects.find((p: any) => p.id === project.id);
    expect(foundArchived).toBeTruthy();
    expect(foundArchived.status).toBe('archived');
  });

  test('Restore an archived project — returns to active list', async ({ request }) => {
    const project = await createProject(request, 'To Be Restored');
    createdIds.push(project.id);

    // Archive first
    await request.post(`${API}/projects/${project.id}/archive`);

    // Verify it's gone from active
    let activeProjects = await listActiveProjects(request);
    expect(activeProjects.find((p: any) => p.id === project.id)).toBeFalsy();

    // Restore
    const restoreRes = await request.post(`${API}/projects/${project.id}/restore`);
    expect(restoreRes.ok()).toBeTruthy();
    const restored = await restoreRes.json();
    expect(restored.status).toBe('active');

    // Should be back in active list
    activeProjects = await listActiveProjects(request);
    const found = activeProjects.find((p: any) => p.id === project.id);
    expect(found).toBeTruthy();
    expect(found.status).toBe('active');

    // Should NOT be in archived list
    const archivedProjects = await listArchivedProjects(request);
    expect(archivedProjects.find((p: any) => p.id === project.id)).toBeFalsy();
  });

  test('Delete a project permanently', async ({ request }) => {
    const project = await createProject(request, 'To Be Deleted');
    // Don't add to createdIds since we're deleting it here

    // Delete
    const delRes = await request.delete(`${API}/projects/${project.id}`);
    expect(delRes.status()).toBe(204);

    // Should not appear anywhere
    const activeProjects = await listActiveProjects(request);
    expect(activeProjects.find((p: any) => p.id === project.id)).toBeFalsy();

    const archivedProjects = await listArchivedProjects(request);
    expect(archivedProjects.find((p: any) => p.id === project.id)).toBeFalsy();

    // GET should return 404
    const getRes = await request.get(`${API}/projects/${project.id}`);
    expect(getRes.status()).toBe(404);
  });

  test('Cards of an archived project are preserved', async ({ request }) => {
    const project = await createProject(request, 'Project With Cards');
    createdIds.push(project.id);

    // Create cards
    await createCard(request, project.id, 'Card Alpha');
    await createCard(request, project.id, 'Card Beta');
    await createCard(request, project.id, 'Card Gamma');

    // Archive the project
    await request.post(`${API}/projects/${project.id}/archive`);

    // Fetch project details — cards should still be there
    const getRes = await request.get(`${API}/projects/${project.id}`);
    expect(getRes.status()).toBe(200);
    const projectData = await getRes.json();

    expect(projectData.status).toBe('archived');
    expect(projectData.cards).toHaveLength(3);

    const cardTitles = projectData.cards.map((c: any) => c.title).sort();
    expect(cardTitles).toEqual(['Card Alpha', 'Card Beta', 'Card Gamma']);
  });

  test('Cards of a deleted project are erased', async ({ request }) => {
    const project = await createProject(request, 'Project To Nuke');

    // Create cards
    const card1 = await createCard(request, project.id, 'Doomed Card 1');
    const card2 = await createCard(request, project.id, 'Doomed Card 2');

    // Delete the project
    const delRes = await request.delete(`${API}/projects/${project.id}`);
    expect(delRes.status()).toBe(204);

    // Project should be gone
    const getRes = await request.get(`${API}/projects/${project.id}`);
    expect(getRes.status()).toBe(404);

    // Cards should also be gone — try to fetch them individually
    const card1Res = await request.get(`${API}/cards/${card1.id}`);
    expect(card1Res.status()).toBe(404);

    const card2Res = await request.get(`${API}/cards/${card2.id}`);
    expect(card2Res.status()).toBe(404);
  });

  test('Multiple projects — archive filter works correctly', async ({ request }) => {
    // Create 4 projects
    const p1 = await createProject(request, 'Filter Test Active 1');
    const p2 = await createProject(request, 'Filter Test Active 2');
    const p3 = await createProject(request, 'Filter Test Archived 1');
    const p4 = await createProject(request, 'Filter Test Archived 2');
    createdIds.push(p1.id, p2.id, p3.id, p4.id);

    // Archive two of them
    await request.post(`${API}/projects/${p3.id}/archive`);
    await request.post(`${API}/projects/${p4.id}/archive`);

    // Active list should have p1, p2 but NOT p3, p4
    const activeProjects = await listActiveProjects(request);
    const activeIds = activeProjects.map((p: any) => p.id);
    expect(activeIds).toContain(p1.id);
    expect(activeIds).toContain(p2.id);
    expect(activeIds).not.toContain(p3.id);
    expect(activeIds).not.toContain(p4.id);

    // Archived list should have p3, p4 but NOT p1, p2
    const archivedProjects = await listArchivedProjects(request);
    const archivedIds = archivedProjects.map((p: any) => p.id);
    expect(archivedIds).toContain(p3.id);
    expect(archivedIds).toContain(p4.id);
    expect(archivedIds).not.toContain(p1.id);
    expect(archivedIds).not.toContain(p2.id);
  });

  test('Archive and restore cycle preserves project data', async ({ request }) => {
    const project = await createProject(request, 'Cycle Test Project', 'Cycle description');
    createdIds.push(project.id);

    // Add cards
    await createCard(request, project.id, 'Persistent Card');

    // Archive → Restore → Archive → Restore
    await request.post(`${API}/projects/${project.id}/archive`);
    await request.post(`${API}/projects/${project.id}/restore`);
    await request.post(`${API}/projects/${project.id}/archive`);
    await request.post(`${API}/projects/${project.id}/restore`);

    // Verify data integrity
    const getRes = await request.get(`${API}/projects/${project.id}`);
    const data = await getRes.json();
    expect(data.title).toBe('Cycle Test Project');
    expect(data.description).toBe('Cycle description');
    expect(data.status).toBe('active');
    expect(data.cards).toHaveLength(1);
    expect(data.cards[0].title).toBe('Persistent Card');
  });

  test('Delete non-existent project returns 404', async ({ request }) => {
    const res = await request.delete(`${API}/projects/non-existent-id-12345`);
    expect(res.status()).toBe(404);
  });

  test('Archive non-existent project returns 404', async ({ request }) => {
    const res = await request.post(`${API}/projects/non-existent-id-12345/archive`);
    expect(res.status()).toBe(404);
  });

  test('Restore non-existent project returns 404', async ({ request }) => {
    const res = await request.post(`${API}/projects/non-existent-id-12345/restore`);
    expect(res.status()).toBe(404);
  });
});
