import { AppStateData } from '../src/types';

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: jest.fn((key: string) => store[key] || null),
    setItem: jest.fn((key: string, value: string) => { store[key] = value; }),
    removeItem: jest.fn((key: string) => { delete store[key]; }),
    clear: jest.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Must import after mocking
import { appState } from '../src/state/AppState';

describe('AppState', () => {
  beforeEach(() => {
    localStorageMock.clear();
    jest.clearAllMocks();
    appState.reset();
  });

  // --- Basic get/set ---

  test('should return default state values', () => {
    expect(appState.get('currentView')).toBe('chat');
    expect(appState.get('currentProjectId')).toBeNull();
    expect(appState.get('messages')).toEqual([]);
    expect(appState.get('sidebarOpen')).toBe(true);
    expect(appState.get('volume')).toBe(0.8);
  });

  test('should update state values', () => {
    appState.set('currentView', 'kanban');
    expect(appState.get('currentView')).toBe('kanban');
  });

  // --- Persistence ---

  test('should save to localStorage on set', () => {
    appState.set('volume', 0.5);
    expect(localStorageMock.setItem).toHaveBeenCalled();

    const stored = JSON.parse(localStorageMock.setItem.mock.calls[localStorageMock.setItem.mock.calls.length - 1][1]);
    expect(stored.volume).toBe(0.5);
  });

  test('should handle localStorage errors gracefully', () => {
    const consoleSpy = jest.spyOn(console, 'warn').mockImplementation();
    localStorageMock.setItem.mockImplementationOnce(() => {
      throw new Error('Storage full');
    });

    expect(() => appState.set('volume', 0.3)).not.toThrow();
    consoleSpy.mockRestore();
  });

  // --- Listeners ---

  test('should notify subscribers on state change', () => {
    const listener = jest.fn();
    appState.subscribe('currentView', listener);
    appState.set('currentView', 'projects');
    expect(listener).toHaveBeenCalledWith('projects');
  });

  test('should unsubscribe correctly', () => {
    const listener = jest.fn();
    const unsub = appState.subscribe('volume', listener);
    appState.set('volume', 0.5);
    expect(listener).toHaveBeenCalledTimes(1);

    unsub();
    appState.set('volume', 0.9);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  test('should handle listener errors gracefully', () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
    const errorListener = jest.fn(() => { throw new Error('Listener error'); });
    appState.subscribe('currentView', errorListener);

    expect(() => appState.set('currentView', 'kanban')).not.toThrow();
    consoleSpy.mockRestore();
  });

  // --- Messages ---

  test('should add messages with generated id and timestamp', () => {
    const msg = appState.addMessage({ role: 'user', content: 'Hello' });
    expect(msg.id).toBeDefined();
    expect(msg.timestamp).toBeGreaterThan(0);
    expect(msg.content).toBe('Hello');
    expect(appState.getMessages()).toHaveLength(1);
  });

  test('should update messages', () => {
    const msg = appState.addMessage({ role: 'assistant', content: 'Hi' });
    appState.updateMessage(msg.id, { content: 'Hello there!' });
    const messages = appState.getMessages();
    expect(messages[0].content).toBe('Hello there!');
  });

  test('should filter messages by project', () => {
    appState.addMessage({ role: 'user', content: 'A', projectId: 'p1' });
    appState.addMessage({ role: 'user', content: 'B', projectId: 'p2' });
    appState.addMessage({ role: 'user', content: 'C', projectId: 'p1' });

    expect(appState.getMessages('p1')).toHaveLength(2);
    expect(appState.getMessages('p2')).toHaveLength(1);
  });

  // --- Projects ---

  test('should create and retrieve projects', () => {
    const project = appState.addProject('Test Project', 'A test');
    expect(project.id).toBeDefined();
    expect(project.name).toBe('Test Project');
    expect(appState.getProject(project.id)).toEqual(project);
  });

  test('should delete projects and their cards', () => {
    const project = appState.addProject('Temp');
    appState.addCard({
      title: 'Card 1',
      description: '',
      status: 'todo',
      projectId: project.id,
      dependencies: [],
      tags: [],
      priority: 0,
    });

    appState.deleteProject(project.id);
    expect(appState.getProject(project.id)).toBeUndefined();
    expect(appState.getCardsByProject(project.id)).toHaveLength(0);
  });

  // --- Cards ---

  test('should create cards and link to project', () => {
    const project = appState.addProject('Proj');
    const card = appState.addCard({
      title: 'Card',
      description: 'Desc',
      status: 'idea',
      projectId: project.id,
      dependencies: [],
      tags: [],
      priority: 1,
    });

    expect(card.id).toBeDefined();
    expect(appState.getCardsByProject(project.id)).toHaveLength(1);

    const updatedProject = appState.getProject(project.id);
    expect(updatedProject?.cards).toContain(card.id);
  });

  test('should move cards between statuses', () => {
    const project = appState.addProject('Proj');
    const card = appState.addCard({
      title: 'Card',
      description: '',
      status: 'idea',
      projectId: project.id,
      dependencies: [],
      tags: [],
      priority: 0,
    });

    appState.moveCard(card.id, 'in-progress');
    expect(appState.getCard(card.id)?.status).toBe('in-progress');
  });

  // --- Reset ---

  test('should reset to defaults', () => {
    appState.addProject('Test');
    appState.addMessage({ role: 'user', content: 'test' });
    appState.set('volume', 0.3);

    appState.reset();

    expect(appState.get('projects')).toEqual([]);
    expect(appState.get('messages')).toEqual([]);
    expect(appState.get('volume')).toBe(0.8);
  });

  // --- Snapshot ---

  test('should return deep-cloned snapshot', () => {
    appState.addProject('Test');
    const snapshot = appState.getSnapshot();
    snapshot.projects.push({} as any);
    expect(appState.get('projects')).toHaveLength(1);
  });
});
