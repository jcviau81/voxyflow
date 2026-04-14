import { useCallback, useMemo, useState } from 'react';
import { cn } from '../../lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SlashCommand {
  name: string;
  args?: string;
  description: string;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: '/new', description: 'Start a new session (clear chat history)' },
  { name: '/clear', description: 'Clear chat messages visually' },
  { name: '/help', description: 'Show available commands' },
  {
    name: '/agent',
    args: '[name]',
    description: 'Switch agent persona: general, coder, architect, researcher, designer, writer, qa',
  },
  { name: '/meeting', description: 'Import meeting notes and extract action items as cards' },
];

// ---------------------------------------------------------------------------
// Hook — returns render element + imperative controls
// ---------------------------------------------------------------------------

export interface SlashMenuControls {
  element: React.ReactNode;
  /** Update filter from current input value. Returns true if menu is visible. */
  update: (query: string) => boolean;
  /** Handle keyboard event. Returns true if consumed. */
  handleKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => boolean;
  /** Whether the menu is currently visible */
  visible: boolean;
  /** Hide the menu */
  hide: () => void;
}

export function useSlashMenu(onSelect: (cmd: SlashCommand) => void): SlashMenuControls {
  const [query, setQuery] = useState('');
  const [isVisible, setIsVisible] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);

  const items = useMemo(() => {
    if (!query.startsWith('/')) return [];
    const lower = query.toLowerCase();
    return SLASH_COMMANDS.filter((c) => c.name.startsWith(lower));
  }, [query]);

  const hide = useCallback(() => {
    setIsVisible(false);
    setQuery('');
    setActiveIndex(0);
  }, []);

  const selectItem = useCallback(
    (index: number) => {
      const cmd = items[index];
      if (cmd) {
        hide();
        onSelect(cmd);
      }
    },
    [items, hide, onSelect],
  );

  const update = useCallback(
    (value: string): boolean => {
      if (!value.startsWith('/')) {
        if (isVisible) hide();
        return false;
      }
      setQuery(value);
      setActiveIndex(0);
      setIsVisible(true);
      return true;
    },
    [isVisible, hide],
  );

  const handleKey = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
      if (!isVisible) return false;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActiveIndex((prev) => (prev + 1) % Math.max(items.length, 1));
        return true;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActiveIndex((prev) => (prev - 1 + Math.max(items.length, 1)) % Math.max(items.length, 1));
        return true;
      }
      if (e.key === 'Enter' && items.length > 0) {
        e.preventDefault();
        selectItem(activeIndex);
        return true;
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        hide();
        return true;
      }
      return false;
    },
    [isVisible, items.length, activeIndex, selectItem, hide],
  );

  const element = isVisible ? (
    <div className="slash-menu absolute bottom-full left-0 w-full mb-1 bg-popover border border-border rounded-lg shadow-lg z-20 overflow-hidden" role="listbox">
      {items.length === 0 ? (
        <div className="slash-menu-empty px-3 py-2 text-sm text-muted-foreground">
          No commands match
        </div>
      ) : (
        items.map((cmd, i) => (
          <div
            key={cmd.name}
            role="option"
            aria-selected={i === activeIndex}
            className={cn(
              'slash-menu-item flex items-center gap-3 px-3 py-2 cursor-pointer text-sm',
              i === activeIndex ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50',
            )}
            onMouseDown={(e) => {
              e.preventDefault(); // prevent textarea blur
              selectItem(i);
            }}
          >
            <span className="slash-menu-item-name font-mono font-medium">
              {cmd.args ? `${cmd.name} ${cmd.args}` : cmd.name}
            </span>
            <span className="slash-menu-item-desc text-muted-foreground">{cmd.description}</span>
          </div>
        ))
      )}
    </div>
  ) : null;

  return { element, update, handleKey, visible: isVisible, hide };
}
