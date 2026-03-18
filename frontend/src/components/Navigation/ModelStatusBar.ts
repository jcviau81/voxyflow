import { ModelName, ModelState } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';

interface ModelInfo {
  name: ModelName;
  emoji: string;
  label: string;
  state: ModelState;
  /** Whether this layer can be toggled on/off */
  toggleable: boolean;
}

const MODEL_DEFAULTS: ModelInfo[] = [
  { name: 'fast', emoji: '⚡', label: 'Fast', state: 'idle', toggleable: false },
  { name: 'deep', emoji: '🧠', label: 'Deep', state: 'idle', toggleable: true },
  { name: 'analyzer', emoji: '🔍', label: 'Analyzer', state: 'idle', toggleable: true },
];

const STATE_LABELS: Record<ModelState, string> = {
  active: 'responding',
  thinking: 'thinking...',
  idle: 'idle',
  error: 'error',
};

const LAYER_STORAGE_KEY = 'voxyflow_layer_toggles';

export class ModelStatusBar {
  private element: HTMLElement;
  private models: Map<ModelName, ModelInfo> = new Map();
  private dotElements: Map<ModelName, HTMLElement> = new Map();
  private labelElements: Map<ModelName, HTMLElement> = new Map();
  private toggleElements: Map<ModelName, HTMLInputElement> = new Map();
  private layerState: Record<string, boolean> = {};
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.element = createElement('div', {
      className: 'model-status-bar',
      'data-testid': 'model-status-bar',
    });

    // Initialize models
    MODEL_DEFAULTS.forEach((m) => this.models.set(m.name, { ...m }));

    // Load layer toggle state from localStorage
    this.loadLayerState();

    this.render();
    this.setupListeners();
  }

  private loadLayerState(): void {
    try {
      const stored = localStorage.getItem(LAYER_STORAGE_KEY);
      if (stored) {
        this.layerState = JSON.parse(stored);
      } else {
        // Default: all toggleable layers enabled
        this.layerState = { deep: true, analyzer: true };
      }
    } catch {
      this.layerState = { deep: true, analyzer: true };
    }
  }

  private saveLayerState(): void {
    try {
      localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(this.layerState));
    } catch (e) {
      console.warn('[ModelStatusBar] Failed to save layer state:', e);
    }
  }

  private render(): void {
    this.element.innerHTML = '';

    this.models.forEach((model) => {
      const statusDiv = createElement('div', { className: 'model-status' });

      // Layer toggle checkbox (only for toggleable models)
      if (model.toggleable) {
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.className = 'layer-toggle';
        checkbox.setAttribute('data-layer', model.name);
        checkbox.setAttribute('data-testid', `layer-toggle-${model.name}`);
        checkbox.checked = this.layerState[model.name] !== false;
        checkbox.title = `Enable/disable ${model.label} layer`;
        checkbox.addEventListener('change', () => {
          this.handleLayerToggle(model.name, checkbox.checked);
        });
        statusDiv.appendChild(checkbox);
        this.toggleElements.set(model.name, checkbox);
      }

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

  private handleLayerToggle(layer: string, enabled: boolean): void {
    this.layerState[layer] = enabled;
    this.saveLayerState();
    eventBus.emit(EVENTS.LAYER_TOGGLE, { layer, enabled });
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

  /** Get the current layer toggle states */
  getLayerState(): Record<string, boolean> {
    return { ...this.layerState };
  }

  /** Static helper to read layer state from localStorage */
  static getStoredLayerState(): Record<string, boolean> {
    try {
      const stored = localStorage.getItem(LAYER_STORAGE_KEY);
      if (stored) return JSON.parse(stored);
    } catch {}
    return { deep: true, analyzer: true };
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.toggleElements.clear();
    this.element.remove();
  }
}
