import { Card, CardStatus } from '../../types';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';

// ─── Timeline config ────────────────────────────────────────────────────────

const WEEK_WIDTH_PX = 140;     // px per week column
const ROW_HEIGHT_PX = 42;      // px per card row
const LABEL_WIDTH_PX = 180;    // px for left label column
const WEEKS_BEFORE = 4;
const WEEKS_AFTER = 4;
const TOTAL_WEEKS = WEEKS_BEFORE + 1 + WEEKS_AFTER; // 9

// Estimated duration (in ms) for each status
const MS_PER_DAY = 86_400_000;
const MS_PER_WEEK = 7 * MS_PER_DAY;
const STATUS_DURATION: Record<CardStatus, number> = {
  card:           0, // Main Board cards don't appear on roadmap
  idea:           MS_PER_WEEK * 1,
  todo:           MS_PER_WEEK * 1,
  'in-progress':  MS_PER_WEEK * 2,
  done:           0, // computed from updatedAt
};

// Priority label → class suffix
const PRIORITY_CLASS: Record<number, string> = {
  3: 'critical',
  2: 'high',
  1: 'medium',
  0: 'low',
};

// Group order
const STATUS_GROUPS: { status: CardStatus; label: string; icon: string }[] = [
  { status: 'in-progress', label: 'In Progress', icon: '🔨' },
  { status: 'todo',        label: 'Todo',        icon: '📋' },
  { status: 'idea',        label: 'Ideas',       icon: '💡' },
  { status: 'done',        label: 'Done',        icon: '✅' },
];

// ─── Helpers ────────────────────────────────────────────────────────────────

function startOfWeek(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay(); // 0=Sun
  d.setDate(d.getDate() - day);
  d.setHours(0, 0, 0, 0);
  return d;
}

function addWeeks(date: Date, n: number): Date {
  const d = new Date(date);
  d.setDate(d.getDate() + n * 7);
  return d;
}

function formatWeekLabel(date: Date): string {
  const month = date.toLocaleString('default', { month: 'short' });
  const day = date.getDate();
  return `${month} ${day}`;
}

// ─── Component ──────────────────────────────────────────────────────────────

export class ProjectRoadmap {
  private container: HTMLElement;
  private tooltip: HTMLElement | null = null;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'roadmap-view' });
    this.render();
    this.setupListeners();
    this.parentElement.appendChild(this.container);
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  private render(): void {
    this.container.innerHTML = '';

    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      this.renderEmpty('No project selected.');
      return;
    }

    const cards = appState.getCardsByProject(projectId);
    if (cards.length === 0) {
      this.renderEmpty('No cards yet. Add cards to your project to see the roadmap.');
      return;
    }

    // Timeline boundaries
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const currentWeekStart = startOfWeek(today);
    const timelineStart = addWeeks(currentWeekStart, -WEEKS_BEFORE);
    const timelineEnd   = addWeeks(currentWeekStart,  WEEKS_AFTER + 1); // exclusive
    const totalMs = timelineEnd.getTime() - timelineStart.getTime();

    // (page title handled by ProjectHeader)

    // ── Scroll wrapper (header + rows share horizontal scroll)
    const scrollWrapper = createElement('div', { className: 'roadmap-scroll-wrapper' });
    const innerWidth = LABEL_WIDTH_PX + TOTAL_WEEKS * WEEK_WIDTH_PX;

    // ── Header (week labels + today line)
    const header = createElement('div', { className: 'roadmap-header' });
    header.style.width = `${innerWidth}px`;

    // Label spacer
    const spacer = createElement('div', { className: 'roadmap-label-spacer' });
    spacer.style.width = `${LABEL_WIDTH_PX}px`;
    header.appendChild(spacer);

    // Week columns
    const weeksArea = createElement('div', { className: 'roadmap-weeks-area' });
    weeksArea.style.width = `${TOTAL_WEEKS * WEEK_WIDTH_PX}px`;

    for (let w = 0; w < TOTAL_WEEKS; w++) {
      const weekStart = addWeeks(timelineStart, w);
      const isCurrentWeek = weekStart.getTime() === currentWeekStart.getTime();
      const col = createElement('div', { className: `roadmap-week-col${isCurrentWeek ? ' current-week' : ''}` });
      col.style.width = `${WEEK_WIDTH_PX}px`;
      col.textContent = formatWeekLabel(weekStart);
      weeksArea.appendChild(col);
    }
    header.appendChild(weeksArea);
    scrollWrapper.appendChild(header);

    // ── Rows body
    const body = createElement('div', { className: 'roadmap-body' });
    body.style.width = `${innerWidth}px`;
    body.style.position = 'relative';

    // Today vertical line
    const todayOffsetMs = today.getTime() - timelineStart.getTime();
    const todayPct = todayOffsetMs / totalMs;
    const todayPx = LABEL_WIDTH_PX + todayPct * (TOTAL_WEEKS * WEEK_WIDTH_PX);
    const todayLine = createElement('div', { className: 'roadmap-today' });
    todayLine.style.left = `${todayPx}px`;
    body.appendChild(todayLine);

    // Week grid lines
    for (let w = 0; w <= TOTAL_WEEKS; w++) {
      const gridLine = createElement('div', { className: 'roadmap-grid-line' });
      gridLine.style.left = `${LABEL_WIDTH_PX + w * WEEK_WIDTH_PX}px`;
      body.appendChild(gridLine);
    }

    // Groups
    STATUS_GROUPS.forEach(({ status, label, icon }) => {
      const groupCards = cards.filter((c) => c.status === status);
      if (groupCards.length === 0) return;

      // Section header
      const sectionLabel = createElement('div', { className: 'roadmap-section-label' });
      sectionLabel.style.width = `${innerWidth}px`;
      sectionLabel.textContent = `${icon} ${label}`;
      body.appendChild(sectionLabel);

      // Rows
      groupCards.forEach((card) => {
        const row = this.buildRow(card, timelineStart, totalMs);
        body.appendChild(row);
      });
    });

    scrollWrapper.appendChild(body);
    this.container.appendChild(scrollWrapper);

    // Tooltip (shared, absolute positioned)
    this.tooltip = createElement('div', { className: 'roadmap-tooltip' });
    this.tooltip.style.display = 'none';
    document.body.appendChild(this.tooltip);
  }

  // ── Build a single card row ──────────────────────────────────────────────

  private buildRow(card: Card, timelineStart: Date, totalMs: number): HTMLElement {
    const row = createElement('div', { className: 'roadmap-row' });

    // Label
    const label = createElement('div', { className: 'roadmap-row-label' });
    label.style.width = `${LABEL_WIDTH_PX}px`;
    label.textContent = card.title.length > 22 ? card.title.slice(0, 22) + '…' : card.title;
    label.title = card.title;
    row.appendChild(label);

    // Timeline area
    const timeArea = createElement('div', { className: 'roadmap-row-time' });
    timeArea.style.width = `${TOTAL_WEEKS * WEEK_WIDTH_PX}px`;

    // Compute bar position
    const startMs = card.createdAt;
    let endMs: number;
    if (card.status === 'done') {
      endMs = card.updatedAt > card.createdAt ? card.updatedAt : card.createdAt + MS_PER_WEEK;
    } else {
      endMs = startMs + STATUS_DURATION[card.status];
    }

    const tlStartMs = timelineStart.getTime();
    const tlEndMs = tlStartMs + totalMs;

    // Clamp to timeline
    const barStartMs = Math.max(startMs, tlStartMs);
    const barEndMs   = Math.min(endMs, tlEndMs);

    if (barEndMs > barStartMs) {
      const leftPct  = (barStartMs - tlStartMs) / totalMs;
      const widthPct = (barEndMs - barStartMs)  / totalMs;

      const barLeft  = leftPct  * (TOTAL_WEEKS * WEEK_WIDTH_PX);
      const barWidth = Math.max(widthPct * (TOTAL_WEEKS * WEEK_WIDTH_PX), 6); // min 6px

      const priorityClass = PRIORITY_CLASS[card.priority] ?? 'low';
      const bar = createElement('div', { className: `roadmap-bar ${priorityClass}` });
      bar.style.left  = `${barLeft}px`;
      bar.style.width = `${barWidth}px`;

      // Bar inner label
      const barLabel = createElement('span', { className: 'roadmap-bar-label' });
      barLabel.textContent = card.title;
      bar.appendChild(barLabel);

      // Hover → tooltip
      bar.addEventListener('mouseenter', (e) => this.showTooltip(e, card));
      bar.addEventListener('mousemove', (e) => this.moveTooltip(e));
      bar.addEventListener('mouseleave', () => this.hideTooltip());

      // Click → CardDetailModal
      bar.addEventListener('click', () => {
        appState.selectCard(card.id);
        eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', cardId: card.id });
      });

      timeArea.appendChild(bar);
    }

    row.appendChild(timeArea);
    return row;
  }

  // ── Tooltip ───────────────────────────────────────────────────────────────

  private showTooltip(e: MouseEvent, card: Card): void {
    if (!this.tooltip) return;

    const statusLabels: Record<CardStatus, string> = {
      'card':        '📝 Card',
      'idea':        '💡 Idea',
      'todo':        '📋 Todo',
      'in-progress': '🔨 In Progress',
      'done':        '✅ Done',
    };
    const priorityLabels: Record<number, string> = { 3: '🔴 Critical', 2: '🟠 High', 1: '🟡 Medium', 0: '🟢 Low' };
    const created = new Date(card.createdAt).toLocaleDateString();
    const updated = new Date(card.updatedAt).toLocaleDateString();

    this.tooltip.innerHTML = `
      <div class="tooltip-title">${card.title}</div>
      <div class="tooltip-row"><span>Status:</span> ${statusLabels[card.status] ?? card.status}</div>
      <div class="tooltip-row"><span>Priority:</span> ${priorityLabels[card.priority] ?? card.priority}</div>
      ${card.tags?.length ? `<div class="tooltip-row"><span>Tags:</span> ${card.tags.join(', ')}</div>` : ''}
      <div class="tooltip-row"><span>Created:</span> ${created}</div>
      <div class="tooltip-row"><span>Updated:</span> ${updated}</div>
      <div class="tooltip-hint">Click to open</div>
    `;
    this.tooltip.style.display = 'block';
    this.moveTooltip(e);
  }

  private moveTooltip(e: MouseEvent): void {
    if (!this.tooltip) return;
    const offset = 14;
    let x = e.clientX + offset;
    let y = e.clientY + offset;
    const tw = this.tooltip.offsetWidth || 220;
    const th = this.tooltip.offsetHeight || 120;
    if (x + tw > window.innerWidth - 8)  x = e.clientX - tw - offset;
    if (y + th > window.innerHeight - 8) y = e.clientY - th - offset;
    this.tooltip.style.left = `${x}px`;
    this.tooltip.style.top  = `${y}px`;
  }

  private hideTooltip(): void {
    if (this.tooltip) this.tooltip.style.display = 'none';
  }

  // ── Empty state ───────────────────────────────────────────────────────────

  private renderEmpty(message: string): void {
    const empty = createElement('div', { className: 'roadmap-empty' });
    empty.textContent = message;
    this.container.appendChild(empty);
  }

  // ── Listeners ─────────────────────────────────────────────────────────────

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_CREATED, () => this.refresh()),
      eventBus.on(EVENTS.CARD_UPDATED, () => this.refresh()),
      eventBus.on(EVENTS.CARD_DELETED, () => this.refresh()),
      eventBus.on(EVENTS.CARD_MOVED,   () => this.refresh()),
      eventBus.on(EVENTS.PROJECT_SELECTED, () => this.refresh()),
    );
  }

  private refresh(): void {
    this.hideTooltip();
    this.render();
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  update(): void {
    this.refresh();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.hideTooltip();
    if (this.tooltip) {
      this.tooltip.remove();
      this.tooltip = null;
    }
    this.container.remove();
  }
}
