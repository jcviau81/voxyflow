import { Card, ChecklistProgress } from '../../types';
import { createElement, truncate } from '../../utils/helpers';
import { AGENT_PERSONAS, AGENT_TYPE_EMOJI } from '../../utils/constants';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';
import { cardService } from '../../services/CardService';
import { chatService } from '../../services/ChatService';

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
  private contextMenu: HTMLElement | null = null;
  private checkboxEl: HTMLInputElement | null = null;
  private selectMode: boolean = false;
  private selected: boolean = false;
  private onSelectChange: ((id: string, selected: boolean) => void) | null = null;

  constructor(private parentElement: HTMLElement, private card: Card) {
    this.element = createElement('div', {
      className: 'kanban-card',
      draggable: 'true',
      'data-card-id': card.id,
      'data-card-status': card.status,
    });
    this.render();
    this.setupDrag();
    this.setupContextMenu();
  }

  /** Expose the root DOM element (used by KanbanColumn for manual sort). */
  getElement(): HTMLElement {
    return this.element;
  }

  private setupContextMenu(): void {
    // Close any open context menu
    const closeMenu = () => {
      if (this.contextMenu) {
        this.contextMenu.remove();
        this.contextMenu = null;
      }
    };

    const openMenu = (x: number, y: number) => {
      closeMenu();

      const menu = createElement('div', { className: 'card-context-menu' });

      // Get other projects for clone/move submenus
      const allProjects = (appState.get('projects') as import('../../types').Project[]) ?? [];
      const otherProjects = allProjects.filter((p) => p.id !== this.card.projectId);

      // Helper to build a submenu item with a nested project list
      const buildSubmenuItem = (
        icon: string,
        label: string,
        onSelect: (projectId: string, projectTitle: string) => void,
      ): HTMLElement => {
        const el = createElement('div', { className: 'card-context-item card-context-item--submenu' });
        el.innerHTML = `<span class="card-context-icon">${icon}</span><span>${label}</span><span class="card-context-arrow">›</span>`;

        if (otherProjects.length === 0) {
          el.classList.add('card-context-item--disabled');
          el.title = 'No other projects available';
          return el;
        }

        let submenu: HTMLElement | null = null;

        const openSubmenu = () => {
          closeSubmenu();
          submenu = createElement('div', { className: 'card-context-submenu' });

          otherProjects.forEach((project) => {
            const projectEl = createElement('div', { className: 'card-context-submenu-item' });
            const emoji = project.emoji || '📁';
            const projectName = project.name;
            projectEl.innerHTML = `<span class="card-context-icon">${emoji}</span><span>${projectName}</span>`;
            projectEl.addEventListener('click', (e) => {
              e.stopPropagation();
              closeMenu();
              onSelect(project.id, projectName);
            });
            submenu!.appendChild(projectEl);
          });

          document.body.appendChild(submenu);

          // Position submenu relative to parent item
          const rect = el.getBoundingClientRect();
          const submenuW = 180;
          const submenuH = otherProjects.length * 36 + 8;
          const vw = window.innerWidth;
          const vh = window.innerHeight;
          let left = rect.right + 2;
          let top = rect.top;
          if (left + submenuW > vw) left = rect.left - submenuW - 2;
          if (top + submenuH > vh) top = vh - submenuH - 8;
          submenu.style.left = `${left}px`;
          submenu.style.top = `${top}px`;
        };

        const closeSubmenu = () => {
          if (submenu) {
            submenu.remove();
            submenu = null;
          }
        };

        el.addEventListener('mouseenter', openSubmenu);
        el.addEventListener('mouseleave', (e) => {
          // Keep submenu open if cursor moves into it
          const related = e.relatedTarget as Node | null;
          if (submenu && submenu.contains(related)) return;
          closeSubmenu();
        });
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          if (submenu) {
            closeSubmenu();
          } else {
            openSubmenu();
          }
        });

        // Track submenu reference for cleanup
        el.addEventListener('card:submenu-close', () => closeSubmenu());

        return el;
      };

      const items: Array<{ icon: string; label: string; action: () => void; danger?: boolean } | HTMLElement> = [
        {
          icon: '▶',
          label: 'Execute',
          action: async () => {
            const result = await apiClient.executeCard(this.card.id);
            if (result) {
              chatService.sendMessage(result.prompt, this.card.projectId || undefined, this.card.id);
              eventBus.emit(EVENTS.TOAST_SHOW, { message: `▶ Executing: "${this.card.title}"`, type: 'success', duration: 3000 });
            } else {
              eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Execution failed', type: 'error', duration: 3000 });
            }
          },
        },
        {
          icon: '📌',
          label: 'Move to Board',
          action: async () => {
            const result = await apiClient.patchCard(this.card.id, { status: 'card' });
            if (result) {
              const cards = appState.get('cards') as Card[];
              appState.set('cards', cards.filter(c => c.id !== this.card.id));
              eventBus.emit(EVENTS.CARD_UPDATED, { id: this.card.id });
              eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Card moved to Board', type: 'success', duration: 3000 });
              this.destroy();
            } else {
              eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Move failed', type: 'error', duration: 3000 });
            }
          },
        },
        {
          icon: '📋',
          label: 'Duplicate',
          action: () => this.handleDuplicate(),
        },
        {
          icon: '📋',
          label: 'Copy Card ID',
          action: async () => {
            try {
              await navigator.clipboard.writeText(this.card.id);
              eventBus.emit(EVENTS.TOAST_SHOW, { message: '✅ Card ID copied!', type: 'success', duration: 3000 });
            } catch (err) {
              eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Failed to copy ID', type: 'error', duration: 3000 });
            }
          },
        },
        {
          icon: '✏️',
          label: 'Edit',
          action: () => {
            appState.selectCard(this.card.id);
            eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', cardId: this.card.id });
          },
        },
        {
          icon: '🎯',
          label: 'Focus Mode',
          action: () => {
            eventBus.emit(EVENTS.FOCUS_MODE_ENTER, this.card.id);
          },
        },
        buildSubmenuItem('📤', 'Clone to Project', async (projectId, projectTitle) => {
          await this.handleCloneTo(projectId, projectTitle);
        }),
        buildSubmenuItem('✈️', 'Move to Project', async (projectId, projectTitle) => {
          await this.handleMoveTo(projectId, projectTitle);
        }),
        {
          icon: '📦',
          label: 'Archive',
          action: () => {
            cardService.archive(this.card.id);
            eventBus.emit(EVENTS.TOAST_SHOW, { message: `📦 "${this.card.title}" archived`, type: 'success', duration: 3000 });
          },
        },
        {
          icon: '🗑️',
          label: 'Delete',
          danger: true,
          action: () => {
            if (confirm(`Delete "${this.card.title}"? This is permanent and cannot be undone.`)) {
              cardService.delete(this.card.id);
            }
          },
        },
      ];

      items.forEach((item) => {
        if (item instanceof HTMLElement) {
          menu.appendChild(item);
          return;
        }
        const el = createElement('div', {
          className: `card-context-item${item.danger ? ' card-context-item--danger' : ''}`,
        });
        el.innerHTML = `<span class="card-context-icon">${item.icon}</span><span>${item.label}</span>`;
        el.addEventListener('click', (e) => {
          e.stopPropagation();
          closeMenu();
          item.action();
        });
        menu.appendChild(el);
      });

      document.body.appendChild(menu);
      this.contextMenu = menu;

      // Position: keep within viewport
      const menuW = 180;
      const menuH = items.length * 36 + 8;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      let left = x;
      let top = y;
      if (left + menuW > vw) left = vw - menuW - 8;
      if (top + menuH > vh) top = vh - menuH - 8;
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;

      // Close on outside click or Escape
      const onDocClick = (e: MouseEvent) => {
        if (!menu.contains(e.target as Node)) {
          closeMenu();
          document.removeEventListener('click', onDocClick);
          document.removeEventListener('keydown', onEscape);
        }
      };
      const onEscape = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          closeMenu();
          document.removeEventListener('click', onDocClick);
          document.removeEventListener('keydown', onEscape);
        }
      };
      // Use setTimeout to avoid immediate close from the triggering click
      setTimeout(() => {
        document.addEventListener('click', onDocClick);
        document.addEventListener('keydown', onEscape);
      }, 0);
    };

    // Right-click context menu
    this.element.addEventListener('contextmenu', (e: MouseEvent) => {
      e.preventDefault();
      e.stopPropagation();
      openMenu(e.clientX, e.clientY);
    });

    // The "..." button is appended in render(), and triggers this via a custom event
    this.element.addEventListener('card:menu', (e: Event) => {
      const ce = e as CustomEvent<{ x: number; y: number }>;
      openMenu(ce.detail.x, ce.detail.y);
    });
  }

  private async handleDuplicate(): Promise<void> {
    const newCard = await apiClient.duplicateCard(this.card.id);
    if (newCard) {
      // Add to app state so it shows up in the kanban
      const cards = appState.get('cards') as Card[];
      appState.set('cards', [...cards, newCard]);
      eventBus.emit(EVENTS.CARD_CREATED, newCard);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `📋 Duplicated: "${newCard.title}"`, type: 'success', duration: 3000 });
    } else {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Duplication failed', type: 'error', duration: 3000 });
    }
  }

  private async handleCloneTo(targetProjectId: string, targetProjectTitle: string): Promise<void> {
    const newCard = await apiClient.cloneCardToProject(this.card.id, targetProjectId);
    if (newCard) {
      // Only add to appState if the card belongs to current project view
      const currentProjectId = appState.get('currentProjectId') as string | null;
      if (newCard.projectId === currentProjectId) {
        const cards = appState.get('cards') as Card[];
        appState.set('cards', [...cards, newCard]);
        eventBus.emit(EVENTS.CARD_CREATED, newCard);
      }
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `📤 Cloned to "${targetProjectTitle}"`,
        type: 'success',
        duration: 3000,
      });
    } else {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Clone failed', type: 'error', duration: 3000 });
    }
  }

  private async handleMoveTo(targetProjectId: string, targetProjectTitle: string): Promise<void> {
    const movedCard = await apiClient.moveCardToProject(this.card.id, targetProjectId);
    if (movedCard) {
      // Remove from current project's card list in appState
      const cards = appState.get('cards') as Card[];
      appState.set('cards', cards.filter((c) => c.id !== this.card.id));
      // Destroy this card's DOM element
      this.destroy();
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `✈️ Moved to "${targetProjectTitle}"`,
        type: 'success',
        duration: 3000,
      });
    } else {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Move failed', type: 'error', duration: 3000 });
    }
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
    this.checkboxEl = null;

    // Selection checkbox (visible in select mode)
    const checkboxWrapper = createElement('div', { className: 'card-select-checkbox-wrapper' });
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'card-select-checkbox';
    checkbox.checked = this.selected;
    checkbox.setAttribute('aria-label', `Select card: ${this.card.title}`);
    checkbox.addEventListener('change', (e) => {
      e.stopPropagation();
      this.selected = checkbox.checked;
      this.updateSelectedVisual();
      this.onSelectChange?.(this.card.id, this.selected);
    });
    checkbox.addEventListener('click', (e) => e.stopPropagation());
    checkboxWrapper.addEventListener('click', (e) => e.stopPropagation());
    checkboxWrapper.appendChild(checkbox);
    this.checkboxEl = checkbox;
    this.element.appendChild(checkboxWrapper);

    // Apply select mode visibility
    if (this.selectMode) {
      checkboxWrapper.classList.add('card-select-checkbox-wrapper--visible');
    }

    // Header row: title + actions button
    const headerRow = createElement('div', { className: 'kanban-card-header' });
    const title = createElement('div', { className: 'kanban-card-title' }, this.card.title);
    this.titleEl = title;

    // "..." actions button
    const actionsBtn = createElement('button', {
      className: 'card-actions-btn',
      title: 'Card actions',
    }, '···');
    actionsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const event = new CustomEvent('card:menu', { detail: { x: rect.left, y: rect.bottom + 4 } });
      this.element.dispatchEvent(event);
    });
    headerRow.appendChild(title);
    headerRow.appendChild(actionsBtn);

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
    if (agentType && agentType !== 'general') {
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

    // Removed: vote button — personal workflow, not Jira

    // Assignee avatar badge (bottom-left) — hidden (personal workflow)
    // Removed: assignee avatar badge — personal workflow

    this.element.appendChild(headerRow);
    if (this.card.description) {
      this.element.appendChild(desc);
    }
    this.element.appendChild(footer);

    // Click to edit via inline form (unless in select mode)
    this.element.addEventListener('click', (e) => {
      if (this.selectMode) {
        // In select mode: toggle selection on card click (but not on checkbox itself)
        if ((e.target as HTMLElement).closest('.card-select-checkbox-wrapper')) return;
        this.selected = !this.selected;
        if (this.checkboxEl) this.checkboxEl.checked = this.selected;
        this.updateSelectedVisual();
        this.onSelectChange?.(this.card.id, this.selected);
        return;
      }
      appState.selectCard(this.card.id);
      eventBus.emit(EVENTS.MODAL_OPEN, { type: 'card-detail', cardId: this.card.id });
    });

    this.parentElement.appendChild(this.element);
  }

  private setupDrag(): void {
    this.element.addEventListener('dragstart', (e: DragEvent) => {
      // Prevent drag in select mode
      if (this.selectMode) {
        e.preventDefault();
        return;
      }
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

  private updateSelectedVisual(): void {
    this.element.classList.toggle('selected', this.selected);
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
      ? (this.card.agentType || 'general') === agentFilter
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

  /**
   * Enable or disable multi-select mode.
   * When enabled, the checkbox is visible and drag is disabled.
   */
  setSelectMode(active: boolean): void {
    this.selectMode = active;
    // Update draggable attr
    this.element.setAttribute('draggable', active ? 'false' : 'true');
    // Update checkbox wrapper visibility
    const wrapper = this.element.querySelector('.card-select-checkbox-wrapper');
    if (wrapper) {
      wrapper.classList.toggle('card-select-checkbox-wrapper--visible', active);
    }
    if (!active) {
      // Deselect when exiting select mode
      this.selected = false;
      if (this.checkboxEl) this.checkboxEl.checked = false;
      this.updateSelectedVisual();
    }
    this.element.classList.toggle('kanban-card--select-mode', active);
  }

  /**
   * Set selection state from outside (e.g. clear all).
   */
  setSelected(selected: boolean): void {
    this.selected = selected;
    if (this.checkboxEl) this.checkboxEl.checked = selected;
    this.updateSelectedVisual();
  }

  isSelected(): boolean {
    return this.selected;
  }

  /**
   * Register a callback for when this card's selection changes.
   */
  setOnSelectChange(cb: (id: string, selected: boolean) => void): void {
    this.onSelectChange = cb;
  }

  destroy(): void {
    this.element.remove();
  }
}
