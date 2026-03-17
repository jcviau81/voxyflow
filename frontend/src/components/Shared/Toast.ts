import { ToastOptions } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, TOAST_DURATION } from '../../utils/constants';
import { createElement, cn } from '../../utils/helpers';

export class Toast {
  private container: HTMLElement;
  private toasts: Map<number, HTMLElement> = new Map();
  private counter = 0;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'toast-container' });
    this.parentElement.appendChild(this.container);
    this.setupListeners();
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.TOAST_SHOW, (options: unknown) => {
        this.show(options as ToastOptions);
      })
    );
  }

  show(options: ToastOptions): void {
    const id = ++this.counter;
    const duration = options.duration || TOAST_DURATION;

    const toast = createElement('div', {
      className: cn('toast', `toast-${options.type}`),
    });

    const content = createElement('div', { className: 'toast-content' });

    // Icon
    const icons: Record<string, string> = {
      info: 'ℹ️',
      success: '✅',
      warning: '⚠️',
      error: '❌',
    };
    const icon = createElement('span', { className: 'toast-icon' }, icons[options.type] || 'ℹ️');

    // Message
    const message = createElement('span', { className: 'toast-message' }, options.message);

    content.appendChild(icon);
    content.appendChild(message);

    // Action button
    if (options.action) {
      const actionBtn = createElement(
        'button',
        { className: 'toast-action' },
        options.action.label
      );
      actionBtn.addEventListener('click', () => {
        options.action!.callback();
        this.dismiss(id);
      });
      content.appendChild(actionBtn);
    }

    // Close button
    const closeBtn = createElement('button', { className: 'toast-close' }, '✕');
    closeBtn.addEventListener('click', () => this.dismiss(id));

    toast.appendChild(content);
    toast.appendChild(closeBtn);

    // Animate in
    toast.style.animation = 'toast-in 0.3s ease';

    this.container.appendChild(toast);
    this.toasts.set(id, toast);

    // Auto dismiss
    setTimeout(() => this.dismiss(id), duration);
  }

  private dismiss(id: number): void {
    const toast = this.toasts.get(id);
    if (!toast) return;

    toast.style.animation = 'toast-out 0.3s ease';
    setTimeout(() => {
      toast.remove();
      this.toasts.delete(id);
    }, 300);
  }

  update(): void {
    // No-op
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.toasts.clear();
    this.container.remove();
  }
}
