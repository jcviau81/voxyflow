import { useCallback, useEffect, useRef } from 'react';
import { darkTheme, lightTheme } from 'picmo';
import { createPopup, type PopupPickerController } from '@picmo/popup-picker';
import { useThemeStore } from '../../stores/useThemeStore';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface EmojiPickerProps {
  onSelect: (emoji: string) => void;
}

// ---------------------------------------------------------------------------
// Component — renders the trigger button; PicMo popup is imperative
// ---------------------------------------------------------------------------

export function EmojiPicker({ onSelect }: EmojiPickerProps) {
  const btnRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<PopupPickerController | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // Create popup once, re-create only when theme changes
  useEffect(() => {
    const btn = btnRef.current;
    if (!btn) return;

    const isDark = theme === 'dark';
    const popup = createPopup(
      {
        theme: isDark ? darkTheme : lightTheme,
        showPreview: false,
        emojisPerRow: 8,
        visibleRows: 5,
      },
      {
        referenceElement: btn,
        triggerElement: btn,
        position: 'top-start',
        className: 'voxyflow-emoji-popup',
      },
    );

    popup.addEventListener('emoji:select', (selection: { emoji: string }) => {
      onSelect(selection.emoji);
    });

    popupRef.current = popup;

    return () => {
      popup.destroy();
      popupRef.current = null;
    };
  }, [theme, onSelect]);

  const toggle = useCallback(() => {
    popupRef.current?.toggle();
  }, []);

  return (
    <button
      ref={btnRef}
      type="button"
      className="emoji-picker-btn flex items-center justify-center w-8 h-8 rounded hover:bg-accent transition-colors text-lg"
      title="Emoji picker"
      onClick={toggle}
    >
      😀
    </button>
  );
}
