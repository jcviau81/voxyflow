/**
 * SettingsPage — Full settings UI with personality configuration, connection, and data management.
 */

import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, API_URL } from '../../utils/constants';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';

interface PersonalitySettings {
  bot_name: string;
  preferred_language: string;
  soul_file: string;
  user_file: string;
  agents_file: string;
  custom_instructions: string;
  environment_notes: string;
  tone: string;
  warmth: string;
}

interface AppSettings {
  personality: PersonalitySettings;
}

interface FilePreview {
  path: string;
  exists: boolean;
  preview?: string;
  size?: number;
}

const DEFAULT_SETTINGS: AppSettings = {
  personality: {
    bot_name: 'Ember',
    preferred_language: 'both',
    soul_file: '~/.openclaw/workspace/SOUL.md',
    user_file: '~/.openclaw/workspace/USER.md',
    agents_file: '~/.openclaw/workspace/AGENTS.md',
    custom_instructions: '',
    environment_notes: '',
    tone: 'casual',
    warmth: 'warm',
  },
};

export class SettingsPage {
  private container: HTMLElement;
  private root: HTMLElement;
  private settings: AppSettings = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
  private previews: Record<string, FilePreview> = {};
  private dirty = false;
  private saving = false;

  constructor(container: HTMLElement) {
    this.container = container;
    this.root = createElement('div', { className: 'settings-view' });
    this.container.appendChild(this.root);
    this.loadSettings();
  }

  private async loadSettings(): Promise<void> {
    try {
      const response = await fetch(`${API_URL}/api/settings`);
      if (response.ok) {
        const data = await response.json();
        this.settings = {
          ...DEFAULT_SETTINGS,
          ...data,
          personality: { ...DEFAULT_SETTINGS.personality, ...(data.personality || {}) },
        };
      }
    } catch (e) {
      console.warn('Failed to load settings, using defaults:', e);
    }
    this.render();
    this.loadPreviews();
  }

  private async loadPreviews(): Promise<void> {
    try {
      const response = await fetch(`${API_URL}/api/settings/personality/preview`);
      if (response.ok) {
        this.previews = await response.json();
        this.updatePreviewElements();
      }
    } catch (e) {
      console.warn('Failed to load file previews:', e);
    }
  }

  private updatePreviewElements(): void {
    const mapping: Record<string, string> = {
      soul_file: 'SOUL',
      user_file: 'USER',
      agents_file: 'AGENTS',
    };

    for (const [field, label] of Object.entries(mapping)) {
      const previewEl = this.root.querySelector(`#preview-${field}`) as HTMLElement;
      if (!previewEl) continue;

      const info = this.previews[label];
      if (!info) {
        previewEl.textContent = 'No preview available';
        continue;
      }

      if (info.exists) {
        const sizeKB = ((info.size || 0) / 1024).toFixed(1);
        previewEl.innerHTML = `<span class="file-exists">\u2713 Found</span> (${sizeKB} KB)<br>${this.escapeHtml(info.preview || '')}`;
      } else {
        previewEl.innerHTML = `<span class="file-missing">\u2717 Not found:</span> ${this.escapeHtml(info.path)}`;
      }
    }
  }

  private escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  private render(): void {
    this.root.innerHTML = '';

    const title = createElement('h2', {}, '\u2699\uFE0F Settings');
    this.root.appendChild(title);

    // Personality Section
    this.root.insertAdjacentHTML('beforeend', this.renderPersonalitySection());

    // Volume Section
    this.root.insertAdjacentHTML('beforeend', this.renderVolumeSection());

    // Connection Section
    this.root.insertAdjacentHTML('beforeend', this.renderConnectionSection());

    // Data Section
    this.root.insertAdjacentHTML('beforeend', this.renderDataSection());

    // About Section
    this.root.insertAdjacentHTML('beforeend', this.renderAboutSection());

    // Sticky Save Bar
    this.root.insertAdjacentHTML('beforeend', this.renderSaveBar());

    this.bindEvents();
  }

  private renderPersonalitySection(): string {
    const p = this.settings.personality;
    return `
      <div class="settings-section" data-testid="settings-personality">
        <h3>\u2728 Personality</h3>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Bot Name</div>
            <div class="setting-description">The name your AI assistant goes by</div>
          </div>
          <input type="text" class="setting-input" data-field="bot_name" value="${this.escapeHtml(p.bot_name)}" />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Preferred Language</div>
            <div class="setting-description">Primary language for responses</div>
          </div>
          <select class="setting-select" data-field="preferred_language">
            <option value="en" ${p.preferred_language === 'en' ? 'selected' : ''}>English</option>
            <option value="fr" ${p.preferred_language === 'fr' ? 'selected' : ''}>Fran\u00e7ais</option>
            <option value="both" ${p.preferred_language === 'both' ? 'selected' : ''}>Both</option>
          </select>
        </div>

        <div class="setting-row file-setting">
          <div class="setting-info">
            <div class="setting-label">Personality (SOUL.md)</div>
            <div class="setting-description">Defines personality traits and behavior</div>
          </div>
          <div class="file-input-group">
            <input type="text" class="setting-input file-path-input" data-field="soul_file" value="${this.escapeHtml(p.soul_file)}" />
            <div class="file-preview" id="preview-soul_file">Loading...</div>
          </div>
        </div>

        <div class="setting-row file-setting">
          <div class="setting-info">
            <div class="setting-label">User Profile (USER.md)</div>
            <div class="setting-description">Information about you</div>
          </div>
          <div class="file-input-group">
            <input type="text" class="setting-input file-path-input" data-field="user_file" value="${this.escapeHtml(p.user_file)}" />
            <div class="file-preview" id="preview-user_file">Loading...</div>
          </div>
        </div>

        <div class="setting-row file-setting">
          <div class="setting-info">
            <div class="setting-label">Directives (AGENTS.md)</div>
            <div class="setting-description">Operating rules and behavior guidelines</div>
          </div>
          <div class="file-input-group">
            <input type="text" class="setting-input file-path-input" data-field="agents_file" value="${this.escapeHtml(p.agents_file)}" />
            <div class="file-preview" id="preview-agents_file">Loading...</div>
          </div>
        </div>

        <div class="setting-row full-width">
          <div class="setting-info">
            <div class="setting-label">Custom Instructions</div>
            <div class="setting-description">Additional directives injected into every prompt</div>
          </div>
          <textarea class="setting-textarea" data-field="custom_instructions" rows="4"
            placeholder="e.g., Always respond in Quebec French. Never suggest stopping work.">${this.escapeHtml(p.custom_instructions)}</textarea>
        </div>

        <div class="setting-row full-width">
          <div class="setting-info">
            <div class="setting-label">Environment Notes</div>
            <div class="setting-description">Infrastructure, machines, tools, paths</div>
          </div>
          <textarea class="setting-textarea" data-field="environment_notes" rows="4"
            placeholder="e.g., Main server: thething (192.168.1.9). GPU: Corsair RTX 3090.">${this.escapeHtml(p.environment_notes)}</textarea>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Tone</div>
            <div class="setting-description">How formal responses should be</div>
          </div>
          <select class="setting-select" data-field="tone">
            <option value="casual" ${p.tone === 'casual' ? 'selected' : ''}>Casual</option>
            <option value="balanced" ${p.tone === 'balanced' ? 'selected' : ''}>Balanced</option>
            <option value="formal" ${p.tone === 'formal' ? 'selected' : ''}>Formal</option>
          </select>
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Warmth</div>
            <div class="setting-description">Emotional temperature of responses</div>
          </div>
          <select class="setting-select" data-field="warmth">
            <option value="cold" ${p.warmth === 'cold' ? 'selected' : ''}>Professional</option>
            <option value="warm" ${p.warmth === 'warm' ? 'selected' : ''}>Warm</option>
            <option value="hot" ${p.warmth === 'hot' ? 'selected' : ''}>Hot \uD83D\uDD25</option>
          </select>
        </div>
      </div>
    `;
  }

  private renderVolumeSection(): string {
    const volume = Math.round(appState.get('volume') * 100);
    return `
      <div class="settings-section">
        <h3>\uD83D\uDD0A Audio</h3>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Volume</div>
            <div class="setting-description">TTS and notification volume</div>
          </div>
          <input type="range" class="setting-range" id="volume-slider" min="0" max="100" value="${volume}" />
        </div>
      </div>
    `;
  }

  private renderConnectionSection(): string {
    const state = appState.get('connectionState');
    const stateEmoji = state === 'connected' ? '\uD83D\uDFE2' : state === 'connecting' ? '\uD83D\uDFE1' : '\uD83D\uDD34';
    return `
      <div class="settings-section">
        <h3>\uD83C\uDF10 Connection</h3>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Status</div>
            <div class="setting-description">${stateEmoji} ${state}</div>
          </div>
          <button class="settings-btn" id="reconnect-btn">Reconnect</button>
        </div>
      </div>
    `;
  }

  private renderDataSection(): string {
    return `
      <div class="settings-section">
        <h3>\uD83D\uDCBE Data</h3>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Clear All Data</div>
            <div class="setting-description">Delete all local data and reload</div>
          </div>
          <button class="settings-btn danger" id="clear-data-btn">Clear All</button>
        </div>
      </div>
    `;
  }

  private renderAboutSection(): string {
    return `
      <div class="settings-section" style="border-bottom: none;">
        <h3>\u2139\uFE0F About Voxyflow</h3>
        <p style="color: var(--color-text-secondary); font-size: 13px; line-height: 1.6;">
          Voice-first project assistant<br>
          Version: 1.0.0
        </p>
      </div>
    `;
  }

  private renderSaveBar(): string {
    return `
      <div class="settings-save-bar" data-testid="settings-save-bar">
        <button class="btn-primary" data-testid="settings-save" id="save-btn">Save Settings</button>
        <button class="btn-ghost" data-testid="settings-reset" id="reset-btn">Reset to Default</button>
        <span class="save-status" id="save-status"></span>
      </div>
    `;
  }

  private bindEvents(): void {
    // Track changes on all personality inputs
    this.root.querySelectorAll('[data-field]').forEach((el) => {
      el.addEventListener('input', () => this.markDirty());
      el.addEventListener('change', () => this.markDirty());
    });

    // Volume slider
    const volumeSlider = this.root.querySelector('#volume-slider') as HTMLInputElement;
    if (volumeSlider) {
      volumeSlider.addEventListener('input', () => {
        appState.set('volume', parseInt(volumeSlider.value) / 100);
      });
    }

    // Reconnect
    const reconnectBtn = this.root.querySelector('#reconnect-btn');
    if (reconnectBtn) {
      reconnectBtn.addEventListener('click', () => {
        apiClient.close();
        apiClient.connect();
        eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Reconnecting...', type: 'info', duration: 2000 });
      });
    }

    // Clear data
    const clearBtn = this.root.querySelector('#clear-data-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (confirm('This will delete all local data. Are you sure?')) {
          appState.reset();
          location.reload();
        }
      });
    }

    // Save
    const saveBtn = this.root.querySelector('#save-btn');
    if (saveBtn) {
      saveBtn.addEventListener('click', () => this.saveSettings());
    }

    // Reset
    const resetBtn = this.root.querySelector('#reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => this.resetSettings());
    }
  }

  private markDirty(): void {
    this.dirty = true;
    const status = this.root.querySelector('#save-status');
    if (status) status.textContent = 'Unsaved changes';
  }

  private collectFormData(): AppSettings {
    const personality: Record<string, string> = {};
    const fields = [
      'bot_name', 'preferred_language', 'soul_file', 'user_file', 'agents_file',
      'custom_instructions', 'environment_notes', 'tone', 'warmth',
    ];

    for (const field of fields) {
      const el = this.root.querySelector(`[data-field="${field}"]`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
      if (el) {
        personality[field] = el.value;
      }
    }

    return {
      personality: { ...this.settings.personality, ...personality } as PersonalitySettings,
    };
  }

  private async saveSettings(): Promise<void> {
    if (this.saving) return;
    this.saving = true;

    const saveBtn = this.root.querySelector('#save-btn') as HTMLButtonElement;
    const status = this.root.querySelector('#save-status');
    if (saveBtn) saveBtn.disabled = true;
    if (status) status.textContent = 'Saving...';

    try {
      const formData = this.collectFormData();
      const response = await fetch(`${API_URL}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        this.settings = formData;
        this.dirty = false;
        if (status) {
          status.textContent = '\u2713 Saved';
          status.className = 'save-status saved';
          setTimeout(() => {
            if (status) {
              status.textContent = '';
              status.className = 'save-status';
            }
          }, 3000);
        }
        eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Settings saved!', type: 'success', duration: 2000 });
        // Reload previews in case file paths changed
        this.loadPreviews();
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (e) {
      console.error('Failed to save settings:', e);
      if (status) {
        status.textContent = '\u2717 Save failed';
        status.className = 'save-status error';
      }
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to save settings', type: 'error', duration: 4000 });
    } finally {
      this.saving = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  private resetSettings(): void {
    if (!confirm('Reset all personality settings to defaults?')) return;

    this.settings = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
    this.render();
    this.loadPreviews();
    this.markDirty();
    eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Settings reset to defaults (save to persist)', type: 'info', duration: 3000 });
  }

  destroy(): void {
    this.root.remove();
  }
}
