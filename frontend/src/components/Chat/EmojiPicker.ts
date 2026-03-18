/**
 * Lightweight Emoji Picker — no heavy libraries
 */
import { createElement } from '../../utils/helpers';

interface EmojiCategory {
  name: string;
  icon: string;
  emojis: EmojiItem[];
}

interface EmojiItem {
  emoji: string;
  name: string;
}

const EMOJI_CATEGORIES: EmojiCategory[] = [
  {
    name: 'Smileys',
    icon: '😀',
    emojis: [
      { emoji: '😀', name: 'grinning' },
      { emoji: '😃', name: 'smiley' },
      { emoji: '😄', name: 'smile' },
      { emoji: '😁', name: 'grin' },
      { emoji: '😂', name: 'joy' },
      { emoji: '🤣', name: 'rofl' },
      { emoji: '😊', name: 'blush' },
      { emoji: '😇', name: 'innocent' },
      { emoji: '😉', name: 'wink' },
      { emoji: '😍', name: 'heart_eyes' },
      { emoji: '🥰', name: 'smiling_hearts' },
      { emoji: '😘', name: 'kissing_heart' },
      { emoji: '😋', name: 'yum' },
      { emoji: '😎', name: 'sunglasses' },
      { emoji: '🤔', name: 'thinking' },
      { emoji: '🤗', name: 'hugging' },
      { emoji: '😏', name: 'smirk' },
      { emoji: '😌', name: 'relieved' },
      { emoji: '😴', name: 'sleeping' },
      { emoji: '🤤', name: 'drool' },
      { emoji: '😜', name: 'stuck_out_tongue_winking' },
      { emoji: '🤪', name: 'zany' },
      { emoji: '😳', name: 'flushed' },
      { emoji: '🥺', name: 'pleading' },
      { emoji: '😢', name: 'cry' },
      { emoji: '😭', name: 'sob' },
      { emoji: '😤', name: 'triumph' },
      { emoji: '😡', name: 'rage' },
      { emoji: '🤯', name: 'exploding_head' },
      { emoji: '😱', name: 'scream' },
    ],
  },
  {
    name: 'Gestures',
    icon: '👍',
    emojis: [
      { emoji: '👍', name: 'thumbsup' },
      { emoji: '👎', name: 'thumbsdown' },
      { emoji: '👏', name: 'clap' },
      { emoji: '🙌', name: 'raised_hands' },
      { emoji: '🤝', name: 'handshake' },
      { emoji: '🙏', name: 'pray' },
      { emoji: '💪', name: 'muscle' },
      { emoji: '👋', name: 'wave' },
      { emoji: '✌️', name: 'peace' },
      { emoji: '🤘', name: 'metal' },
      { emoji: '👌', name: 'ok_hand' },
      { emoji: '🤞', name: 'crossed_fingers' },
      { emoji: '☝️', name: 'point_up' },
      { emoji: '👀', name: 'eyes' },
      { emoji: '🧠', name: 'brain' },
    ],
  },
  {
    name: 'Hearts & Symbols',
    icon: '❤️',
    emojis: [
      { emoji: '❤️', name: 'heart' },
      { emoji: '🧡', name: 'orange_heart' },
      { emoji: '💛', name: 'yellow_heart' },
      { emoji: '💚', name: 'green_heart' },
      { emoji: '💙', name: 'blue_heart' },
      { emoji: '💜', name: 'purple_heart' },
      { emoji: '🖤', name: 'black_heart' },
      { emoji: '💕', name: 'two_hearts' },
      { emoji: '💯', name: '100' },
      { emoji: '✅', name: 'check' },
      { emoji: '❌', name: 'x' },
      { emoji: '⚠️', name: 'warning' },
      { emoji: '💡', name: 'bulb' },
      { emoji: '⭐', name: 'star' },
      { emoji: '✨', name: 'sparkles' },
    ],
  },
  {
    name: 'Objects',
    icon: '🔥',
    emojis: [
      { emoji: '🔥', name: 'fire' },
      { emoji: '⚡', name: 'zap' },
      { emoji: '🚀', name: 'rocket' },
      { emoji: '🎉', name: 'tada' },
      { emoji: '🎯', name: 'dart' },
      { emoji: '🏆', name: 'trophy' },
      { emoji: '💎', name: 'gem' },
      { emoji: '👑', name: 'crown' },
      { emoji: '💰', name: 'money_bag' },
      { emoji: '💻', name: 'computer' },
      { emoji: '📱', name: 'phone' },
      { emoji: '⚙️', name: 'gear' },
      { emoji: '🔧', name: 'wrench' },
      { emoji: '🔗', name: 'link' },
      { emoji: '🔒', name: 'lock' },
      { emoji: '🔑', name: 'key' },
      { emoji: '📌', name: 'pin' },
      { emoji: '📝', name: 'memo' },
      { emoji: '📖', name: 'book' },
      { emoji: '☕', name: 'coffee' },
      { emoji: '🍕', name: 'pizza' },
      { emoji: '🍺', name: 'beer' },
      { emoji: '🎂', name: 'cake' },
    ],
  },
  {
    name: 'Animals',
    icon: '🐱',
    emojis: [
      { emoji: '🐱', name: 'cat' },
      { emoji: '🐶', name: 'dog' },
      { emoji: '🦄', name: 'unicorn' },
      { emoji: '🐍', name: 'snake' },
      { emoji: '🐻', name: 'bear' },
      { emoji: '🦊', name: 'fox' },
      { emoji: '🐙', name: 'octopus' },
      { emoji: '🦋', name: 'butterfly' },
      { emoji: '🤖', name: 'robot' },
      { emoji: '👻', name: 'ghost' },
      { emoji: '👽', name: 'alien' },
      { emoji: '💀', name: 'skull' },
    ],
  },
];

export class EmojiPicker {
  private panel: HTMLElement;
  private isOpen = false;
  private onSelect: (emoji: string) => void;
  private closeHandler: (e: MouseEvent) => void;

  constructor(
    private parentElement: HTMLElement,
    onSelect: (emoji: string) => void
  ) {
    this.onSelect = onSelect;
    this.panel = createElement('div', { className: 'emoji-picker-panel' });
    this.panel.style.display = 'none';

    this.buildPanel();
    this.parentElement.appendChild(this.panel);

    // Close on outside click
    this.closeHandler = (e: MouseEvent) => {
      if (this.isOpen && !this.panel.contains(e.target as Node) &&
          !(e.target as HTMLElement).closest('.emoji-picker-btn')) {
        this.close();
      }
    };
    document.addEventListener('click', this.closeHandler);
  }

  private buildPanel(): void {
    // Search bar
    const searchInput = createElement('input', {
      className: 'emoji-search',
      type: 'text',
      placeholder: 'Search emoji...',
    }) as HTMLInputElement;
    searchInput.addEventListener('input', () => this.filterEmojis(searchInput.value));
    this.panel.appendChild(searchInput);

    // Category tabs
    const tabs = createElement('div', { className: 'emoji-tabs' });
    EMOJI_CATEGORIES.forEach((cat, idx) => {
      const tab = createElement('button', {
        className: `emoji-tab${idx === 0 ? ' active' : ''}`,
        'data-category': idx.toString(),
      }, cat.icon);
      tab.title = cat.name;
      tab.addEventListener('click', () => this.showCategory(idx));
      tabs.appendChild(tab);
    });
    this.panel.appendChild(tabs);

    // Grid container
    const gridContainer = createElement('div', { className: 'emoji-grid-container' });
    EMOJI_CATEGORIES.forEach((cat, idx) => {
      const section = createElement('div', {
        className: `emoji-section${idx === 0 ? '' : ' hidden'}`,
        'data-section': idx.toString(),
      });
      const label = createElement('div', { className: 'emoji-section-label' }, cat.name);
      section.appendChild(label);

      const grid = createElement('div', { className: 'emoji-grid' });
      cat.emojis.forEach((item) => {
        const btn = createElement('button', {
          className: 'emoji-item',
        }, item.emoji);
        btn.title = `:${item.name}:`;
        btn.addEventListener('click', () => {
          this.onSelect(item.emoji);
          this.close();
        });
        grid.appendChild(btn);
      });
      section.appendChild(grid);
      gridContainer.appendChild(section);
    });
    this.panel.appendChild(gridContainer);
  }

  private showCategory(index: number): void {
    // Update tabs
    this.panel.querySelectorAll('.emoji-tab').forEach((tab, i) => {
      tab.classList.toggle('active', i === index);
    });
    // Show/hide sections
    this.panel.querySelectorAll('.emoji-section').forEach((sec, i) => {
      sec.classList.toggle('hidden', i !== index);
    });
  }

  private filterEmojis(query: string): void {
    const q = query.toLowerCase().trim();
    if (!q) {
      // Show all, reset to first tab
      this.panel.querySelectorAll('.emoji-section').forEach((sec, i) => {
        sec.classList.toggle('hidden', i !== 0);
      });
      this.panel.querySelectorAll('.emoji-tab').forEach((tab, i) => {
        tab.classList.toggle('active', i === 0);
      });
      return;
    }

    // Show all sections, filter items
    this.panel.querySelectorAll('.emoji-section').forEach((sec) => {
      sec.classList.remove('hidden');
      const items = sec.querySelectorAll('.emoji-item');
      let hasVisible = false;
      items.forEach((item) => {
        const name = (item as HTMLElement).title.toLowerCase();
        const match = name.includes(q);
        (item as HTMLElement).style.display = match ? '' : 'none';
        if (match) hasVisible = true;
      });
      (sec as HTMLElement).style.display = hasVisible ? '' : 'none';
    });
    // Deactivate all tabs during search
    this.panel.querySelectorAll('.emoji-tab').forEach((tab) => {
      tab.classList.remove('active');
    });
  }

  toggle(): void {
    if (this.isOpen) {
      this.close();
    } else {
      this.open();
    }
  }

  open(): void {
    this.isOpen = true;
    this.panel.style.display = 'flex';
    const input = this.panel.querySelector('.emoji-search') as HTMLInputElement;
    if (input) {
      input.value = '';
      this.filterEmojis('');
    }
  }

  close(): void {
    this.isOpen = false;
    this.panel.style.display = 'none';
  }

  destroy(): void {
    document.removeEventListener('click', this.closeHandler);
    this.panel.remove();
  }
}
