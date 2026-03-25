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
  private modeButtons: Map<string, HTMLButtonElement> = new Map();
  private layerState: Record<string, boolean> = {};
  private unsubscribers: (() => void)[] = [];
  private staleTimers: Map<ModelName, ReturnType<typeof setTimeout>> = new Map();
  private static readonly STALE_TIMEOUT_MS = 60_000; // 60 seconds safety net

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
        // Default: deep enabled, analyzer off by default
        this.layerState = { deep: true, analyzer: false };
      }
    } catch {
      this.layerState = { deep: true, analyzer: false };
    }
  }

  private saveLayerState(): void {
    try {
      localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(this.layerState));
    } catch (e) {
      console.warn('[ModelStatusBar] Failed to save layer state:', e);
    }
  }

  /** Whether deep mode is the active chat responder */
  private get isDeepMode(): boolean {
    return this.layerState['deep'] === true;
  }

  private render(): void {
    this.element.innerHTML = '';

    // --- Mode pill toggle: Fast / Deep ---
    const modePill = createElement('div', { className: 'mode-pill' });

    const fastBtn = document.createElement('button');
    fastBtn.className = `mode-pill-btn mode-fast ${!this.isDeepMode ? 'active' : ''}`;
    fastBtn.setAttribute('data-testid', 'mode-btn-fast');
    fastBtn.title = 'Fast mode — Sonnet responds in chat, workers execute actions';
    fastBtn.innerHTML = '⚡ Sonnet';
    fastBtn.addEventListener('click', () => this.setMode('fast'));
    this.modeButtons.set('fast', fastBtn);

    const deepBtn = document.createElement('button');
    deepBtn.className = `mode-pill-btn mode-deep ${this.isDeepMode ? 'active' : ''}`;
    deepBtn.setAttribute('data-testid', 'mode-btn-deep');
    deepBtn.title = 'Deep mode — Opus responds in chat, workers execute actions';
    deepBtn.innerHTML = '🧠 Opus';
    deepBtn.addEventListener('click', () => this.setMode('deep'));
    this.modeButtons.set('deep', deepBtn);

    modePill.appendChild(fastBtn);
    modePill.appendChild(deepBtn);
    this.element.appendChild(modePill);

    // --- Status dots for active models ---
    const fastModel = this.models.get('fast')!;
    const deepModel = this.models.get('deep')!;

    // Active model status dot (shown next to pill)
    const activeDot = createElement('span', {
      className: `status-dot ${this.isDeepMode ? deepModel.state : fastModel.state}`,
    });
    this.dotElements.set('fast', activeDot);
    this.dotElements.set('deep', activeDot);
    const activeLabel = createElement(
      'span',
      { className: 'status-label' },
      STATE_LABELS[this.isDeepMode ? deepModel.state : fastModel.state]
    );
    this.labelElements.set('fast', activeLabel);
    this.labelElements.set('deep', activeLabel);

    const activeStatus = createElement('div', { className: 'model-status mode-status' });
    activeStatus.appendChild(activeDot);
    activeStatus.appendChild(activeLabel);
    this.element.appendChild(activeStatus);

    // --- Separator ---
    this.element.appendChild(createElement('span', { className: 'status-separator' }));

    // --- Analyzer toggle ---
    const analyzerModel = this.models.get('analyzer')!;
    const analyzerDiv = createElement('div', { className: 'model-status' });

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'layer-toggle';
    checkbox.setAttribute('data-layer', 'analyzer');
    checkbox.setAttribute('data-testid', 'layer-toggle-analyzer');
    checkbox.checked = this.layerState['analyzer'] !== false;
    checkbox.title = 'Enable/disable Analyzer layer';
    checkbox.addEventListener('change', () => {
      this.handleLayerToggle('analyzer', checkbox.checked);
    });
    analyzerDiv.appendChild(checkbox);
    this.toggleElements.set('analyzer', checkbox);

    const analyzerDot = createElement('span', {
      className: `status-dot ${analyzerModel.state}`,
    });
    const analyzerName = createElement('span', {}, `${analyzerModel.emoji} ${analyzerModel.label}`);
    const analyzerLabel = createElement(
      'span',
      { className: 'status-label' },
      STATE_LABELS[analyzerModel.state]
    );

    analyzerDiv.appendChild(analyzerDot);
    analyzerDiv.appendChild(analyzerName);
    analyzerDiv.appendChild(analyzerLabel);

    this.dotElements.set('analyzer', analyzerDot);
    this.labelElements.set('analyzer', analyzerLabel);

    this.element.appendChild(analyzerDiv);

    this.parentElement.appendChild(this.element);
  }

  private setMode(mode: 'fast' | 'deep'): void {
    const deepEnabled = mode === 'deep';
    if (this.layerState['deep'] === deepEnabled) return;

    this.layerState['deep'] = deepEnabled;
    this.saveLayerState();
    eventBus.emit(EVENTS.LAYER_TOGGLE, { layer: 'deep', enabled: deepEnabled });

    // Update pill button classes
    const fastBtn = this.modeButtons.get('fast');
    const deepBtn = this.modeButtons.get('deep');
    if (fastBtn) fastBtn.className = `mode-pill-btn mode-fast ${!deepEnabled ? 'active' : ''}`;
    if (deepBtn) deepBtn.className = `mode-pill-btn mode-deep ${deepEnabled ? 'active' : ''}`;
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

    // Update pill button state class for active/thinking animation
    const btn = this.modeButtons.get(modelName);
    if (btn) {
      btn.classList.toggle('responding', state === 'active');
      btn.classList.toggle('thinking', state === 'thinking');
    }

    // Safety net: auto-reset to idle if stuck in thinking/active for too long
    const existingTimer = this.staleTimers.get(modelName);
    if (existingTimer) {
      clearTimeout(existingTimer);
      this.staleTimers.delete(modelName);
    }

    if (state === 'thinking' || state === 'active') {
      const timer = setTimeout(() => {
        console.warn(`[ModelStatusBar] Safety net: forcing ${modelName} back to idle after ${ModelStatusBar.STALE_TIMEOUT_MS}ms`);
        this.updateModelState(modelName, 'idle');
      }, ModelStatusBar.STALE_TIMEOUT_MS);
      this.staleTimers.set(modelName, timer);
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
    return { deep: true, analyzer: false };
  }

  /** Reset all model statuses to idle — used on reconnection */
  resetAllStatuses(): void {
    for (const modelName of this.models.keys()) {
      this.updateModelState(modelName, 'idle');
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    // Clear all stale timers
    for (const timer of this.staleTimers.values()) {
      clearTimeout(timer);
    }
    this.staleTimers.clear();
    this.toggleElements.clear();
    this.modeButtons.clear();
    this.element.remove();
  }
}
