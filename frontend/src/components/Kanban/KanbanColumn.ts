import { Card } from '../../types';
import { createElement } from '../../utils/helpers';
import { KanbanCard } from './KanbanCard';
import { apiClient } from '../../services/ApiClient';

// ── Sort modes ─────────────────────────────────────────────────────────────────

export type ColumnSortMode =
  | 'createdAt_desc'
  | 'updatedAt_desc'
  | 'alpha_asc'
  | 'alpha_desc'
  | 'priority_desc'
  | 'manual'
  | 'votes';

export interface SortOption {
  value: ColumnSortMode;
  label: string;
}

/** All sort modes available in the selector (manual excluded — it's a special toggle) */
export const SORT_OPTIONS: SortOption[] = [
  { value: 'priority_desc', label: '⬆ Priority' },
  { value: 'createdAt_desc', label: '🕐 Newest first' },
  { value: 'updatedAt_desc', label: '🔄 Recently updated' },
  { value: 'alpha_asc', label: '🔤 A → Z' },
  { value: 'alpha_desc', label: '🔤 Z → A' },
  { value: 'votes', label: '▲ Votes' },
];

/** Default sort mode per column status */
export const DEFAULT_SORT_PER_STATUS: Record<string, ColumnSortMode> = {
  idea: 'createdAt_desc',
  todo: 'createdAt_desc',
  'in-progress': 'priority_desc',
  done: 'updatedAt_desc',
  card: 'createdAt_desc',
};

/** Columns that support manual drag-and-drop reorder */
const MANUAL_SORT_ALLOWED = new Set(['idea', 'todo', 'card']);

// ── localStorage helpers ───────────────────────────────────────────────────────

function sortStorageKey(projectId: string, status: string): string {
  return `voxy:sort:${projectId}:${status}`;
}

export function loadSortMode(projectId: string, status: string): ColumnSortMode {
  try {
    const stored = localStorage.getItem(sortStorageKey(projectId, status));
    if (stored) return stored as ColumnSortMode;
  } catch (_) { /* ignore */ }
  return DEFAULT_SORT_PER_STATUS[status] ?? 'priority_desc';
}

export function saveSortMode(projectId: string, status: string, mode: ColumnSortMode): void {
  try {
    localStorage.setItem(sortStorageKey(projectId, status), mode);
  } catch (_) { /* ignore */ }
}

// ── Sort engine ────────────────────────────────────────────────────────────────

export function sortCards(cards: Card[], mode: ColumnSortMode): Card[] {
  const arr = [...cards];
  switch (mode) {
    case 'createdAt_desc':
      return arr.sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
    case 'updatedAt_desc':
      return arr.sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
    case 'alpha_asc':
      return arr.sort((a, b) => a.title.localeCompare(b.title));
    case 'alpha_desc':
      return arr.sort((a, b) => b.title.localeCompare(a.title));
    case 'votes':
      return arr.sort(
        (a, b) =>
          (b.votes ?? 0) - (a.votes ?? 0) ||
          b.priority - a.priority ||
          (b.createdAt ?? 0) - (a.createdAt ?? 0),
      );
    case 'manual':
      // Use the persisted `position` field; fall back to createdAt for ties
      return arr.sort(
        (a, b) =>
          (a.position ?? 0) - (b.position ?? 0) ||
          (a.createdAt ?? 0) - (b.createdAt ?? 0),
      );
    case 'priority_desc':
    default:
      return arr.sort(
        (a, b) =>
          b.priority - a.priority ||
          (b.updatedAt ?? 0) - (a.updatedAt ?? 0),
      );
  }
}

// ── KanbanColumn ───────────────────────────────────────────────────────────────

export class KanbanColumn {
  private element: HTMLElement;
  private cardContainer: HTMLElement;
  private countEl: HTMLElement;
  private sortBtn: HTMLElement;
  private sortMenu: HTMLElement;
  private cardComponents: Map<string, KanbanCard> = new Map();

  private currentSortMode: ColumnSortMode;
  private currentProjectId: string = '';
  private currentCards: Card[] = [];

  // Drag-and-drop manual reorder state
  private draggingCardEl: HTMLElement | null = null;
  private dragSourceIndex: number = -1;

  constructor(
    private parentElement: HTMLElement,
    private status: string,
    private label: string,
  ) {
    this.currentSortMode = DEFAULT_SORT_PER_STATUS[status] ?? 'priority_desc';

    this.element = createElement('div', {
      className: 'kanban-column',
      'data-status': status,
      'data-testid': 'kanban-column',
    });

    // ── Header ──
    const header = createElement('div', { className: 'kanban-column-header' });
    const titleEl = createElement('span', { className: 'kanban-column-title' }, label);
    this.countEl = createElement('span', { className: 'kanban-column-count' }, '0');

    // Sort button + dropdown
    const sortWrapper = createElement('div', { className: 'kanban-sort-wrapper' });
    this.sortBtn = createElement('button', {
      className: 'kanban-sort-btn',
      title: 'Sort column',
      'aria-haspopup': 'true',
      'aria-expanded': 'false',
    }, '↕');
    this.sortMenu = createElement('div', { className: 'kanban-sort-menu' });
    this.sortMenu.style.display = 'none';
    this.buildSortMenu();

    this.sortBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = this.sortMenu.style.display !== 'none';
      this.sortMenu.style.display = open ? 'none' : '';
      this.sortBtn.setAttribute('aria-expanded', String(!open));
    });

    // Close menu when clicking outside
    document.addEventListener('click', () => {
      this.sortMenu.style.display = 'none';
      this.sortBtn.setAttribute('aria-expanded', 'false');
    }, { capture: false });

    sortWrapper.appendChild(this.sortBtn);
    sortWrapper.appendChild(this.sortMenu);

    header.appendChild(titleEl);
    header.appendChild(this.countEl);
    header.appendChild(sortWrapper);

    // ── Card container ──
    this.cardContainer = createElement('div', { className: 'kanban-column-cards' });

    // ── Cross-column drop zone (status change) ──
    this.element.addEventListener('dragenter', (e) => {
      e.preventDefault();
      // Only highlight for cross-column drops (card moving from another column)
      const dragging = document.querySelector('.kanban-card--dragging');
      if (dragging) {
        const sourceStatus = (dragging as HTMLElement).dataset.cardStatus;
        if (sourceStatus !== this.status) {
          this.element.classList.add('drag-over');
        }
      }
    });
    this.element.addEventListener('dragleave', (e: DragEvent) => {
      if (!this.element.contains(e.relatedTarget as Node)) {
        this.element.classList.remove('drag-over');
      }
    });
    this.element.addEventListener('dragover', (e) => {
      e.preventDefault();
    });
    this.element.addEventListener('drop', () => {
      this.element.classList.remove('drag-over');
    });

    this.element.appendChild(header);
    this.element.appendChild(this.cardContainer);
    this.parentElement.appendChild(this.element);
  }

  // ── Build / rebuild the sort dropdown ──────────────────────────────────────

  private buildSortMenu(): void {
    this.sortMenu.innerHTML = '';

    const options = [...SORT_OPTIONS];

    // Add "Manual" option only for supported columns
    if (MANUAL_SORT_ALLOWED.has(this.status)) {
      options.push({ value: 'manual', label: '✋ Manual order' });
    }

    options.forEach(({ value, label }) => {
      const item = createElement('button', {
        className: 'kanban-sort-menu-item' + (this.currentSortMode === value ? ' active' : ''),
        'data-sort': value,
      }, label);
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        this.applySortMode(value);
        this.sortMenu.style.display = 'none';
        this.sortBtn.setAttribute('aria-expanded', 'false');
      });
      this.sortMenu.appendChild(item);
    });

    // Update button label to reflect current mode
    const activeOption = options.find((o) => o.value === this.currentSortMode);
    this.sortBtn.title = `Sort: ${activeOption?.label ?? 'Sort column'}`;
    this.sortBtn.textContent = this.currentSortMode === 'manual' ? '✋' : '↕';
  }

  private applySortMode(mode: ColumnSortMode): void {
    this.currentSortMode = mode;
    if (this.currentProjectId) {
      saveSortMode(this.currentProjectId, this.status, mode);
    }
    this.buildSortMenu();
    // Re-render with new sort
    this.renderCards(this.currentCards);
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Main entry point: render cards for this column.
   * Called by KanbanBoard on every refresh.
   */
  setCards(
    cards: Card[],
    projectId: string,
    sortMode?: ColumnSortMode,
    selectMode: boolean = false,
    onSelectChange?: (id: string, selected: boolean) => void,
  ): void {
    this.currentCards = cards;
    this.currentProjectId = projectId;

    // Load persisted sort preference, or use the provided override
    if (sortMode !== undefined) {
      this.currentSortMode = sortMode;
    } else {
      this.currentSortMode = loadSortMode(projectId, this.status);
    }

    this.buildSortMenu();
    this.renderCards(cards, selectMode, onSelectChange);
  }

  private renderCards(
    cards: Card[],
    selectMode: boolean = false,
    onSelectChange?: (id: string, selected: boolean) => void,
  ): void {
    // Preserve select state/callbacks from existing cards if not provided
    const hadSelectMode = selectMode;

    this.cardComponents.forEach((c) => c.destroy());
    this.cardComponents.clear();
    this.cardContainer.innerHTML = '';

    const sorted = sortCards(cards, this.currentSortMode);

    sorted.forEach((card, index) => {
      const kanbanCard = new KanbanCard(this.cardContainer, card);
      if (hadSelectMode) {
        kanbanCard.setSelectMode(true);
      }
      if (onSelectChange) {
        kanbanCard.setOnSelectChange(onSelectChange);
      }
      this.cardComponents.set(card.id, kanbanCard);

      // Attach intra-column drag-and-drop for manual sort
      if (this.currentSortMode === 'manual' && MANUAL_SORT_ALLOWED.has(this.status)) {
        this.attachManualDragHandlers(kanbanCard.getElement(), card.id, index);
      }
    });

    this.countEl.textContent = cards.length.toString();
  }

  // ── Manual drag-and-drop within same column ────────────────────────────────

  private attachManualDragHandlers(el: HTMLElement, cardId: string, index: number): void {
    el.setAttribute('draggable', 'true');
    el.dataset.manualIndex = String(index);

    el.addEventListener('dragstart', (e) => {
      this.draggingCardEl = el;
      this.dragSourceIndex = index;
      el.classList.add('kanban-card--dragging-manual');
      e.dataTransfer?.setData('text/plain', cardId);
      e.dataTransfer!.effectAllowed = 'move';
    });

    el.addEventListener('dragend', () => {
      el.classList.remove('kanban-card--dragging-manual');
      this.cardContainer.querySelectorAll('.kanban-card--drag-placeholder').forEach((p) => p.remove());
      this.cardContainer.querySelectorAll('.kanban-card').forEach((c) => {
        (c as HTMLElement).classList.remove('kanban-card--drag-over-top', 'kanban-card--drag-over-bottom');
      });
      this.draggingCardEl = null;
      this.dragSourceIndex = -1;
    });

    el.addEventListener('dragover', (e) => {
      if (!this.draggingCardEl || this.draggingCardEl === el) return;
      e.preventDefault();
      e.stopPropagation();
      e.dataTransfer!.dropEffect = 'move';

      const rect = el.getBoundingClientRect();
      const midY = rect.top + rect.height / 2;
      const isAbove = e.clientY < midY;

      this.cardContainer.querySelectorAll('.kanban-card').forEach((c) => {
        (c as HTMLElement).classList.remove('kanban-card--drag-over-top', 'kanban-card--drag-over-bottom');
      });
      el.classList.add(isAbove ? 'kanban-card--drag-over-top' : 'kanban-card--drag-over-bottom');
    });

    el.addEventListener('dragleave', () => {
      el.classList.remove('kanban-card--drag-over-top', 'kanban-card--drag-over-bottom');
    });

    el.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      el.classList.remove('kanban-card--drag-over-top', 'kanban-card--drag-over-bottom');

      if (!this.draggingCardEl || this.draggingCardEl === el) return;

      const rect = el.getBoundingClientRect();
      const isAbove = e.clientY < rect.top + rect.height / 2;

      // Reorder the card elements in the DOM
      if (isAbove) {
        this.cardContainer.insertBefore(this.draggingCardEl, el);
      } else {
        this.cardContainer.insertBefore(this.draggingCardEl, el.nextSibling);
      }

      // Persist new order
      this.persistManualOrder();
    });
  }

  /**
   * After a manual drag-and-drop reorder, persist the new position values.
   */
  private persistManualOrder(): void {
    const cardEls = Array.from(this.cardContainer.querySelectorAll('[data-card-id]'));
    const orderedIds = cardEls.map((el) => (el as HTMLElement).dataset.cardId ?? '').filter(Boolean);

    // Update positions in the in-memory card list so the local state is correct
    orderedIds.forEach((id, idx) => {
      const card = this.currentCards.find((c) => c.id === id);
      if (card) card.position = idx;
    });

    // Fire-and-forget API persistence
    apiClient.reorderCards(orderedIds).catch((err) => {
      console.error('[KanbanColumn] persistManualOrder error:', err);
    });
  }

  // ── Filter & selection passthrough ────────────────────────────────────────

  setSelectMode(active: boolean, onSelectChange?: (id: string, selected: boolean) => void): void {
    this.cardComponents.forEach((card) => {
      card.setSelectMode(active);
      if (onSelectChange) {
        card.setOnSelectChange(onSelectChange);
      }
    });
  }

  clearSelection(): void {
    this.cardComponents.forEach((card) => card.setSelected(false));
  }

  applyFilter(
    query: string,
    priorityFilter: number | null,
    agentFilter: string | null,
    tagFilter: string | null = null,
  ): number {
    let visibleCount = 0;
    this.cardComponents.forEach((card) => {
      if (card.applyFilter(query, priorityFilter, agentFilter, tagFilter)) {
        visibleCount++;
      }
    });
    return visibleCount;
  }

  getCardComponents(): Map<string, KanbanCard> {
    return this.cardComponents;
  }

  getCurrentSortMode(): ColumnSortMode {
    return this.currentSortMode;
  }

  destroy(): void {
    this.cardComponents.forEach((c) => c.destroy());
    this.cardComponents.clear();
    this.element.remove();
  }
}
