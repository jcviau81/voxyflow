import { Sprint, Card, SprintStatus } from '../../types';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';

export class SprintPlanner {
  private container: HTMLElement;
  private projectId: string;
  private sprints: Sprint[] = [];
  private cards: Card[] = [];
  private selectedSprintId: string | null = null;
  private showCreateForm = false;

  // DOM refs
  private sidebar: HTMLElement | null = null;
  private boardArea: HTMLElement | null = null;
  private sprintListEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'sprint-view' });
    this.projectId = appState.get('currentProjectId') || '';
    this.render();
    this.loadData();
    this.parentElement.appendChild(this.container);
  }

  private async loadData(): Promise<void> {
    if (!this.projectId) return;
    const [sprints, cards] = await Promise.all([
      apiClient.listSprints(this.projectId),
      apiClient.fetchCards(this.projectId),
    ]);
    this.sprints = sprints;
    this.cards = (cards as Card[]) || [];
    // Auto-select active sprint or first sprint
    const active = sprints.find((s) => s.status === 'active');
    if (active) this.selectedSprintId = active.id;
    else if (sprints.length > 0) this.selectedSprintId = sprints[0].id;
    this.renderSidebar();
    this.renderBoard();
  }

  private render(): void {
    this.container.innerHTML = '';

    // (page title handled by ProjectHeader)
    const header = createElement('div', { className: 'sprint-header' });
    const newBtn = createElement('button', { className: 'btn-primary sprint-new-btn' }, '+ New Sprint');
    newBtn.addEventListener('click', () => this.toggleCreateForm());
    header.appendChild(newBtn);

    const body = createElement('div', { className: 'sprint-body' });

    this.sidebar = createElement('div', { className: 'sprint-sidebar' });
    this.sprintListEl = createElement('div', { className: 'sprint-list' });
    this.sidebar.appendChild(this.sprintListEl);

    this.boardArea = createElement('div', { className: 'sprint-board' });

    body.appendChild(this.sidebar);
    body.appendChild(this.boardArea);

    this.container.appendChild(header);
    this.container.appendChild(body);
  }

  private renderSidebar(): void {
    if (!this.sprintListEl) return;
    this.sprintListEl.innerHTML = '';

    if (this.showCreateForm) {
      this.sprintListEl.appendChild(this.buildCreateForm());
    }

    if (this.sprints.length === 0) {
      const empty = createElement('div', { className: 'sprint-empty' }, 'No sprints yet. Create one to get started.');
      this.sprintListEl.appendChild(empty);
      return;
    }

    for (const sprint of this.sprints) {
      const item = this.buildSprintItem(sprint);
      this.sprintListEl.appendChild(item);
    }
  }

  private buildSprintItem(sprint: Sprint): HTMLElement {
    const isActive = sprint.status === 'active';
    const isSelected = this.selectedSprintId === sprint.id;
    const classes = ['sprint-item', sprint.status, isSelected ? 'selected' : ''].filter(Boolean).join(' ');
    const item = createElement('div', { className: classes });

    const itemHeader = createElement('div', { className: 'sprint-item-header' });
    const nameBadge = createElement('div', { className: 'sprint-item-name' });
    if (isActive) {
      const badge = createElement('span', { className: 'sprint-active-badge' }, '● ACTIVE');
      nameBadge.appendChild(badge);
    }
    nameBadge.appendChild(document.createTextNode(sprint.name));
    itemHeader.appendChild(nameBadge);

    const statusTag = createElement('span', { className: `sprint-status-tag ${sprint.status}` }, sprint.status);
    itemHeader.appendChild(statusTag);

    item.appendChild(itemHeader);

    if (sprint.goal) {
      const goal = createElement('div', { className: 'sprint-item-goal' }, sprint.goal);
      item.appendChild(goal);
    }

    const dateRange = createElement('div', { className: 'sprint-date-range' });
    dateRange.textContent = `${this.formatDate(sprint.startDate)} → ${this.formatDate(sprint.endDate)}`;
    item.appendChild(dateRange);

    const footer = createElement('div', { className: 'sprint-item-footer' });
    const cardCount = createElement('span', { className: 'sprint-card-count' }, `${sprint.cardCount} card${sprint.cardCount !== 1 ? 's' : ''}`);
    footer.appendChild(cardCount);

    // Action buttons
    const actions = createElement('div', { className: 'sprint-item-actions' });
    if (sprint.status === 'planning') {
      const startBtn = createElement('button', { className: 'sprint-btn-sm sprint-btn-start', title: 'Start sprint' }, '▶ Start');
      startBtn.addEventListener('click', (e) => { e.stopPropagation(); this.handleStartSprint(sprint.id); });
      actions.appendChild(startBtn);
    }
    if (sprint.status === 'active') {
      const completeBtn = createElement('button', { className: 'sprint-btn-sm sprint-btn-complete', title: 'Complete sprint' }, '✓ Complete');
      completeBtn.addEventListener('click', (e) => { e.stopPropagation(); this.handleCompleteSprint(sprint.id); });
      actions.appendChild(completeBtn);
    }
    const deleteBtn = createElement('button', { className: 'sprint-btn-sm sprint-btn-delete', title: 'Delete sprint' }, '🗑');
    deleteBtn.addEventListener('click', (e) => { e.stopPropagation(); this.handleDeleteSprint(sprint.id); });
    actions.appendChild(deleteBtn);
    footer.appendChild(actions);

    item.appendChild(footer);

    item.addEventListener('click', () => {
      this.selectedSprintId = sprint.id;
      this.renderSidebar();
      this.renderBoard();
    });

    return item;
  }

  private buildCreateForm(): HTMLElement {
    const form = createElement('div', { className: 'sprint-create-form' });
    const title = createElement('h4', {}, 'New Sprint');

    const nameInput = createElement('input', {
      type: 'text',
      placeholder: 'Sprint name (e.g. Sprint 1)',
      className: 'sprint-input',
    }) as HTMLInputElement;

    const goalInput = createElement('textarea', {
      placeholder: 'Sprint goal (optional)',
      className: 'sprint-textarea',
      rows: '2',
    }) as HTMLTextAreaElement;

    const dateRow = createElement('div', { className: 'sprint-date-row' });
    const startLabel = createElement('label', {}, 'Start');
    const startInput = createElement('input', { type: 'date', className: 'sprint-input sprint-date-input' }) as HTMLInputElement;
    const endLabel = createElement('label', {}, 'End');
    const endInput = createElement('input', { type: 'date', className: 'sprint-input sprint-date-input' }) as HTMLInputElement;

    // Default to today + 2 weeks
    const today = new Date();
    const twoWeeks = new Date(today.getTime() + 14 * 24 * 60 * 60 * 1000);
    startInput.value = this.toDateInputValue(today);
    endInput.value = this.toDateInputValue(twoWeeks);

    dateRow.appendChild(startLabel);
    dateRow.appendChild(startInput);
    dateRow.appendChild(endLabel);
    dateRow.appendChild(endInput);

    const btnRow = createElement('div', { className: 'sprint-form-btns' });
    const createBtn = createElement('button', { className: 'btn-primary' }, 'Create');
    const cancelBtn = createElement('button', { className: 'btn-secondary' }, 'Cancel');

    createBtn.addEventListener('click', async () => {
      const name = nameInput.value.trim();
      if (!name) { nameInput.focus(); return; }
      const result = await apiClient.createSprint(this.projectId, {
        name,
        goal: goalInput.value.trim() || undefined,
        start_date: new Date(startInput.value).toISOString(),
        end_date: new Date(endInput.value).toISOString(),
      });
      if (result) {
        this.showCreateForm = false;
        await this.loadData();
        this.selectedSprintId = result.id;
        this.renderSidebar();
        this.renderBoard();
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `✅ Sprint "${result.name}" created`, type: 'success', duration: 3000 });
      }
    });

    cancelBtn.addEventListener('click', () => {
      this.showCreateForm = false;
      this.renderSidebar();
    });

    btnRow.appendChild(createBtn);
    btnRow.appendChild(cancelBtn);

    form.appendChild(title);
    form.appendChild(nameInput);
    form.appendChild(goalInput);
    form.appendChild(dateRow);
    form.appendChild(btnRow);

    return form;
  }

  private renderBoard(): void {
    if (!this.boardArea) return;
    this.boardArea.innerHTML = '';

    const selectedSprint = this.sprints.find((s) => s.id === this.selectedSprintId);
    const sprintCards = selectedSprint
      ? this.cards.filter((c) => c.sprintId === this.selectedSprintId)
      : [];
    const backlogCards = this.cards.filter((c) => !c.sprintId);

    if (this.sprints.length === 0) {
      const msg = createElement('div', { className: 'sprint-board-empty' }, '👈 Create a sprint to get started');
      this.boardArea.appendChild(msg);
      return;
    }

    // Sprint board section
    if (selectedSprint) {
      const sprintSection = createElement('div', { className: 'sprint-board-section' });
      const sprintTitle = createElement('div', { className: 'sprint-board-title' });
      sprintTitle.innerHTML = `<strong>${selectedSprint.name}</strong>`;
      if (selectedSprint.goal) {
        sprintTitle.innerHTML += ` <span class="sprint-goal-text">— ${selectedSprint.goal}</span>`;
      }
      sprintSection.appendChild(sprintTitle);

      if (sprintCards.length === 0) {
        const empty = createElement('div', { className: 'sprint-cards-empty' }, 'No cards in this sprint yet. Add from backlog below.');
        sprintSection.appendChild(empty);
      } else {
        const columns = this.buildKanbanColumns(sprintCards, selectedSprint);
        sprintSection.appendChild(columns);
      }

      this.boardArea.appendChild(sprintSection);
    }

    // Backlog section
    const backlogSection = createElement('div', { className: 'sprint-backlog' });
    const backlogTitle = createElement('div', { className: 'sprint-backlog-title' });
    backlogTitle.innerHTML = `<strong>📋 Backlog</strong> <span class="sprint-backlog-count">${backlogCards.length} cards</span>`;
    backlogSection.appendChild(backlogTitle);

    if (backlogCards.length === 0) {
      const empty = createElement('div', { className: 'sprint-cards-empty' }, 'All cards are assigned to sprints.');
      backlogSection.appendChild(empty);
    } else {
      const list = createElement('div', { className: 'sprint-backlog-list' });
      for (const card of backlogCards) {
        list.appendChild(this.buildBacklogCard(card));
      }
      backlogSection.appendChild(list);
    }

    this.boardArea.appendChild(backlogSection);
  }

  private buildKanbanColumns(cards: Card[], sprint: Sprint): HTMLElement {
    const columns = createElement('div', { className: 'sprint-kanban-columns' });
    const statusOrder: Array<{ key: string; label: string }> = [
      { key: 'idea', label: '💡 Idea' },
      { key: 'todo', label: '📋 Todo' },
      { key: 'in-progress', label: '🔨 In Progress' },
      { key: 'done', label: '✅ Done' },
    ];

    for (const { key, label } of statusOrder) {
      const colCards = cards.filter((c) => c.status === key);
      const col = createElement('div', { className: `sprint-kanban-col sprint-col-${key}` });
      const colHeader = createElement('div', { className: 'sprint-col-header' });
      colHeader.innerHTML = `${label} <span class="sprint-col-count">${colCards.length}</span>`;
      col.appendChild(colHeader);

      const cardList = createElement('div', { className: 'sprint-col-cards' });
      for (const card of colCards) {
        cardList.appendChild(this.buildSprintCard(card, sprint));
      }
      col.appendChild(cardList);
      columns.appendChild(col);
    }

    return columns;
  }

  private buildSprintCard(card: Card, sprint: Sprint): HTMLElement {
    const el = createElement('div', { className: 'sprint-card' });
    const cardTitle = createElement('div', { className: 'sprint-card-title' }, card.title);
    el.appendChild(cardTitle);

    if (card.description) {
      const desc = createElement('div', { className: 'sprint-card-desc' }, card.description.slice(0, 80) + (card.description.length > 80 ? '…' : ''));
      el.appendChild(desc);
    }

    const footer = createElement('div', { className: 'sprint-card-footer' });
    if (card.agentType) {
      const agent = createElement('span', { className: 'sprint-card-agent' }, card.agentType);
      footer.appendChild(agent);
    }

    if (sprint.status !== 'completed') {
      const removeBtn = createElement('button', { className: 'sprint-card-remove', title: 'Remove from sprint' }, '×');
      removeBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await apiClient.patchCard(card.id, { sprint_id: null });
        card.sprintId = null;
        // Update local card count
        const s = this.sprints.find((sp) => sp.id === sprint.id);
        if (s) s.cardCount = Math.max(0, s.cardCount - 1);
        this.renderSidebar();
        this.renderBoard();
      });
      footer.appendChild(removeBtn);
    }

    el.appendChild(footer);
    return el;
  }

  private buildBacklogCard(card: Card): HTMLElement {
    const el = createElement('div', { className: 'sprint-backlog-card' });
    const cardTitle = createElement('div', { className: 'sprint-backlog-card-title' }, card.title);
    el.appendChild(cardTitle);

    const meta = createElement('div', { className: 'sprint-backlog-card-meta' });
    const statusBadge = createElement('span', { className: `sprint-status-badge sprint-status-${card.status}` }, card.status);
    meta.appendChild(statusBadge);

    if (this.selectedSprintId) {
      const selectedSprint = this.sprints.find((s) => s.id === this.selectedSprintId);
      if (selectedSprint && selectedSprint.status !== 'completed') {
        const addBtn = createElement('button', { className: 'sprint-add-btn', title: `Add to ${selectedSprint.name}` }, `+ Add to Sprint`);
        addBtn.addEventListener('click', async () => {
          await apiClient.patchCard(card.id, { sprint_id: this.selectedSprintId });
          card.sprintId = this.selectedSprintId!;
          const s = this.sprints.find((sp) => sp.id === this.selectedSprintId);
          if (s) s.cardCount += 1;
          this.renderSidebar();
          this.renderBoard();
        });
        meta.appendChild(addBtn);
      }
    }

    el.appendChild(meta);
    return el;
  }

  private async handleStartSprint(sprintId: string): Promise<void> {
    const result = await apiClient.startSprint(this.projectId, sprintId);
    if (result) {
      await this.loadData();
      this.selectedSprintId = sprintId;
      this.renderSidebar();
      this.renderBoard();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `🏃 Sprint started!`, type: 'success', duration: 3000 });
    }
  }

  private async handleCompleteSprint(sprintId: string): Promise<void> {
    const result = await apiClient.completeSprint(this.projectId, sprintId);
    if (result) {
      await this.loadData();
      this.renderSidebar();
      this.renderBoard();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `✅ Sprint completed!`, type: 'success', duration: 3000 });
    }
  }

  private async handleDeleteSprint(sprintId: string): Promise<void> {
    const sprint = this.sprints.find((s) => s.id === sprintId);
    if (!sprint) return;
    if (!confirm(`Delete sprint "${sprint.name}"? Cards will return to backlog.`)) return;
    const ok = await apiClient.deleteSprint(this.projectId, sprintId);
    if (ok) {
      if (this.selectedSprintId === sprintId) this.selectedSprintId = null;
      await this.loadData();
      this.renderSidebar();
      this.renderBoard();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `🗑️ Sprint deleted`, type: 'info', duration: 2500 });
    }
  }

  private toggleCreateForm(): void {
    this.showCreateForm = !this.showCreateForm;
    this.renderSidebar();
  }

  private formatDate(iso: string): string {
    if (!iso) return '?';
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return iso.slice(0, 10);
    }
  }

  private toDateInputValue(date: Date): string {
    return date.toISOString().slice(0, 10);
  }

  destroy(): void {
    this.container.remove();
  }
}
