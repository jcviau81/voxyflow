import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';

export class TopBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];
  private opportunitiesCount: number = 0;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('header', { className: 'top-bar' });
    this.render();
    this.setupListeners();
  }

  render(): void {
    this.container.innerHTML = '';

    // Menu toggle (mobile)
    const menuBtn = createElement('button', { className: 'top-bar-menu-btn' }, '☰');
    menuBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.SIDEBAR_TOGGLE);
    });

    // Voice indicator
    const voiceIndicator = createElement('div', {
      className: `top-bar-voice ${appState.get('voiceActive') ? 'active' : ''}`,
    });
    const voiceDot = createElement('span', { className: 'voice-dot' });
    const voiceLabel = createElement('span', {}, appState.get('voiceActive') ? 'Listening...' : '');
    voiceIndicator.appendChild(voiceDot);
    voiceIndicator.appendChild(voiceLabel);

    // Opportunities toggle (mobile only)
    const oppToggle = createElement('button', {
      className: 'top-bar-opp-toggle',
      'data-testid': 'opportunities-toggle',
    });
    oppToggle.innerHTML = `💡${this.opportunitiesCount > 0 ? `<span class="opp-toggle-badge">${this.opportunitiesCount}</span>` : ''}`;
    oppToggle.addEventListener('click', () => {
      eventBus.emit(EVENTS.OPPORTUNITIES_TOGGLE);
    });

    this.container.appendChild(menuBtn);
    this.container.appendChild(voiceIndicator);
    this.container.appendChild(oppToggle);

    this.parentElement.appendChild(this.container);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      appState.subscribe('voiceActive', () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_COUNT, (count: unknown) => {
        this.opportunitiesCount = count as number;
        this.render();
      })
    );
  }

  update(): void {
    this.render();
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.container.remove();
  }
}
