/**
 * Emoji Picker — powered by PicMo (popup mode)
 */
import { darkTheme, lightTheme } from 'picmo';
import { createPopup, PopupPickerController } from '@picmo/popup-picker';

export class EmojiPicker {
  private popup: PopupPickerController;

  constructor(
    private parentElement: HTMLElement,
    onSelect: (emoji: string) => void
  ) {
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    this.popup = createPopup(
      {
        theme: isDark ? darkTheme : lightTheme,
        showPreview: false,
        emojisPerRow: 8,
        visibleRows: 5,
      },
      {
        referenceElement: this.parentElement,
        triggerElement: this.parentElement,
        position: 'top-start',
        className: 'voxyflow-emoji-popup',
      }
    );

    this.popup.addEventListener('emoji:select', (selection: { emoji: string }) => {
      onSelect(selection.emoji);
    });
  }

  toggle(): void {
    this.popup.toggle();
  }

  open(): void {
    this.popup.open();
  }

  close(): void {
    this.popup.close();
  }

  destroy(): void {
    this.popup.destroy();
  }
}
