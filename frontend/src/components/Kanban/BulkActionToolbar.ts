import { Card, CardStatus } from '../../types';
import { createElement } from '../../utils/helpers';
import { CARD_STATUSES, CARD_STATUS_LABELS } from '../../utils/constants';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { apiClient } from '../../services/ApiClient';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';

export interface BulkActionCallbacks {
  onClearSelection: () => void;
  onSelectionChange?: () => void;
}

export class BulkActionToolbar {
  private element: HTMLElement;
  private countEl: HTMLElement;
  private actionsEl: HTMLElement;
  private selectedIds: Set<string> = new Set();
  private callbacks: BulkActionCallbacks;

  // Status dropdown state
  private statusDropdown: HTMLElement | null = null;
  private priorityDropdown: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement, callbacks: BulkActionCallbacks) {
    this.callbacks = callbacks;

    this.element = createElement('div', { className: 'bulk-toolbar', role: 'toolbar', 'aria-label': 'Bulk card actions' });
    this.element.style.display = 'none';

    const left = createElement('div', { className: 'bulk-toolbar-left' });
    this.countEl = createElement('span', { className: 'bulk-select-count' }, '0 cards selected');

    const clearBtn = createElement('button', {
      className: 'bulk-toolbar-action bulk-toolbar-clear',
      title: 'Clear selection',
    }, '✕ Clear');
    clearBtn.addEventListener('click', () => this.callbacks.onClearSelection());

    left.appendChild(this.countEl);
    left.appendChild(clearBtn);

    this.actionsEl = createElement('div', { className: 'bulk-toolbar-actions' });
    this.buildActions();

    this.element.appendChild(left);
    this.element.appendChild(this.actionsEl);

    this.parentElement.appendChild(this.element);

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
      if (!this.element.contains(e.target as Node)) {
        this.closeDropdowns();
      }
    });
  }

  private buildActions(): void {
    this.actionsEl.innerHTML = '';

    // Duplicate selected
    const dupBtn = createElement('button', {
      className: 'bulk-toolbar-action',
      title: 'Duplicate selected cards',
    }, '📋 Duplicate');
    dupBtn.addEventListener('click', () => this.handleDuplicateSelected());
    this.actionsEl.appendChild(dupBtn);

    // Delete selected
    const delBtn = createElement('button', {
      className: 'bulk-toolbar-action bulk-toolbar-action--danger',
      title: 'Delete selected cards',
    }, '🗑️ Delete');
    delBtn.addEventListener('click', () => this.handleDeleteSelected());
    this.actionsEl.appendChild(delBtn);

    // Set status dropdown trigger
    const statusTrigger = createElement('button', {
      className: 'bulk-toolbar-action bulk-toolbar-dropdown-trigger',
      title: 'Set status for all selected',
    }, '🏷️ Set Status ▾');
    statusTrigger.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.statusDropdown) {
        this.closeDropdowns();
      } else {
        this.closeDropdowns();
        this.openStatusDropdown(statusTrigger);
      }
    });
    this.actionsEl.appendChild(statusTrigger);

    // Set priority dropdown trigger
    const priorityTrigger = createElement('button', {
      className: 'bulk-toolbar-action bulk-toolbar-dropdown-trigger',
      title: 'Set priority for all selected',
    }, '🔢 Set Priority ▾');
    priorityTrigger.addEventListener('click', (e) => {
      e.stopPropagation();
      if (this.priorityDropdown) {
        this.closeDropdowns();
      } else {
        this.closeDropdowns();
        this.openPriorityDropdown(priorityTrigger);
      }
    });
    this.actionsEl.appendChild(priorityTrigger);

    // Assign to input wrapper
    const assignWrapper = createElement('div', { className: 'bulk-toolbar-assign-wrapper' });
    const assignInput = createElement('input') as HTMLInputElement;
    assignInput.type = 'text';
    assignInput.className = 'bulk-toolbar-assign-input';
    assignInput.placeholder = '👤 Assign to…';
    assignInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const val = assignInput.value.trim();
        if (val) {
          this.handleAssignAll(val);
          assignInput.value = '';
        }
      }
    });
    const assignBtn = createElement('button', {
      className: 'bulk-toolbar-action',
      title: 'Assign selected cards',
    }, 'Apply');
    assignBtn.addEventListener('click', () => {
      const val = assignInput.value.trim();
      if (val) {
        this.handleAssignAll(val);
        assignInput.value = '';
      }
    });
    assignWrapper.appendChild(assignInput);
    assignWrapper.appendChild(assignBtn);
    this.actionsEl.appendChild(assignWrapper);
  }

  private openStatusDropdown(trigger: HTMLElement): void {
    const dropdown = createElement('div', { className: 'bulk-toolbar-dropdown' });

    const statusOptions: Array<{ label: string; value: CardStatus }> = CARD_STATUSES.map((s) => ({
      label: CARD_STATUS_LABELS[s] || s,
      value: s as CardStatus,
    }));

    statusOptions.forEach(({ label, value }) => {
      const item = createElement('button', { className: 'bulk-toolbar-dropdown-item' }, label);
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeDropdowns();
        this.handleSetStatusAll(value);
      });
      dropdown.appendChild(item);
    });

    this.positionDropdown(dropdown, trigger);
    this.statusDropdown = dropdown;
  }

  private openPriorityDropdown(trigger: HTMLElement): void {
    const PRIORITY_OPTIONS = [
      { label: '🟢 Low', value: 0 },
      { label: '🟡 Medium', value: 1 },
      { label: '🟠 High', value: 2 },
      { label: '🔴 Critical', value: 3 },
    ];

    const dropdown = createElement('div', { className: 'bulk-toolbar-dropdown' });
    PRIORITY_OPTIONS.forEach(({ label, value }) => {
      const item = createElement('button', { className: 'bulk-toolbar-dropdown-item' }, label);
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        this.closeDropdowns();
        this.handleSetPriorityAll(value);
      });
      dropdown.appendChild(item);
    });

    this.positionDropdown(dropdown, trigger);
    this.priorityDropdown = dropdown;
  }

  private positionDropdown(dropdown: HTMLElement, trigger: HTMLElement): void {
    document.body.appendChild(dropdown);
    const rect = trigger.getBoundingClientRect();
    const dropH = 160;
    const dropW = 160;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = rect.left;
    // Open upward since toolbar is at the bottom
    let top = rect.top - dropH - 4;
    if (top < 0) top = rect.bottom + 4;
    if (left + dropW > vw) left = vw - dropW - 8;
    dropdown.style.left = `${left}px`;
    dropdown.style.top = `${top}px`;
  }

  private closeDropdowns(): void {
    if (this.statusDropdown) {
      this.statusDropdown.remove();
      this.statusDropdown = null;
    }
    if (this.priorityDropdown) {
      this.priorityDropdown.remove();
      this.priorityDropdown = null;
    }
  }

  // ── Bulk Handlers ──────────────────────────────────────────────────────────

  private async handleDuplicateSelected(): Promise<void> {
    const ids = Array.from(this.selectedIds);
    if (ids.length === 0) return;

    let successCount = 0;
    for (const id of ids) {
      const newCard = await apiClient.duplicateCard(id);
      if (newCard) {
        const cards = appState.get('cards') as Card[];
        appState.set('cards', [...cards, newCard]);
        eventBus.emit(EVENTS.CARD_CREATED, newCard);
        successCount++;
      }
    }

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `📋 Duplicated ${successCount} card${successCount !== 1 ? 's' : ''}`,
      type: successCount > 0 ? 'success' : 'error',
      duration: 3000,
    });

    this.callbacks.onClearSelection();
  }

  private handleDeleteSelected(): void {
    const ids = Array.from(this.selectedIds);
    if (ids.length === 0) return;

    if (!confirm(`Delete ${ids.length} selected card${ids.length !== 1 ? 's' : ''}? This cannot be undone.`)) {
      return;
    }

    let count = 0;
    for (const id of ids) {
      cardService.delete(id);
      count++;
    }

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `🗑️ Deleted ${count} card${count !== 1 ? 's' : ''}`,
      type: 'success',
      duration: 3000,
    });

    this.callbacks.onClearSelection();
  }

  private handleSetStatusAll(status: CardStatus): void {
    const ids = Array.from(this.selectedIds);
    if (ids.length === 0) return;

    for (const id of ids) {
      cardService.move(id, status);
    }

    const label = CARD_STATUS_LABELS[status] || status;
    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `🏷️ Set ${ids.length} card${ids.length !== 1 ? 's' : ''} to "${label}"`,
      type: 'success',
      duration: 3000,
    });

    this.callbacks.onClearSelection();
  }

  private handleSetPriorityAll(priority: number): void {
    const ids = Array.from(this.selectedIds);
    if (ids.length === 0) return;

    const PRIORITY_LABELS = ['Low', 'Medium', 'High', 'Critical'];

    for (const id of ids) {
      cardService.update(id, { priority });
    }

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `🔢 Set priority to ${PRIORITY_LABELS[priority] || priority} for ${ids.length} card${ids.length !== 1 ? 's' : ''}`,
      type: 'success',
      duration: 3000,
    });

    this.callbacks.onClearSelection();
  }

  private handleAssignAll(assignee: string): void {
    const ids = Array.from(this.selectedIds);
    if (ids.length === 0) return;

    for (const id of ids) {
      cardService.update(id, { assignee });
    }

    eventBus.emit(EVENTS.TOAST_SHOW, {
      message: `👤 Assigned ${ids.length} card${ids.length !== 1 ? 's' : ''} to "${assignee}"`,
      type: 'success',
      duration: 3000,
    });

    this.callbacks.onClearSelection();
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  setSelection(ids: Set<string>): void {
    this.selectedIds = new Set(ids);
    const count = this.selectedIds.size;
    this.countEl.textContent = `${count} card${count !== 1 ? 's' : ''} selected`;

    if (count > 0) {
      this.element.style.display = '';
      this.element.classList.add('bulk-toolbar--visible');
    } else {
      this.element.style.display = 'none';
      this.element.classList.remove('bulk-toolbar--visible');
      this.closeDropdowns();
    }
  }

  destroy(): void {
    this.closeDropdowns();
    this.element.remove();
  }
}
