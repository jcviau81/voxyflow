import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { appState } from '../../state/AppState';
import { ttsService } from '../../services/TtsService';

const LAYER_STORAGE_KEY = 'voxyflow_layer_toggles';

export class TopBar {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('header', { className: 'top-bar' });
    this.render();
    this.setupListeners();
  }

  private getLayerState(): { deep: boolean; analyzer: boolean } {
    try {
      const stored = localStorage.getItem(LAYER_STORAGE_KEY);
      if (stored) return JSON.parse(stored);
    } catch { /* ignore */ }
    return { deep: true, analyzer: true };
  }

  private setDeepMode(deep: boolean): void {
    const state = this.getLayerState();
    state.deep = deep;
    localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(state));
    eventBus.emit(EVENTS.STATE_CHANGED, { key: 'layerToggles', value: state });
    this.render();
  }

  private getVoiceSetting(key: string, defaultVal: boolean): boolean {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      if (stored) {
        const settings = JSON.parse(stored);
        return settings?.voice?.[key] ?? defaultVal;
      }
    } catch { /* ignore */ }
    return defaultVal;
  }

  private setVoiceSetting(key: string, value: boolean): void {
    try {
      const stored = localStorage.getItem('voxyflow_settings');
      const settings = stored ? JSON.parse(stored) : {};
      if (!settings.voice) settings.voice = {};
      settings.voice[key] = value;
      localStorage.setItem('voxyflow_settings', JSON.stringify(settings));
    } catch { /* ignore */ }
  }

  render(): void {
    this.container.innerHTML = '';

    // Menu toggle (mobile)
    const menuBtn = createElement('button', { className: 'top-bar-menu-btn' }, '☰');
    menuBtn.addEventListener('click', () => {
      eventBus.emit(EVENTS.SIDEBAR_TOGGLE);
    });

    // Project name
    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    const projectName = project?.name || 'Main';
    const projectLabel = createElement('span', { className: 'top-bar-project-name' }, projectName);

    // Spacer
    const spacer = createElement('div', { className: 'top-bar-spacer' });

    // Fast/Deep mode toggle pill
    const isDeep = this.getLayerState().deep;
    const modePill = createElement('div', { className: 'top-bar-mode-pill' });

    const fastBtn = createElement('button', {
      className: `top-bar-mode-btn ${!isDeep ? 'active' : ''}`,
      title: 'Fast mode (Sonnet)',
    }, '⚡');
    fastBtn.addEventListener('click', () => this.setDeepMode(false));

    const deepBtn = createElement('button', {
      className: `top-bar-mode-btn ${isDeep ? 'active' : ''}`,
      title: 'Deep mode (Opus)',
    }, '🧠');
    deepBtn.addEventListener('click', () => this.setDeepMode(true));

    modePill.appendChild(fastBtn);
    modePill.appendChild(deepBtn);

    // Auto-play toggle
    const autoPlay = this.getVoiceSetting('tts_auto_play', false);
    const autoPlayBtn = createElement('button', {
      className: `top-bar-voice-btn ${autoPlay ? 'active' : ''}`,
      title: 'Auto-play responses',
    }, '🔊');
    autoPlayBtn.addEventListener('click', () => {
      const newVal = !this.getVoiceSetting('tts_auto_play', false);
      this.setVoiceSetting('tts_auto_play', newVal);
      if (!newVal) ttsService.stop();
      this.render();
    });

    // Auto-send toggle
    const autoSend = this.getVoiceSetting('stt_auto_send', false);
    const autoSendBtn = createElement('button', {
      className: `top-bar-voice-btn ${autoSend ? 'active' : ''}`,
      title: 'Auto-send voice',
    }, '📤');
    autoSendBtn.addEventListener('click', () => {
      const newVal = !this.getVoiceSetting('stt_auto_send', false);
      this.setVoiceSetting('stt_auto_send', newVal);
      this.render();
    });

    this.container.appendChild(menuBtn);
    this.container.appendChild(projectLabel);
    this.container.appendChild(spacer);
    this.container.appendChild(modePill);
    this.container.appendChild(autoSendBtn);
    this.container.appendChild(autoPlayBtn);

    this.parentElement.appendChild(this.container);
  }

  private setupListeners(): void {
    this.unsubscribers.push(
      appState.subscribe('voiceActive', () => this.render())
    );
    this.unsubscribers.push(
      appState.subscribe('currentProjectId', () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.OPPORTUNITIES_COUNT, () => this.render())
    );
    this.unsubscribers.push(
      eventBus.on(EVENTS.TAB_SWITCH, () => this.render())
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
