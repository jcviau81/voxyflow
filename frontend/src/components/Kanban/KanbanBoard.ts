import { Card, CardStatus } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS, AGENT_TYPE_EMOJI, AGENT_TYPE_INFO } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';
import { apiClient } from '../../services/ApiClient';
import { KanbanColumn } from './KanbanColumn';
import { ActivityFeed } from './ActivityFeed';

// Priority filter options
const PRIORITY_FILTERS = [
  { label: 'All', value: null },
  { label: '🔴 Critical', value: 3 },
  { label: '🟠 High', value: 2 },
  { label: '🟡 Medium', value: 1 },
  { label: '🟢 Low', value: 0 },
];

// Agent filter options
const AGENT_FILTERS = [
  { label: 'All', value: null },
  ...Object.entries(AGENT_TYPE_INFO).map(([key, info]) => ({
    label: `${info.emoji} ${info.name}`,
    value: key,
  })),
];

export class KanbanBoard {
  private container: HTMLElement;
  private columns: Map<string, KanbanColumn> = new Map();
  private activityFeed: ActivityFeed | null = null;
  private unsubscribers: (() => void)[] = [];

  // Filter state (ephemeral — not in AppState)
  private searchQuery: string = '';
  private priorityFilter: number | null = null;
  private agentFilter: string | null = null;

  // UI refs
  private matchCountEl: HTMLElement | null = null;
  private searchInput: HTMLInputElement | null = null;
  private clearBtn: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'kanban-board', 'data-testid': 'kanban-board' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';
    this.columns.clear();

    // Reset filter state on render (project change)
    this.searchQuery = '';
    this.priorityFilter = null;
    this.agentFilter = null;

    // Header row (title + search + add button)
    const header = createElement('div', { className: 'kanban-header' });
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    const projectName = project?.name || 'Kanban Board';
    const title = createElement('h2', { className: 'kanban-title' }, projectName);

    // Search bar
    const searchBar = createElement('div', { className: 'kanban-search-bar' });

    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.className = 'kanban-search-input';
    this.searchInput.placeholder = 'Search cards...';
    this.searchInput.addEventListener('input', () => {
      this.searchQuery = this.searchInput!.value;
      this.updateClearBtn();
      this.applyFilters();
    });

    this.clearBtn = createElement('button', { className: 'kanban-search-clear' }, '×');
    this.clearBtn.style.display = 'none';
    this.clearBtn.addEventListener('click', () => {
      this.searchQuery = '';
      this.searchInput!.value = '';
      this.updateClearBtn();
      this.applyFilters();
    });

    this.matchCountEl = createElement('span', { className: 'kanban-match-count' });

    searchBar.appendChild(this.searchInput);
    searchBar.appendChild(this.clearBtn);
    searchBar.appendChild(this.matchCountEl);

    const addBtn = createElement('button', { className: 'kanban-add-btn' }, '+ New Card');
    addBtn.addEventListener('click', () => this.promptNewCard());

    // Export button
    const exportBtn = createElement('button', { className: 'kanban-action-btn', title: 'Export project as JSON' }, '⬇ Export');
    exportBtn.addEventListener('click', () => this.handleExport());

    // Import button + hidden file input
    const importBtn = createElement('button', { className: 'kanban-action-btn', title: 'Import project from JSON' }, '⬆ Import');
    const importInput = document.createElement('input');
    importInput.type = 'file';
    importInput.accept = '.json,application/json';
    importInput.style.display = 'none';
    importInput.addEventListener('change', () => {
      const file = importInput.files?.[0];
      if (file) this.handleImport(file);
      importInput.value = ''; // reset so same file can be re-selected
    });
    importBtn.addEventListener('click', () => importInput.click());

    header.appendChild(title);
    header.appendChild(searchBar);
    header.appendChild(exportBtn);
    header.appendChild(importBtn);
    header.appendChild(importInput);
    header.appendChild(addBtn);
    this.container.appendChild(header);

    // Filter chips row
    const filterRow = createElement('div', { className: 'kanban-filter-row' });

    // Priority chips
    const priorityGroup = createElement('div', { className: 'kanban-filter-chips' });
    const priorityLabel = createElement('span', { className: 'kanban-filter-label' }, 'Priority:');
    priorityGroup.appendChild(priorityLabel);
    PRIORITY_FILTERS.forEach((pf) => {
      const chip = createElement('button', { className: 'kanban-filter-chip' + (this.priorityFilter === pf.value ? ' active' : '') }, pf.label);
      if (this.priorityFilter === pf.value) chip.classList.add('active');
      chip.addEventListener('click', () => {
        this.priorityFilter = pf.value;
        // Update active state on all priority chips
        priorityGroup.querySelectorAll('.kanban-filter-chip').forEach((c, i) => {
          c.classList.toggle('active', PRIORITY_FILTERS[i].value === this.priorityFilter);
        });
        this.applyFilters();
      });
      priorityGroup.appendChild(chip);
    });

    // Agent chips
    const agentGroup = createElement('div', { className: 'kanban-filter-chips' });
    const agentLabel = createElement('span', { className: 'kanban-filter-label' }, 'Agent:');
    agentGroup.appendChild(agentLabel);
    AGENT_FILTERS.forEach((af) => {
      const chip = createElement('button', { className: 'kanban-filter-chip' + (this.agentFilter === af.value ? ' active' : '') }, af.label);
      if (this.agentFilter === af.value) chip.classList.add('active');
      chip.addEventListener('click', () => {
        this.agentFilter = af.value;
        agentGroup.querySelectorAll('.kanban-filter-chip').forEach((c, i) => {
          c.classList.toggle('active', AGENT_FILTERS[i].value === this.agentFilter);
        });
        this.applyFilters();
      });
      agentGroup.appendChild(chip);
    });

    filterRow.appendChild(priorityGroup);
    filterRow.appendChild(agentGroup);
    this.container.appendChild(filterRow);

    // Board with columns
    const board = createElement('div', { className: 'kanban-columns' });

    for (const status of CARD_STATUSES) {
      const column = new KanbanColumn(board, status, CARD_STATUS_LABELS[status]);
      this.columns.set(status, column);
    }

    this.container.appendChild(board);

    // Setup drag & drop on board
    this.setupDragDrop(board);

    // Activity Feed at the bottom
    if (this.activityFeed) {
      this.activityFeed.destroy();
      this.activityFeed = null;
    }
    this.activityFeed = new ActivityFeed(this.container);

    this.parentElement.appendChild(this.container);
    this.refreshCards();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_CREATED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_UPDATED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_DELETED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_MOVED, () => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.render())
    );
  }

  private updateClearBtn(): void {
    if (this.clearBtn) {
      this.clearBtn.style.display = this.searchQuery ? '' : 'none';
    }
  }

  private applyFilters(): void {
    let visibleCount = 0;
    let totalCount = 0;

    this.columns.forEach((column) => {
      const columnVisible = column.applyFilter(this.searchQuery, this.priorityFilter, this.agentFilter);
      visibleCount += columnVisible;
      column.getCardComponents().forEach(() => totalCount++);
    });

    if (this.matchCountEl) {
      const isFiltered = this.searchQuery || this.priorityFilter !== null || this.agentFilter !== null;
      this.matchCountEl.textContent = isFiltered ? `Showing ${visibleCount} of ${totalCount} cards` : '';
    }
  }

  private setupDragDrop(board: HTMLElement): void {
    board.addEventListener('dragover', (e: DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'move';
      }
    });

    board.addEventListener('drop', (e: DragEvent) => {
      e.preventDefault();
      const cardId = e.dataTransfer?.getData('text/plain');
      const target = (e.target as HTMLElement).closest('.kanban-column');
      if (cardId && target) {
        const newStatus = target.getAttribute('data-status') as CardStatus;
        if (newStatus) {
          cardService.move(cardId, newStatus);
        }
      }
    });
  }

  private refreshCards(): void {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      this.columns.forEach((col) => col.setCards([]));
      this.applyFilters();
      return;
    }

    for (const status of CARD_STATUSES) {
      const cards = appState.getCardsByStatus(projectId, status);
      const column = this.columns.get(status);
      if (column) {
        column.setCards(cards);
      }
    }

    // Re-apply current filters after refresh
    this.applyFilters();
  }

  private promptNewCard(): void {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: 'Select a project first',
        type: 'warning',
      });
      return;
    }

    eventBus.emit(EVENTS.CARD_FORM_SHOW, {
      mode: 'create',
      projectId,
    });
  }

  private async handleExport(): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Select a project first', type: 'warning' });
      return;
    }

    const project = appState.getProject(projectId);
    const data = await apiClient.exportProject(projectId);
    if (!data) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Export failed', type: 'error' });
      return;
    }

    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const filename = `${(project?.name || 'project').replace(/[^a-z0-9_-]/gi, '_')}.json`;
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);

    eventBus.emit(EVENTS.TOAST_SHOW, { message: '✅ Project exported', type: 'success' });
  }

  private async handleImport(file: File): Promise<void> {
    let data: unknown;
    try {
      const text = await file.text();
      data = JSON.parse(text);
    } catch {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Invalid JSON file', type: 'error' });
      return;
    }

    const result = await apiClient.importProject(data);
    if (!result) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Import failed — check file format', type: 'error' });
      return;
    }

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `✅ Project imported: ${result.project_title}`,
      type: 'success',
    });

    // Refresh project list so new project appears in sidebar
    eventBus.emit(EVENTS.PROJECT_CREATED, { id: result.project_id });
  }

  moveCard(cardId: string, newStatus: CardStatus): void {
    cardService.move(cardId, newStatus);
  }

  update(): void {
    this.refreshCards();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.columns.forEach((col) => col.destroy());
    this.columns.clear();
    this.activityFeed?.destroy();
    this.activityFeed = null;
    this.container.remove();
  }
}
