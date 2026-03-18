import { createElement } from '../../utils/helpers';

interface ShortcutEntry {
  keys: string[];
  action: string;
}

interface ShortcutGroup {
  category: string;
  shortcuts: ShortcutEntry[];
}

const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    category: 'Navigation',
    shortcuts: [
      { keys: ['Ctrl', '1'], action: 'Switch to Chat view' },
      { keys: ['Ctrl', '2'], action: 'Switch to Kanban view' },
      { keys: ['Esc'], action: 'Dismiss dialogs / menus' },
    ],
  },
  {
    category: 'Tabs',
    shortcuts: [
      { keys: ['Ctrl', 'T'], action: 'New tab / New project' },
      { keys: ['Ctrl', 'W'], action: 'Close current tab' },
      { keys: ['Ctrl', 'Tab'], action: 'Next tab' },
    ],
  },
  {
    category: 'Chat',
    shortcuts: [
      { keys: ['Ctrl', 'Shift', 'N'], action: 'New session' },
      { keys: ['Enter'], action: 'Send message' },
      { keys: ['Shift', 'Enter'], action: 'New line in message' },
      { keys: ['/'], action: 'Slash commands' },
    ],
  },
  {
    category: 'Help',
    shortcuts: [
      { keys: ['?'], action: 'Show this keyboard shortcuts help' },
    ],
  },
];

export class KeyboardShortcutsModal {
  private overlay: HTMLElement;
  private isVisible = false;
  private boundKeyHandler: (e: KeyboardEvent) => void;
  private boundClickOutside: (e: MouseEvent) => void;

  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'shortcuts-modal-overlay hidden' });
    this.buildModal();
    this.parentElement.appendChild(this.overlay);

    this.boundKeyHandler = this.handleKeyDown.bind(this);
    this.boundClickOutside = this.handleClickOutside.bind(this);

    document.addEventListener('keydown', this.boundKeyHandler);
  }

  private buildModal(): void {
    const modal = createElement('div', { className: 'shortcuts-modal' });

    // Header
    const header = createElement('div', { className: 'shortcuts-modal-header' });
    const title = createElement('h2', { className: 'shortcuts-modal-title' }, '⌨️ Keyboard Shortcuts');
    const closeBtn = createElement('button', { className: 'shortcuts-modal-close' }, '✕');
    closeBtn.setAttribute('aria-label', 'Close shortcuts help');
    closeBtn.addEventListener('click', () => this.hide());
    header.appendChild(title);
    header.appendChild(closeBtn);
    modal.appendChild(header);

    // Shortcut groups
    const body = createElement('div', { className: 'shortcuts-modal-body' });

    for (const group of SHORTCUT_GROUPS) {
      const section = createElement('div', { className: 'shortcuts-section' });
      const categoryLabel = createElement('div', { className: 'shortcuts-category' }, group.category);
      section.appendChild(categoryLabel);

      const table = createElement('table', { className: 'shortcuts-table' });
      const tbody = createElement('tbody');

      for (const entry of group.shortcuts) {
        const tr = createElement('tr');

        const tdKeys = createElement('td', { className: 'shortcuts-keys-cell' });
        const keysWrap = createElement('span', { className: 'shortcuts-keys' });
        entry.keys.forEach((key, i) => {
          if (i > 0) {
            keysWrap.appendChild(createElement('span', { className: 'shortcut-sep' }, '+'));
          }
          keysWrap.appendChild(createElement('kbd', { className: 'shortcut-key' }, key));
        });
        tdKeys.appendChild(keysWrap);

        const tdAction = createElement('td', { className: 'shortcuts-action-cell' }, entry.action);

        tr.appendChild(tdKeys);
        tr.appendChild(tdAction);
        tbody.appendChild(tr);
      }

      table.appendChild(tbody);
      section.appendChild(table);
      body.appendChild(section);
    }

    modal.appendChild(body);

    // Footer hint
    const footer = createElement('div', { className: 'shortcuts-modal-footer' }, 'Press ? or Esc to close');
    modal.appendChild(footer);

    this.overlay.appendChild(modal);
  }

  private handleKeyDown(e: KeyboardEvent): void {
    const target = e.target as HTMLElement;
    const inInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable;

    if (e.key === 'Escape' && this.isVisible) {
      this.hide();
      return;
    }

    // Toggle on '?' — but only when not typing
    if (e.key === '?' && !inInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
      if (this.isVisible) {
        this.hide();
      } else {
        this.show();
      }
    }
  }

  private handleClickOutside(e: MouseEvent): void {
    const modal = this.overlay.querySelector('.shortcuts-modal');
    if (modal && !modal.contains(e.target as Node)) {
      this.hide();
    }
  }

  show(): void {
    this.isVisible = true;
    this.overlay.classList.remove('hidden');
    // Attach click-outside after a tick to avoid immediate close
    setTimeout(() => {
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
    this.overlay.remove();
  }
}
