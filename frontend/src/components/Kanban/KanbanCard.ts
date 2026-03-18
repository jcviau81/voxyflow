import { Card, ChecklistProgress } from '../../types';
import { createElement, truncate } from '../../utils/helpers';
import { AGENT_PERSONAS, AGENT_TYPE_EMOJI } from '../../utils/constants';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';

// ── Vote localStorage helpers ─────────────────────────────────────────────────
function isVoted(cardId: string): boolean {
  return localStorage.getItem(`voxy_voted_${cardId}`) === 'true';
}

function setVoted(cardId: string, voted: boolean): void {
  if (voted) {
    localStorage.setItem(`voxy_voted_${cardId}`, 'true');
  } else {
    localStorage.removeItem(`voxy_voted_${cardId}`);
  }
}

// ── Assignee avatar helpers ───────────────────────────────────────────────────
const ASSIGNEE_AVATAR_COLORS = [
  '#e53935', '#8e24aa', '#1e88e5', '#00897b',
  '#43a047', '#fb8c00', '#f4511e', '#6d4c41',
];

function getAssigneeInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w[0] ?? '')
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

function assigneeNameToColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  }
  return ASSIGNEE_AVATAR_COLORS[hash % ASSIGNEE_AVATAR_COLORS.length];
}

// ── Tag color system ──────────────────────────────────────────────────────────
// 8 muted pastel pairs: [background, text] for dark theme.
const TAG_COLORS: Array<[string, string]> = [
  ['rgba(255, 107, 107, 0.18)', '#ff6b6b'],   // red
  ['rgba(78, 205, 196, 0.18)', '#4ecdc4'],    // teal/accent
  ['rgba(255, 183, 77, 0.18)', '#ffb74d'],    // amber
  ['rgba(66, 165, 245, 0.18)', '#42a5f5'],    // blue
  ['rgba(171, 145, 249, 0.18)', '#ab91f9'],   // lavender
  ['rgba(102, 187, 106, 0.18)', '#66bb6a'],   // green
  ['rgba(255, 138, 101, 0.18)', '#ff8a65'],   // orange
  ['rgba(236, 64, 122, 0.18)', '#ec407a'],    // pink
];

function getTagColor(tag: string): [string, string] {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = (hash * 31 + tag.charCodeAt(i)) >>> 0;
  }
  return TAG_COLORS[hash % TAG_COLORS.length];
}

export class KanbanCard {
  private element: HTMLElement;
  private titleEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement, private card: Card) {
    this.element = createElement('div', {
      className: 'kanban-card',
      draggable: 'true',
      'data-card-id': card.id,
    });
    this.render();
    this.setupDrag();
  }

  private escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  private highlightText(text: string, query: string): string {
    if (!query) return this.escapeHtml(text);
    const escaped = this.escapeHtml(text);
    const escapedQuery = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return escaped.replace(
      new RegExp(escapedQuery, 'gi'),
      (match) => `<mark class="search-highlight">${match}</mark>`
    );
  }

  render(): void {
    this.element.innerHTML = '';

    // Title
    const title = createElement('div', { className: 'kanban-card-title' }, this.card.title);
    this.titleEl = title;

    // Description preview
    const desc = createElement(
      'div',
      { className: 'kanban-card-desc' },
      truncate(this.card.description, 80)
    );

    // Footer with metadata
    const footer = createElement('div', { className: 'kanban-card-footer' });

    // Agent badge — show emoji for non-ember agent types
    const agentType = this.card.agentType;
    if (agentType && agentType !== 'ember') {
      const emoji = AGENT_TYPE_EMOJI[agentType];
      if (emoji) {
        const badge = createElement('span', { className: 'agent-badge', title: agentType }, emoji);
        footer.appendChild(badge);
      }
    } else if (!agentType && this.card.assignedAgent) {
      // Fallback: legacy assignedAgent field
      const persona = AGENT_PERSONAS[this.card.assignedAgent];
      if (persona) {
        const agent = createElement('span', { className: 'agent-badge' }, persona.emoji);
        footer.appendChild(agent);
      }
    }

    // Tags — colored pills, max 3 visible + "+N more", click to filter
    if (this.card.tags.length > 0) {
      const tagsEl = createElement('div', { className: 'kanban-card-tags' });
      const visible = this.card.tags.slice(0, 3);
      const remaining = this.card.tags.length - visible.length;

      visible.forEach((tag) => {
        const [bg, color] = getTagColor(tag);
        const tagEl = createElement('span', {
          className: 'card-tag',
          title: tag,
        }, tag);
        tagEl.style.background = bg;
        tagEl.style.color = color;
        tagEl.addEventListener('click', (e) => {
          e.stopPropagation();
          eventBus.emit(EVENTS.KANBAN_TAG_FILTER, { tag });
        });
        tagsEl.appendChild(tagEl);
      });

      if (remaining > 0) {
        const moreEl = createElement('span', { className: 'card-tag-more' }, `+${remaining}`);
        tagsEl.appendChild(moreEl);
      }

      footer.appendChild(tagsEl);
    }

    // Time tracking badge
    if (this.card.totalMinutes && this.card.totalMinutes > 0) {
      const hours = Math.floor(this.card.totalMinutes / 60);
      const mins = this.card.totalMinutes % 60;
      const timeLabel = hours > 0 ? `⏱ ${hours}h${mins > 0 ? ` ${mins}m` : ''}` : `⏱ ${mins}m`;
      const timeBadge = createElement('span', {
        className: 'time-badge',
        title: `${this.card.totalMinutes} minutes logged`,
      }, timeLabel);
      footer.appendChild(timeBadge);
    }

    // Checklist progress badge
    if (this.card.checklistProgress && this.card.checklistProgress.total > 0) {
      const { total, completed } = this.card.checklistProgress;
      const isDone = completed === total;
      const checklistBadge = createElement('span', {
        className: `checklist-badge${isDone ? ' checklist-badge--done' : ''}`,
        title: `Checklist: ${completed}/${total} completed`,
      }, `☑ ${completed}/${total}`);
      footer.appendChild(checklistBadge);
    }

    // Dependencies indicator
    if (this.card.dependencies.length > 0) {
      const depCards = this.card.dependencies
        .map((id) => appState.getCard(id))
        .filter(Boolean);

      const isBlocked = depCards.some((dep) => dep && dep.status !== 'done');

      const tooltipLines = depCards.map((dep) =>
        dep ? `${dep.status === 'done' ? '✅' : '⏳'} ${dep.title}` : '(unknown card)'
      );
      const tooltipText = tooltipLines.join('\n');

      const depBadge = createElement(
        'span',
        {
          className: 'card-dependency-badge',
          title: tooltipText,
        },
        `🔗 ${this.card.dependencies.length}`
      );
      footer.appendChild(depBadge);

      if (isBlocked) {
        this.element.classList.add('card-blocked');
      } else {
        this.element.classList.remove('card-blocked');
      }
    } else {
      this.element.classList.remove('card-blocked');
    }

    // Vote button
    const voteCount = this.card.votes ?? 0;
    const voted = isVoted(this.card.id);
    const voteBtn = createElement('button', {
      className: 'vote-btn' + (voted ? ' voted' : ''),
      title: voted ? 'Un-vote this card' : 'Vote for this card',
    }, `▲ ${voteCount}`);
    voteBtn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const currentlyVoted = isVoted(this.card.id);
      const newCount = currentlyVoted
        ? await apiClient.unvoteCard(this.card.id)
        : await apiClient.voteCard(this.card.id);
      if (newCount !== null) {
        setVoted(this.card.id, !currentlyVoted);
        this.card = { ...this.card, votes: newCount };
        voteBtn.textContent = `▲ ${newCount}`;
        voteBtn.className = 'vote-btn' + (!currentlyVoted ? ' voted' : '');
        voteBtn.title = !currentlyVoted ? 'Un-vote this card' : 'Vote for this card';
        appState.updateCard(this.card.id, { votes: newCount });
      }
    });
    footer.appendChild(voteBtn);

    // Assignee avatar badge (bottom-left)
    if (this.card.assignee) {
      const avatarEl = createElement('div', {
        className: 'assignee-avatar',
        title: `Assigned to: ${this.card.assignee}`,
      }, getAssigneeInitials(this.card.assignee));
      avatarEl.style.background = assigneeNameToColor(this.card.assignee);
      this.element.appendChild(avatarEl);
    }

    this.element.appendChild(title);
    if (this.card.description) {
      this.element.appendChild(desc);
    }
    this.element.appendChild(footer);

    // Click to edit via inline form
    this.element.addEventListener('click', () => {
      appState.selectCard(this.card.id);
      eventBus.emit(EVENTS.CARD_FORM_SHOW, {
        mode: 'edit',
        card: this.card,
        projectId: this.card.projectId,
      });
    });

    this.parentElement.appendChild(this.element);
  }

  private setupDrag(): void {
    this.element.addEventListener('dragstart', (e: DragEvent) => {
      if (e.dataTransfer) {
        e.dataTransfer.setData('text/plain', this.card.id);
        e.dataTransfer.effectAllowed = 'move';
      }
      this.element.classList.add('dragging');
    });

    this.element.addEventListener('dragend', () => {
      this.element.classList.remove('dragging');
    });
  }

  setHighlight(query: string): void {
    if (!this.titleEl) return;
    this.titleEl.innerHTML = this.highlightText(this.card.title, query);
  }

  /**
   * Apply filter criteria. Returns true if card is visible.
   * Hides/shows via display style.
   */
  applyFilter(
    query: string,
    priorityFilter: number | null,
    agentFilter: string | null,
    tagFilter: string | null = null,
  ): boolean {
    const titleMatch = query
      ? this.card.title.toLowerCase().includes(query.toLowerCase())
      : true;
    const priorityMatch = priorityFilter !== null
      ? this.card.priority === priorityFilter
      : true;
    const agentMatch = agentFilter
      ? (this.card.agentType || 'ember') === agentFilter
      : true;
    // Tag filter: OR semantics — card visible if it has the tag (single tag selected)
    const tagMatch = tagFilter
      ? this.card.tags.some((t) => t.toLowerCase() === tagFilter.toLowerCase())
      : true;

    const visible = titleMatch && priorityMatch && agentMatch && tagMatch;
    this.element.style.display = visible ? '' : 'none';

    // Apply highlight when visible
    if (visible) {
      this.setHighlight(query);
    }

    return visible;
  }

  getCardData(): Card {
    return this.card;
  }

  update(card: Card): void {
    this.card = card;
    this.render();
  }

  destroy(): void {
    this.element.remove();
  }
}
