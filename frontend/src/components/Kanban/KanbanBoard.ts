import { Card, CardStatus } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS, AGENT_TYPE_EMOJI, AGENT_TYPE_INFO } from '../../utils/constants';
import { createElement, debounce } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardStore } from '../../state/ReactiveCardStore';
import { cardService } from '../../services/CardService';
import { apiClient } from '../../services/ApiClient';
import { KanbanColumn } from './KanbanColumn';
import { ActivityFeed } from './ActivityFeed';
import { BulkActionToolbar } from './BulkActionToolbar';

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
  private depGraphOverlay: HTMLElement | null = null;

  // Filter state (ephemeral — not in AppState)
  private searchQuery: string = '';
  private priorityFilter: number | null = null;
  private agentFilter: string | null = null;
  private tagFilter: string | null = null;
  private sortMode: 'default' | 'votes' = 'default';

  // Multi-select state
  private selectModeActive: boolean = false;
  private selectedCardIds: Set<string> = new Set();
  private bulkToolbar: BulkActionToolbar | null = null;
  private selectToggleBtn: HTMLElement | null = null;

  // Board execution state
  private executionActive: boolean = false;
  private executionId: string | null = null;
  private executionTotal: number = 0;
  private executionCurrentIndex: number = 0;
  private executionCurrentCardId: string | null = null;
  private executionProgressEl: HTMLElement | null = null;
  private executeBtn: HTMLElement | null = null;

  // UI refs
  private matchCountEl: HTMLElement | null = null;
  private searchInput: HTMLInputElement | null = null;
  private clearBtn: HTMLElement | null = null;
  private tagFilterGroup: HTMLElement | null = null;

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
    this.tagFilter = null;
    this.sortMode = 'default';

    // Header row (action buttons — project name + view tabs are in shared ProjectHeader)
    const header = createElement('div', { className: 'kanban-header' });
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    // Project name now shown in ProjectHeader

    // Search bar
    const searchBar = createElement('div', { className: 'kanban-search-bar' });

    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.className = 'kanban-search-input';
    this.searchInput.placeholder = 'Search cards...';
    const debouncedFilter = debounce(() => {
      this.applyFilters();
    }, 200);
    this.searchInput.addEventListener('input', () => {
      this.searchQuery = this.searchInput!.value;
      this.updateClearBtn();
      debouncedFilter();
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
    const exportBtn = createElement('button', { className: 'kanban-action-btn', title: 'Export project as JSON' }, '📤 Export');
    exportBtn.addEventListener('click', () => this.handleExport());

    // Import button + hidden file input
    const importBtn = createElement('button', { className: 'kanban-action-btn', title: 'Import project from JSON' }, '📥 Import');
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

    // Dependency graph button (lives in filter bar)
    const depGraphBtn = createElement('button', { className: 'kanban-action-btn', title: 'View dependency map' }, '🔗 Dependencies');
    depGraphBtn.addEventListener('click', () => this.showDepGraph());

    // Execute Board button
    this.executeBtn = createElement('button', {
      className: 'kanban-action-btn kanban-execute-btn',
      title: 'Execute all todo/in-progress cards sequentially',
    }, '▶ Execute Board');
    this.executeBtn.addEventListener('click', () => {
      if (this.executionActive && this.executionId) {
        apiClient.cancelBoardExecution(this.executionId);
      } else {
        this.handleExecuteBoard();
      }
    });

    // Multi-select toggle button
    this.selectToggleBtn = createElement('button', {
      className: 'kanban-action-btn kanban-select-toggle',
      title: 'Toggle multi-select mode',
    }, '☑ Select');
    this.selectToggleBtn.addEventListener('click', () => this.toggleSelectMode());

    // Spacer pushes action buttons to the right
    const headerSpacer = createElement('div', { className: 'kanban-header-spacer' });

    // Row 1: spacer | Execute | Select | Export | Import | New Card
    // (view toggle + project name handled by ProjectHeader)
    header.appendChild(headerSpacer);
    header.appendChild(this.executeBtn);
    header.appendChild(this.selectToggleBtn);
    header.appendChild(exportBtn);
    header.appendChild(importBtn);
    header.appendChild(importInput);
    header.appendChild(addBtn);
    this.container.appendChild(header);

    // Execution progress bar (hidden by default)
    this.executionProgressEl = createElement('div', { className: 'kanban-execution-progress' });
    this.executionProgressEl.style.display = 'none';
    this.container.appendChild(this.executionProgressEl);

    // Row 2: filter bar — search | priority | agent | sort | tags | deps
    const filterRow = createElement('div', { className: 'kanban-filter-bar' });

    // Search bar lives here now
    filterRow.appendChild(searchBar);

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

    // Sort chips
    const sortGroup = createElement('div', { className: 'kanban-filter-chips' });
    const sortLabel = createElement('span', { className: 'kanban-filter-label' }, 'Sort:');
    sortGroup.appendChild(sortLabel);
    const sortOptions: Array<{ label: string; value: 'default' | 'votes' }> = [
      { label: 'Default', value: 'default' },
      { label: '▲ Votes', value: 'votes' },
    ];
    sortOptions.forEach((so) => {
      const chip = createElement('button', {
        className: 'kanban-filter-chip' + (this.sortMode === so.value ? ' active' : ''),
      }, so.label);
      chip.addEventListener('click', () => {
        this.sortMode = so.value;
        sortGroup.querySelectorAll('.kanban-filter-chip').forEach((c, i) => {
          c.classList.toggle('active', sortOptions[i].value === this.sortMode);
        });
        this.refreshCards();
      });
      sortGroup.appendChild(chip);
    });

    // Tag filter chips (built after cards are loaded — refreshed in refreshCards)
    this.tagFilterGroup = createElement('div', { className: 'kanban-filter-chips kanban-tag-filter-group' });
    const tagFilterLabel = createElement('span', { className: 'kanban-filter-label' }, '🏷️ Tags:');
    this.tagFilterGroup.appendChild(tagFilterLabel);
    // Placeholder — will be populated in refreshTagFilterChips()

    filterRow.appendChild(priorityGroup);
    filterRow.appendChild(agentGroup);
    filterRow.appendChild(sortGroup);
    filterRow.appendChild(this.tagFilterGroup);
    filterRow.appendChild(depGraphBtn);
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

    // Bulk Action Toolbar (floating bottom bar)
    if (this.bulkToolbar) {
      this.bulkToolbar.destroy();
      this.bulkToolbar = null;
    }
    this.bulkToolbar = new BulkActionToolbar(this.container, {
      onClearSelection: () => this.clearSelection(),
    });

    this.parentElement.appendChild(this.container);

    // Reset multi-select state on project change
    this.selectModeActive = false;
    this.selectedCardIds.clear();

    // Fetch cards from backend into appState, then refresh
    if (projectId) {
      this.fetchAndSyncCards(projectId);
    } else {
      this.refreshCards();
    }
  }

  private async fetchAndSyncCards(projectId: string): Promise<void> {
    try {
      const { apiClient } = await import('../../services/ApiClient');
      const freshCards = await apiClient.fetchCards(projectId) as Card[];
      // Replace cards for this project in the reactive store
      cardStore.setForProject(projectId, freshCards);
    } catch (e) {
      console.error('[KanbanBoard] fetchAndSyncCards error:', e);
    }
    this.refreshCards();
  }

  private setupListeners(): void {
    // Reactive card store subscription — replaces CARD_CREATED/UPDATED/DELETED/MOVED listeners
    this.unsubscribers.push(
      cardStore.subscribe(() => this.refreshCards())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.render())
    );
    // Board execution events
    this.unsubscribers.push(
      eventBus.on(EVENTS.BOARD_EXECUTE_CARD_START, (data: unknown) => {
        const { cardId, cardTitle, index, total, executionId } = data as {
          cardId: string; cardTitle: string; index: number; total: number; executionId: string;
        };
        this.executionActive = true;
        this.executionId = executionId;
        this.executionTotal = total;
        this.executionCurrentIndex = index;
        this.executionCurrentCardId = cardId;
        this.updateExecutionProgressUI(index, total, cardTitle);
        this.highlightExecutingCard(cardId);
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.BOARD_EXECUTE_CARD_DONE, (data: unknown) => {
        const { cardId } = data as { cardId: string };
        this.clearExecutingCardHighlight(cardId);
        // Cards will be refreshed via CARD_UPDATED event
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.BOARD_EXECUTE_COMPLETE, () => {
        this.resetExecutionState();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.BOARD_EXECUTE_CANCELLED, () => {
        this.resetExecutionState();
      })
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.BOARD_EXECUTE_ERROR, () => {
        this.resetExecutionState();
      })
    );

    // Tag click on a card → activate that tag filter
    this.unsubscribers.push(
      eventBus.on(EVENTS.KANBAN_TAG_FILTER, (data: unknown) => {
        const { tag } = data as { tag: string };
        // Toggle: clicking same tag deselects it
        this.tagFilter = this.tagFilter === tag ? null : tag;
        this.refreshTagFilterChips();
        this.applyFilters();
      })
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
      const columnVisible = column.applyFilter(this.searchQuery, this.priorityFilter, this.agentFilter, this.tagFilter);
      visibleCount += columnVisible;
      column.getCardComponents().forEach(() => totalCount++);
    });

    if (this.matchCountEl) {
      const isFiltered = this.searchQuery || this.priorityFilter !== null || this.agentFilter !== null || this.tagFilter !== null;
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
      this.refreshTagFilterChips();
      this.applyFilters();
      return;
    }

    for (const status of CARD_STATUSES) {
      const cards = appState.getCardsByStatus(projectId, status);
      const column = this.columns.get(status);
      if (column) {
        column.setCards(cards, this.sortMode, this.selectModeActive, (id, selected) => {
          this.onCardSelectChange(id, selected);
        });
      }
    }

    // Rebuild tag filter chips with current project tags
    this.refreshTagFilterChips();

    // Re-apply current filters after refresh
    this.applyFilters();

    // If in select mode, refresh toolbar count (selection may have changed after cards refreshed)
    if (this.selectModeActive) {
      // Re-apply selection state (cards are re-rendered so we need to restore)
      this.restoreSelectionOnCards();
      this.bulkToolbar?.setSelection(this.selectedCardIds);
    }
  }

  private onCardSelectChange(cardId: string, selected: boolean): void {
    if (selected) {
      this.selectedCardIds.add(cardId);
    } else {
      this.selectedCardIds.delete(cardId);
    }
    this.bulkToolbar?.setSelection(this.selectedCardIds);
  }

  private restoreSelectionOnCards(): void {
    this.columns.forEach((col) => {
      col.getCardComponents().forEach((card, id) => {
        card.setSelected(this.selectedCardIds.has(id));
      });
    });
  }

  private toggleSelectMode(): void {
    this.selectModeActive = !this.selectModeActive;

    // Update button state
    if (this.selectToggleBtn) {
      this.selectToggleBtn.classList.toggle('kanban-select-toggle--active', this.selectModeActive);
      this.selectToggleBtn.textContent = this.selectModeActive ? '☑ Select (ON)' : '☑ Select';
    }

    if (!this.selectModeActive) {
      // Exiting select mode: clear selection
      this.clearSelection();
    } else {
      // Entering select mode: propagate to all cards
      this.columns.forEach((col) => {
        col.setSelectMode(true, (id, selected) => this.onCardSelectChange(id, selected));
      });
    }
  }

  private clearSelection(): void {
    this.selectedCardIds.clear();
    this.columns.forEach((col) => col.clearSelection());
    this.bulkToolbar?.setSelection(this.selectedCardIds);

    // If we're exiting select mode from a clear
    if (this.selectModeActive) {
      // Don't toggle mode off, just clear
    }
  }

  private refreshTagFilterChips(): void {
    if (!this.tagFilterGroup) return;

    const projectId = appState.get('currentProjectId');
    // Collect all unique tags across the project
    const allTags = new Set<string>();
    if (projectId) {
      appState.getCardsByProject(projectId).forEach((card) => {
        card.tags.forEach((t) => { if (t) allTags.add(t); });
      });
    }

    // Remove all chips (keep the label as first child)
    const label = this.tagFilterGroup.firstChild;
    this.tagFilterGroup.innerHTML = '';
    if (label) this.tagFilterGroup.appendChild(label);

    if (allTags.size === 0) {
      this.tagFilterGroup.style.display = 'none';
      return;
    }
    this.tagFilterGroup.style.display = '';

    allTags.forEach((tag) => {
      const isActive = this.tagFilter === tag;
      const chip = createElement('button', {
        className: 'tag-filter-chip' + (isActive ? ' active' : ''),
        title: `Filter by "${tag}"`,
      }, tag);
      chip.addEventListener('click', () => {
        this.tagFilter = this.tagFilter === tag ? null : tag;
        this.refreshTagFilterChips();
        this.applyFilters();
      });
      this.tagFilterGroup!.appendChild(chip);
    });
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

  private showDepGraph(): void {
    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Select a project first', type: 'warning' });
      return;
    }

    // Remove existing overlay if any
    if (this.depGraphOverlay) {
      this.depGraphOverlay.remove();
      this.depGraphOverlay = null;
    }

    const allCards = appState.getCardsByProject(projectId);
    const cardMap = new Map(allCards.map((c) => [c.id, c]));

    // Cards with dependencies
    const blockedCards = allCards.filter((c) =>
      c.dependencies.length > 0 && c.dependencies.some((d) => {
        const dep = cardMap.get(d);
        return dep && dep.status !== 'done';
      })
    );

    const readyCards = allCards.filter((c) => {
      if (c.status === 'done') return false;
      if (c.dependencies.length === 0) return true;
      return c.dependencies.every((d) => {
        const dep = cardMap.get(d);
        return dep && dep.status === 'done';
      });
    });

    const overlay = createElement('div', { className: 'dependency-graph' });

    const panel = createElement('div', { className: 'dependency-graph-panel' });

    const graphHeader = createElement('div', { className: 'dependency-graph-header' });
    const graphTitle = createElement('h3', { className: 'dependency-graph-title' }, '🔗 Dependency Map');
    const closeBtn = createElement('button', { className: 'dependency-graph-close' }, '✕');
    closeBtn.addEventListener('click', () => {
      overlay.remove();
      this.depGraphOverlay = null;
    });
    graphHeader.appendChild(graphTitle);
    graphHeader.appendChild(closeBtn);
    panel.appendChild(graphHeader);

    // Blocked section
    const blockedSection = createElement('div', { className: 'dep-graph-section' });
    blockedSection.appendChild(createElement('h4', { className: 'dep-graph-section-title blocked' }, `🚫 Cards with blocked dependencies (${blockedCards.length})`));
    if (blockedCards.length === 0) {
      blockedSection.appendChild(createElement('p', { className: 'dep-graph-empty' }, 'No blocked cards — great!'));
    } else {
      blockedCards.forEach((card) => {
        const item = createElement('div', { className: 'dep-graph-item' });
        const cardTitle = createElement('span', { className: 'dep-graph-card-title' }, `📋 ${card.title}`);
        item.appendChild(cardTitle);
        const blockersList = createElement('ul', { className: 'dep-graph-blockers' });
        card.dependencies.forEach((depId) => {
          const dep = cardMap.get(depId);
          if (!dep || dep.status === 'done') return;
          const li = createElement('li', { className: 'dep-graph-blocker' }, `⏳ ${dep.title}`);
          blockersList.appendChild(li);
        });
        item.appendChild(blockersList);
        blockedSection.appendChild(item);
      });
    }
    panel.appendChild(blockedSection);

    // Ready section
    const readySection = createElement('div', { className: 'dep-graph-section' });
    readySection.appendChild(createElement('h4', { className: 'dep-graph-section-title ready' }, `✅ Ready to work on (${readyCards.length})`));
    if (readyCards.length === 0) {
      readySection.appendChild(createElement('p', { className: 'dep-graph-empty' }, 'No ready cards.'));
    } else {
      readyCards.forEach((card) => {
        const item = createElement('div', { className: 'dep-graph-item ready' });
        const noDeps = card.dependencies.length === 0 ? ' (no deps)' : ' (all deps done)';
        item.appendChild(createElement('span', {}, `📋 ${card.title}${noDeps}`));
        readySection.appendChild(item);
      });
    }
    panel.appendChild(readySection);

    overlay.appendChild(panel);

    // Close on backdrop click
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) {
        overlay.remove();
        this.depGraphOverlay = null;
      }
    });

    this.depGraphOverlay = overlay;
    this.container.appendChild(overlay);
  }

  // ── Board Execution ──────────────────────────────────────────────────────

  private async handleExecuteBoard(): Promise<void> {
    if (this.executionActive) return;

    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Select a project first', type: 'warning' });
      return;
    }

    // Get execution plan to show card count
    const plan = await apiClient.executeBoardPlan(projectId);
    if (!plan || plan.total === 0) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'No todo/in-progress cards to execute', type: 'warning' });
      return;
    }

    if (!confirm(`Execute ${plan.total} cards sequentially?\n\nCards will be processed in order and moved to Done when complete.`)) {
      return;
    }

    // Use ChatService's active session ID for context
    const { chatService } = await import('../../services/ChatService');
    const sessionId = chatService.activeSessionId || 'board-exec-' + Date.now();

    this.executionActive = true;
    this.executionId = plan.executionId;
    if (this.executeBtn) {
      this.executeBtn.textContent = '⏹ Stop';
      this.executeBtn.classList.add('kanban-execute-btn--active');
    }

    apiClient.startBoardExecution(projectId, sessionId);
  }

  private updateExecutionProgressUI(index: number, total: number, cardTitle: string): void {
    if (!this.executionProgressEl) return;

    const pct = ((index + 1) / total) * 100;
    this.executionProgressEl.style.display = '';
    this.executionProgressEl.innerHTML = `
      <div class="kanban-execution-progress__info">
        <span>Executing card ${index + 1}/${total}: ${this.escapeHtml(cardTitle)}</span>
        <button class="kanban-execution-progress__stop" title="Cancel execution">⏹ Stop</button>
      </div>
      <div class="kanban-execution-progress__bar">
        <div class="kanban-execution-progress__fill" style="width: ${pct}%"></div>
      </div>
    `;

    const stopBtn = this.executionProgressEl.querySelector('.kanban-execution-progress__stop');
    stopBtn?.addEventListener('click', () => {
      if (this.executionId) {
        apiClient.cancelBoardExecution(this.executionId);
      }
    });
  }

  private escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  private highlightExecutingCard(cardId: string): void {
    // Clear any previous highlight
    this.container.querySelectorAll('.kanban-card--executing').forEach((el) => {
      el.classList.remove('kanban-card--executing');
    });
    // Add highlight to current card
    const cardEl = this.container.querySelector(`[data-card-id="${cardId}"]`);
    if (cardEl) {
      cardEl.classList.add('kanban-card--executing');
      cardEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  private clearExecutingCardHighlight(cardId: string): void {
    const cardEl = this.container.querySelector(`[data-card-id="${cardId}"]`);
    if (cardEl) {
      cardEl.classList.remove('kanban-card--executing');
    }
  }

  private resetExecutionState(): void {
    this.executionActive = false;
    this.executionId = null;
    this.executionTotal = 0;
    this.executionCurrentIndex = 0;
    this.executionCurrentCardId = null;

    if (this.executionProgressEl) {
      this.executionProgressEl.style.display = 'none';
      this.executionProgressEl.innerHTML = '';
    }
    if (this.executeBtn) {
      this.executeBtn.textContent = '▶ Execute Board';
      this.executeBtn.classList.remove('kanban-execute-btn--active');
    }

    // Clear any lingering card highlights
    this.container.querySelectorAll('.kanban-card--executing').forEach((el) => {
      el.classList.remove('kanban-card--executing');
    });

    // Refresh cards to reflect status changes
    const projectId = appState.get('currentProjectId');
    if (projectId) {
      this.fetchAndSyncCards(projectId);
    }
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
    this.depGraphOverlay?.remove();
    this.depGraphOverlay = null;
    this.executionProgressEl = null;
    this.executeBtn = null;
    this.bulkToolbar?.destroy();
    this.bulkToolbar = null;
    this.container.remove();
  }
}
