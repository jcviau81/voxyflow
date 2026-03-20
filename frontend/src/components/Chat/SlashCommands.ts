export interface SlashCommand {
  name: string;
  args?: string;
  description: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: '/new',     description: 'Start a new session (clear chat history)' },
  { name: '/clear',   description: 'Clear chat messages visually' },
  { name: '/help',    description: 'Show available commands' },
  {
    name: '/agent',
    args: '[name]',
    description: 'Switch agent persona: ember, coder, architect, researcher, designer, writer, qa',
  },
  // Hidden until implemented:
  // { name: '/standup', description: 'Generate a daily standup summary for the current project' },
  {
    name: '/meeting',
    description: 'Import meeting notes and extract action items as cards',
  },
];

export class SlashCommandMenu {
  private el: HTMLElement;
  private items: SlashCommand[] = [];
  private activeIndex = 0;
  private onSelect: (cmd: SlashCommand) => void;
  private visible = false;

  constructor(
    private anchor: HTMLElement,
    onSelect: (cmd: SlashCommand) => void
  ) {
    this.onSelect = onSelect;
    this.el = document.createElement('div');
    this.el.className = 'slash-menu';
    this.el.setAttribute('role', 'listbox');
    this.el.style.display = 'none';
    // Append directly inside the anchor (chat-input-area) which has position:relative
    anchor.appendChild(this.el);
  }

  /** Update filter based on current input value. */
  update(query: string): void {
    if (!query.startsWith('/')) {
      this.hide();
      return;
    }

    const lower = query.toLowerCase();
    this.items = SLASH_COMMANDS.filter((c) => c.name.startsWith(lower));

    this.activeIndex = 0;
    this.render();
    this.show();
  }

  private render(): void {
    this.el.innerHTML = '';

    if (this.items.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'slash-menu-empty';
      empty.textContent = 'No commands match';
      this.el.appendChild(empty);
      return;
    }

    this.items.forEach((cmd, i) => {
      const row = document.createElement('div');
      row.className = `slash-menu-item${i === this.activeIndex ? ' active' : ''}`;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', String(i === this.activeIndex));

      const nameSpan = document.createElement('span');
      nameSpan.className = 'slash-menu-item-name';
      nameSpan.textContent = cmd.args ? `${cmd.name} ${cmd.args}` : cmd.name;

      const descSpan = document.createElement('span');
      descSpan.className = 'slash-menu-item-desc';
      descSpan.textContent = cmd.description;

      row.appendChild(nameSpan);
      row.appendChild(descSpan);

      row.addEventListener('mousedown', (e) => {
        e.preventDefault(); // prevent input blur
        this.selectItem(i);
      });

      this.el.appendChild(row);
    });
  }

  /**
   * Handle keyboard events from the input.
   * Returns true if the event was consumed (caller should preventDefault).
   */
  handleKey(e: KeyboardEvent): boolean {
    if (!this.visible) return false;

    if (e.key === 'ArrowDown') {
      this.activeIndex = (this.activeIndex + 1) % Math.max(this.items.length, 1);
      this.render();
      return true;
    }
    if (e.key === 'ArrowUp') {
      this.activeIndex =
        (this.activeIndex - 1 + Math.max(this.items.length, 1)) % Math.max(this.items.length, 1);
      this.render();
      return true;
    }
    if (e.key === 'Enter' && this.items.length > 0) {
      this.selectItem(this.activeIndex);
      return true;
    }
    if (e.key === 'Escape') {
      this.hide();
      return true;
    }
    return false;
  }

  private selectItem(index: number): void {
    const cmd = this.items[index];
    if (cmd) {
      this.hide();
      this.onSelect(cmd);
    }
  }

  show(): void {
    this.el.style.display = 'block';
    this.visible = true;
  }

  hide(): void {
    this.el.style.display = 'none';
    this.visible = false;
  }

  isVisible(): boolean {
    return this.visible;
  }

  destroy(): void {
    this.el.remove();
  }
}
