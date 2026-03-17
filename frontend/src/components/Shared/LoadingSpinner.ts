import { createElement } from '../../utils/helpers';

export class LoadingSpinner {
  private element: HTMLElement;

  constructor(private parentElement: HTMLElement, private size: 'small' | 'medium' | 'large' = 'medium') {
    this.element = createElement('div', { className: `spinner spinner-${size}` });
    this.render();
  }

  render(): void {
    this.element.innerHTML = '';
    const dots = createElement('div', { className: 'spinner-dots' });
    for (let i = 0; i < 3; i++) {
      dots.appendChild(createElement('span', { className: 'spinner-dot' }));
    }
    this.element.appendChild(dots);
    this.parentElement.appendChild(this.element);
  }

  show(): void {
    this.element.classList.remove('hidden');
  }

  hide(): void {
    this.element.classList.add('hidden');
  }

  destroy(): void {
    this.element.remove();
  }
}
