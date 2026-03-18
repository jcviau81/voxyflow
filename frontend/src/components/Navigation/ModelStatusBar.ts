import { ModelName, ModelState } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';

interface ModelInfo {
  name: ModelName;
  emoji: string;
  label: string;
  state: ModelState;
}

const MODEL_DEFAULTS: ModelInfo[] = [
  { name: 'haiku', emoji: '⚡', label: 'Haiku', state: 'idle' },
  { name: 'opus', emoji: '🧠', label: 'Opus', state: 'idle' },
  { name: 'analyzer', emoji: '🔍', label: 'Analyzer', state: 'idle' },
];

const STATE_LABELS: Record<ModelState, string> = {
  active: 'responding',
  thinking: 'thinking...',
  idle: 'idle',
  error: 'error',
};

export class ModelStatusBar {
  private element: HTMLElement;
  private models: Map<ModelName, ModelInfo> = new Map();
  private dotElements: Map<ModelName, HTMLElement> = new Map();
  private labelElements: Map<ModelName, HTMLElement> = new Map();
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.element = createElement('div', {
      className: 'model-status-bar',
      'data-testid': 'model-status-bar',
    });

    // Initialize models
    MODEL_DEFAULTS.forEach((m) => this.models.set(m.name, { ...m }));

    this.render();
    this.setupListeners();
  }

  private render(): void {
    this.element.innerHTML = '';

    this.models.forEach((model) => {
      const statusDiv = createElement('div', { className: 'model-status' });

      const dot = createElement('span', { className: `status-dot ${model.state}` });
      const nameSpan = createElement('span', {}, `${model.emoji} ${model.label}`);
      const label = createElement('span', { className: 'status-label' }, STATE_LABELS[model.state]);

      statusDiv.appendChild(dot);
      statusDiv.appendChild(nameSpan);
      statusDiv.appendChild(label);

      this.dotElements.set(model.name, dot);
      this.labelElements.set(model.name, label);

      this.element.appendChild(statusDiv);
    });

    this.parentElement.appendChild(this.element);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      eventBus.on(EVENTS.MODEL_STATUS, (data: unknown) => {
        const { model, state } = data as { model: ModelName; state: ModelState };
        this.updateModelState(model, state);
      })
    );
  }

  private updateModelState(modelName: ModelName, state: ModelState): void {
    const model = this.models.get(modelName);
    if (!model) return;

    model.state = state;

    const dot = this.dotElements.get(modelName);
    if (dot) {
      dot.className = `status-dot ${state}`;
    }

    const label = this.labelElements.get(modelName);
    if (label) {
      label.textContent = STATE_LABELS[state] || state;
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.element.remove();
  }
}
