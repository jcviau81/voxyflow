import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { Tab } from '../../types';

interface PaletteAction {
  id: string;
  label: string;
  icon: string;
  shortcut?: string;
  category: string;
  action: () => void;
}

function fuzzyMatch(query: string, label: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const l = label.toLowerCase();
  let qi = 0;
  for (let i = 0; i < l.length && qi < q.length; i++) {
    if (l[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

export class CommandPalette {
  private overlay: HTMLElement;
  private input: HTMLInputElement;
  private resultsList: HTMLElement;
  private emptyMessage: HTMLElement;
  private isVisible = false;
  private activeIndex = 0;
  private filteredActions: PaletteAction[] = [];
  private boundKeyHandler: (e: KeyboardEvent) => void;
  private boundClickOutside: (e: MouseEvent) => void;
  private unsubscribeTabs: (() => void) | null = null;
  private shortcutsModalShow: (() => void) | null = null;

  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'command-palette-overlay hidden' });
    this.input = createElement('input', {
      className: 'command-palette-input',
      placeholder: 'Search actions…',
      type: 'text',
    }) as HTMLInputElement;
    this.resultsList = createElement('ul', { className: 'command-palette-results' });
    this.emptyMessage = createElement('div', { className: 'command-palette-empty' }, 'No results');

    this.buildOverlay();
    this.parentElement.appendChild(this.overlay);

    this.boundKeyHandler = this.handleKeyDown.bind(this);
    this.boundClickOutside = this.handleClickOutside.bind(this);

    document.addEventListener('keydown', this.boundKeyHandler);

    // Re-render dynamic project actions when tabs change
    this.unsubscribeTabs = eventBus.on(EVENTS.TAB_SWITCH, () => {
      if (this.isVisible) this.renderResults(this.input.value);
    }) as unknown as (() => void);

    const tabOpen = eventBus.on(EVENTS.TAB_OPEN, () => {
      if (this.isVisible) this.renderResults(this.input.value);
    });
    const tabClose = eventBus.on(EVENTS.TAB_CLOSE, () => {
      if (this.isVisible) this.renderResults(this.input.value);
    });

    // Keep unsub references
    this._extraUnsubs = [tabOpen as unknown as (() => void), tabClose as unknown as (() => void)];
  }

  private _extraUnsubs: (() => void)[] = [];

  /** Allow the App to pass in a callback to open the shortcuts modal */
  setShortcutsModalCallback(fn: () => void): void {
    this.shortcutsModalShow = fn;
  }

  private buildOverlay(): void {
    const modal = createElement('div', { className: 'command-palette' });

    // Search input wrapper
    const inputWrapper = createElement('div', { className: 'command-palette-input-wrapper' });
    const searchIcon = createElement('span', { className: 'command-palette-search-icon' }, '🔍');
    inputWrapper.appendChild(searchIcon);
    inputWrapper.appendChild(this.input);
    modal.appendChild(inputWrapper);

    // Results
    modal.appendChild(this.resultsList);
    modal.appendChild(this.emptyMessage);

    // Footer hint
    const footer = createElement('div', { className: 'command-palette-footer' });
    footer.innerHTML =
      '<span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>' +
      '<span><kbd>Enter</kbd> select</span>' +
      '<span><kbd>Esc</kbd> close</span>';
    modal.appendChild(footer);

    this.overlay.appendChild(modal);

    // Input listener
    this.input.addEventListener('input', () => {
      this.activeIndex = 0;
      this.renderResults(this.input.value);
    });
  }

  private getStaticActions(): PaletteAction[] {
    return [
      // Navigation
      {
        id: 'nav-chat',
        label: 'Go to Chat',
        icon: '💬',
        shortcut: 'Ctrl+1',
        category: 'Navigation',
        action: () => appState.setView('chat'),
      },
      {
        id: 'nav-kanban',
        label: 'Go to Kanban',
        icon: '📋',
        shortcut: 'Ctrl+2',
        category: 'Navigation',
        action: () => appState.setView('kanban'),
      },
      {
        id: 'nav-board',
        label: 'Go to FreeBoard',
        icon: '📝',
        category: 'Navigation',
        action: () => appState.setView('freeboard'),
      },
      {
        id: 'nav-settings',
        label: 'Open Settings',
        icon: '⚙️',
        category: 'Navigation',
        action: () => appState.setView('settings'),
      },
      // Actions
      {
        id: 'new-project',
        label: 'New Project',
        icon: '➕',
        category: 'Actions',
        action: () => eventBus.emit(EVENTS.PROJECT_FORM_SHOW, { mode: 'create' }),
      },
      {
        id: 'new-session',
        label: 'New Session',
        icon: '🔄',
        category: 'Actions',
        action: () => eventBus.emit(EVENTS.SESSION_NEW, undefined),
      },
      {
        id: 'new-card',
        label: 'New Card',
        icon: '🃏',
        category: 'Actions',
        action: () => eventBus.emit(EVENTS.CARD_FORM_SHOW, { mode: 'create' }),
      },
      {
        id: 'theme-toggle',
        label: 'Toggle Theme',
        icon: '🌙',
        category: 'Actions',
        action: () => {
          const current = appState.get('theme');
          appState.setTheme(current === 'dark' ? 'light' : 'dark');
        },
      },
      {
        id: 'shortcuts',
        label: 'Keyboard Shortcuts',
        icon: '⌨️',
        category: 'Help',
        action: () => {
          if (this.shortcutsModalShow) this.shortcutsModalShow();
        },
      },
    ];
  }

  private getDynamicProjectActions(): PaletteAction[] {
    const tabs: Tab[] = appState.getOpenTabs();
    return tabs
      .filter((tab) => tab.id !== 'main')
      .map((tab) => ({
        id: `switch-tab-${tab.id}`,
        label: `Switch to ${tab.label}`,
        icon: tab.emoji || '📁',
        category: 'Projects',
        action: () => appState.switchTab(tab.id),
      }));
  }

  private getAllActions(): PaletteAction[] {
    return [...this.getStaticActions(), ...this.getDynamicProjectActions()];
  }

  private renderResults(query: string): void {
    const all = this.getAllActions();
    this.filteredActions = all.filter((a) => fuzzyMatch(query, a.label));

    this.resultsList.innerHTML = '';

    if (this.filteredActions.length === 0) {
      this.resultsList.classList.add('hidden');
      this.emptyMessage.classList.remove('hidden');
      return;
    }

    this.resultsList.classList.remove('hidden');
    this.emptyMessage.classList.add('hidden');

    this.filteredActions.forEach((action, idx) => {
      const li = createElement('li', {
        className: `command-palette-item${idx === this.activeIndex ? ' active' : ''}`,
      });
      li.setAttribute('data-index', String(idx));

      const iconEl = createElement('span', { className: 'command-palette-item-icon' }, action.icon);
      const labelEl = createElement('span', { className: 'command-palette-item-label' }, action.label);

      li.appendChild(iconEl);
      li.appendChild(labelEl);

      if (action.shortcut) {
        const shortcutEl = createElement('span', { className: 'command-palette-item-shortcut' }, action.shortcut);
        li.appendChild(shortcutEl);
      }

      if (action.category) {
        const categoryEl = createElement('span', { className: 'command-palette-item-category' }, action.category);
        li.appendChild(categoryEl);
      }

      li.addEventListener('mouseenter', () => {
        this.activeIndex = idx;
        this.updateActiveItem();
      });

      li.addEventListener('click', () => {
        this.executeAction(action);
      });

      this.resultsList.appendChild(li);
    });

    this.scrollActiveIntoView();
  }

  private updateActiveItem(): void {
    const items = this.resultsList.querySelectorAll('.command-palette-item');
    items.forEach((item, idx) => {
      item.classList.toggle('active', idx === this.activeIndex);
    });
    this.scrollActiveIntoView();
  }

  private scrollActiveIntoView(): void {
    const activeEl = this.resultsList.querySelector('.command-palette-item.active');
    if (activeEl) {
      activeEl.scrollIntoView({ block: 'nearest' });
    }
  }

  private executeAction(action: PaletteAction): void {
    this.hide();
    action.action();
  }

  private handleKeyDown(e: KeyboardEvent): void {
    const target = e.target as HTMLElement;
    const inInput =
      (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) &&
      target !== this.input;

    // Open on Ctrl+K / Cmd+K — skip if in a text input (but allow from our own input)
    if ((e.ctrlKey || e.metaKey) && e.key === 'k' && !inInput) {
      e.preventDefault();
      if (this.isVisible) {
        this.hide();
      } else {
        this.show();
      }
      return;
    }

    if (!this.isVisible) return;

    switch (e.key) {
      case 'Escape':
        e.preventDefault();
        this.hide();
        break;

      case 'ArrowDown':
        e.preventDefault();
        if (this.filteredActions.length > 0) {
          this.activeIndex = (this.activeIndex + 1) % this.filteredActions.length;
          this.updateActiveItem();
        }
        break;

      case 'ArrowUp':
        e.preventDefault();
        if (this.filteredActions.length > 0) {
          this.activeIndex =
            (this.activeIndex - 1 + this.filteredActions.length) % this.filteredActions.length;
          this.updateActiveItem();
        }
        break;

      case 'Enter':
        e.preventDefault();
        if (this.filteredActions[this.activeIndex]) {
          this.executeAction(this.filteredActions[this.activeIndex]);
        }
        break;
    }
  }

  private handleClickOutside(e: MouseEvent): void {
    const modal = this.overlay.querySelector('.command-palette');
    if (modal && !modal.contains(e.target as Node)) {
      this.hide();
    }
  }

  show(): void {
    this.isVisible = true;
    this.activeIndex = 0;
    this.input.value = '';
    this.overlay.classList.remove('hidden');
    this.renderResults('');
    setTimeout(() => {
      this.input.focus();
      this.overlay.addEventListener('click', this.boundClickOutside);
    }, 0);
  }

  hide(): void {
    this.isVisible = false;
    this.overlay.classList.add('hidden');
    this.overlay.removeEventListener('click', this.boundClickOutside);
  }

  destroy(): void {
    document.removeEventListener('keydown', this.boundKeyHandler);
    this.overlay.removeEventListener('click', this.boundClickOutside);
    if (this.unsubscribeTabs) this.unsubscribeTabs();
    this._extraUnsubs.forEach((fn) => fn());
    this.overlay.remove();
  }
}
