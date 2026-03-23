import { createElement } from '../../utils/helpers';

interface ConfirmDialogOptions {
  title: string;
  body: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

/**
 * Lightweight confirmation overlay dialog.
 * Returns a Promise that resolves to true (confirm) or false (cancel).
 */
export function showConfirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const overlay = createElement('div', { className: 'confirm-dialog-overlay' });
    const dialog = createElement('div', { className: 'confirm-dialog' });

    const title = createElement('div', { className: 'confirm-dialog-title' }, options.title);
    const body = createElement('div', { className: 'confirm-dialog-body' }, options.body);

    const actions = createElement('div', { className: 'confirm-dialog-actions' });

    const cancelBtn = createElement('button', {
      className: 'confirm-dialog-btn confirm-dialog-btn--cancel',
    }, options.cancelLabel || 'Cancel');

    const confirmBtn = createElement('button', {
      className: `confirm-dialog-btn confirm-dialog-btn--confirm${options.danger ? ' confirm-dialog-btn--danger' : ''}`,
    }, options.confirmLabel || 'Confirm');

    const close = (result: boolean) => {
      overlay.remove();
      resolve(result);
    };

    cancelBtn.addEventListener('click', () => close(false));
    confirmBtn.addEventListener('click', () => close(true));
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) close(false);
    });

    // Escape key to cancel
    const onKeydown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        document.removeEventListener('keydown', onKeydown);
        close(false);
      }
    };
    document.addEventListener('keydown', onKeydown);

    actions.appendChild(cancelBtn);
    actions.appendChild(confirmBtn);
    dialog.appendChild(title);
    dialog.appendChild(body);
    dialog.appendChild(actions);
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    // Auto-focus confirm button
    confirmBtn.focus();
  });
}
