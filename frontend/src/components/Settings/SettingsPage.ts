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

interface FileEditorState {
  filename: string;
  label: string;
  emoji: string;
  content: string;
  editing: boolean;
  exists: boolean;
}

const DEFAULT_SETTINGS: AppSettings = {
  personality: {
    bot_name: 'Assistant',
    preferred_language: 'both',
    soul_file: './personality/SOUL.md',
    user_file: './personality/USER.md',
    agents_file: './personality/AGENTS.md',
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
  private fileEditors: FileEditorState[] = [
    { filename: 'SOUL.md', label: 'Personality', emoji: '✨', content: '', editing: false, exists: false },
    { filename: 'USER.md', label: 'User Profile', emoji: '👤', content: '', editing: false, exists: false },
    { filename: 'AGENTS.md', label: 'Directives', emoji: '📋', content: '', editing: false, exists: false },
    { filename: 'IDENTITY.md', label: 'Identity', emoji: '🪪', content: '', editing: false, exists: false },
  ];
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
    await this.loadFileEditors();
  }

  private async loadFileEditors(): Promise<void> {
    for (const fe of this.fileEditors) {
      try {
        const response = await fetch(`${API_URL}/api/settings/personality/files/${fe.filename}`);
        if (response.ok) {
          const data = await response.json();
          fe.content = data.content || '';
          fe.exists = data.exists !== false;
        }
      } catch (e) {
        console.warn(`Failed to load ${fe.filename}:`, e);
        fe.content = '';
        fe.exists = false;
      }

      const previewEl = this.root.querySelector(`#preview-${fe.filename}`) as HTMLElement;
      if (previewEl) {
        if (fe.exists && fe.content) {
          const preview = fe.content.length > 300 ? fe.content.substring(0, 300) + '...' : fe.content;
          const sizeKB = (fe.content.length / 1024).toFixed(1);
          previewEl.innerHTML = `<span class="file-exists">✓ ${sizeKB} KB</span>\n${this.escapeHtml(preview)}`;
        } else {
          previewEl.innerHTML = `<span class="file-missing">✗ File not found</span>`;
        }
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

    this.root.insertAdjacentHTML('beforeend', this.renderPersonalitySection());
    this.root.insertAdjacentHTML('beforeend', this.renderGitHubSection());
    this.root.insertAdjacentHTML('beforeend', this.renderVolumeSection());
    this.root.insertAdjacentHTML('beforeend', this.renderConnectionSection());
    this.root.insertAdjacentHTML('beforeend', this.renderDataSection());
    this.root.insertAdjacentHTML('beforeend', this.renderAboutSection());
    this.root.insertAdjacentHTML('beforeend', this.renderSaveBar());

    this.bindEvents();
  }

  private renderPersonalitySection(): string {
    const p = this.settings.personality;
    const fileEditorsHtml = this.fileEditors.map((fe) => `
      <div class="file-editor" data-testid="editor-${fe.filename.replace('.md', '').toLowerCase()}">
        <div class="file-editor-header">
          <div class="setting-label">${fe.emoji} ${fe.label} (${fe.filename})</div>
          <div class="file-editor-actions">
            <button class="btn-sm" data-action="edit-file" data-filename="${fe.filename}">✏️ Edit</button>
            <button class="btn-sm btn-danger-sm" data-action="reset-file" data-filename="${fe.filename}">↩️ Reset</button>
          </div>
        </div>
        <div class="file-preview-content" id="preview-${fe.filename}" data-filename="${fe.filename}">
          Loading...
        </div>
        <div class="file-editor-area" id="editor-${fe.filename}" style="display:none">
          <textarea class="file-textarea" id="textarea-${fe.filename}" rows="15"></textarea>
          <div class="file-editor-footer">
            <button class="btn-primary btn-sm" data-action="save-file" data-filename="${fe.filename}">💾 Save</button>
            <button class="btn-ghost btn-sm" data-action="cancel-file" data-filename="${fe.filename}">Cancel</button>
          </div>
        </div>
      </div>
    `).join('');

    return `
      <div class="settings-section" data-testid="settings-personality">
        <h3>✨ Personality</h3>

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

        <div class="file-editors-section">
          <div class="setting-info" style="margin-bottom: 12px;">
            <div class="setting-label">Personality Files</div>
            <div class="setting-description">Edit the markdown files that define your assistant's personality</div>
          </div>
          ${fileEditorsHtml}
        </div>

        <div class="setting-row full-width">
          <div class="setting-info">
            <div class="setting-label">Custom Instructions</div>
            <div class="setting-description">Additional directives injected into every prompt</div>
          </div>
          <textarea class="setting-textarea" data-field="custom_instructions" rows="4"
            placeholder="e.g., Always respond concisely. Prefer code examples over explanations.">${this.escapeHtml(p.custom_instructions)}</textarea>
        </div>

        <div class="setting-row full-width">
          <div class="setting-info">
            <div class="setting-label">Environment Notes</div>
            <div class="setting-description">Infrastructure, machines, tools, paths</div>
          </div>
          <textarea class="setting-textarea" data-field="environment_notes" rows="4"
            placeholder="e.g., Dev server: my-server. Database: PostgreSQL on port 5432.">${this.escapeHtml(p.environment_notes)}</textarea>
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

  private renderGitHubSection(): string {
    return `
      <div class="settings-section" data-testid="settings-github">
        <h3>🔗 GitHub Integration</h3>

        <div class="github-connection-status" id="github-connection-status">
          <span class="github-loading">Checking GitHub status...</span>
        </div>

        <!-- Option 1: GitHub CLI -->
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">GitHub CLI (gh)</div>
            <div class="setting-description">Recommended: uses your existing gh authentication</div>
          </div>
          <div class="github-cli-status" id="github-cli-status">
            <span class="github-loading">Checking...</span>
          </div>
        </div>

        <!-- Option 2: Personal Access Token -->
        <div class="setting-row full-width">
          <div class="setting-info">
            <div class="setting-label">Personal Access Token (alternative)</div>
            <div class="setting-description">Create at <a href="https://github.com/settings/tokens" target="_blank" rel="noopener">github.com/settings/tokens</a></div>
          </div>
          <div class="token-input-row" style="display: flex; gap: 8px; align-items: center;">
            <input type="password" class="setting-input" placeholder="ghp_..." id="github-token-input" style="flex: 1;" />
            <button class="btn-secondary" id="github-save-token-btn">Save Token</button>
          </div>
        </div>

        <!-- Test Connection -->
        <div style="display: flex; gap: 12px; align-items: center; margin-top: 8px;">
          <button class="btn-primary" data-testid="github-test-btn" id="github-test-btn">Test Connection</button>
          <div class="github-test-result" id="github-test-result"></div>
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
    this.root.querySelectorAll('[data-field]').forEach((el) => {
      el.addEventListener('input', () => this.markDirty());
      el.addEventListener('change', () => this.markDirty());
    });

    const volumeSlider = this.root.querySelector('#volume-slider') as HTMLInputElement;
    if (volumeSlider) {
      volumeSlider.addEventListener('input', () => {
        appState.set('volume', parseInt(volumeSlider.value) / 100);
      });
    }

    const reconnectBtn = this.root.querySelector('#reconnect-btn');
    if (reconnectBtn) {
      reconnectBtn.addEventListener('click', () => {
        apiClient.close();
        apiClient.connect();
        eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Reconnecting...', type: 'info', duration: 2000 });
      });
    }

    const clearBtn = this.root.querySelector('#clear-data-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (confirm('This will delete all local data. Are you sure?')) {
          appState.reset();
          location.reload();
        }
      });
    }

    const saveBtn = this.root.querySelector('#save-btn');
    if (saveBtn) {
      saveBtn.addEventListener('click', () => this.saveSettings());
    }

    const resetBtn = this.root.querySelector('#reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => this.resetSettings());
    }

    // File editor buttons
    this.root.querySelectorAll('[data-action="edit-file"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const filename = (btn as HTMLElement).dataset.filename!;
        this.toggleFileEditor(filename, true);
      });
    });

    this.root.querySelectorAll('[data-action="cancel-file"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const filename = (btn as HTMLElement).dataset.filename!;
        this.toggleFileEditor(filename, false);
      });
    });

    this.root.querySelectorAll('[data-action="save-file"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const filename = (btn as HTMLElement).dataset.filename!;
        this.saveFile(filename);
      });
    });

    this.root.querySelectorAll('[data-action="reset-file"]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const filename = (btn as HTMLElement).dataset.filename!;
        this.resetFile(filename);
      });
    });

    // GitHub events
    const githubTestBtn = this.root.querySelector('#github-test-btn');
    if (githubTestBtn) {
      githubTestBtn.addEventListener('click', () => this.checkGitHubStatus(true));
    }

    const githubSaveTokenBtn = this.root.querySelector('#github-save-token-btn');
    if (githubSaveTokenBtn) {
      githubSaveTokenBtn.addEventListener('click', () => this.saveGitHubToken());
    }

    // Auto-check GitHub status on load
    this.checkGitHubStatus(false);
  }

  private async checkGitHubStatus(showToast: boolean): Promise<void> {
    const statusEl = this.root.querySelector('#github-connection-status');
    const cliStatusEl = this.root.querySelector('#github-cli-status');
    const testResult = this.root.querySelector('#github-test-result');

    try {
      const response = await fetch(`${API_URL}/api/github/status`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();

      // Connection status banner
      if (statusEl) {
        if (data.gh_authenticated) {
          statusEl.innerHTML = `<span style="color: var(--color-success, #4ecdc4);">✅ Connected as <strong>@${data.username || 'unknown'}</strong> via ${data.method === 'pat' ? 'Personal Access Token' : 'GitHub CLI'}</span>`;
        } else if (data.token_configured) {
          statusEl.innerHTML = `<span style="color: var(--color-warning, #feca57);">⚠️ Token configured but authentication failed</span>`;
        } else {
          statusEl.innerHTML = `<span style="color: var(--color-error, #ff6b6b);">❌ Not connected — configure below</span>`;
        }
      }

      // CLI status
      if (cliStatusEl) {
        if (!data.gh_installed) {
          cliStatusEl.innerHTML = `<span style="color: var(--color-text-secondary);">❌ Not installed</span>`;
        } else if (data.gh_authenticated && data.method === 'gh_cli') {
          cliStatusEl.innerHTML = `<span style="color: var(--color-success, #4ecdc4);">✅ Authenticated as @${data.username}</span>`;
        } else {
          cliStatusEl.innerHTML = `<span style="color: var(--color-warning, #feca57);">⚠️ Installed but not authenticated</span>`;
        }
      }

      // Test result
      if (testResult && showToast) {
        if (data.gh_authenticated) {
          testResult.innerHTML = `<span style="color: var(--color-success, #4ecdc4);">✅ Connection successful!</span>`;
          eventBus.emit(EVENTS.TOAST_SHOW, { message: `GitHub connected as @${data.username}`, type: 'success', duration: 3000 });
        } else {
          testResult.innerHTML = `<span style="color: var(--color-error, #ff6b6b);">❌ Not authenticated</span>`;
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'GitHub not connected', type: 'error', duration: 3000 });
        }
      }
    } catch (e) {
      console.error('GitHub status check failed:', e);
      if (statusEl) {
        statusEl.innerHTML = `<span style="color: var(--color-error, #ff6b6b);">❌ Failed to check status</span>`;
      }
      if (cliStatusEl) {
        cliStatusEl.innerHTML = `<span style="color: var(--color-text-secondary);">Unknown</span>`;
      }
      if (testResult && showToast) {
        testResult.innerHTML = `<span style="color: var(--color-error, #ff6b6b);">❌ Connection check failed</span>`;
        eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to check GitHub status', type: 'error', duration: 3000 });
      }
    }
  }

  private async saveGitHubToken(): Promise<void> {
    const input = this.root.querySelector('#github-token-input') as HTMLInputElement;
    if (!input) return;

    const token = input.value.trim();
    if (!token) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Enter a token first', type: 'error', duration: 2000 });
      return;
    }

    if (!token.startsWith('ghp_') && !token.startsWith('github_pat_')) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Token must start with ghp_ or github_pat_', type: 'error', duration: 3000 });
      return;
    }

    try {
      const response = await fetch(`${API_URL}/api/github/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Save failed' }));
        throw new Error(err.detail || 'Save failed');
      }

      input.value = '';
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Token saved! Testing connection...', type: 'success', duration: 2000 });

      // Re-check status
      setTimeout(() => this.checkGitHubStatus(true), 500);
    } catch (e) {
      console.error('Failed to save GitHub token:', e);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `Failed to save token: ${e}`, type: 'error', duration: 4000 });
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
      'bot_name', 'preferred_language',
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

  private toggleFileEditor(filename: string, open: boolean): void {
    const fe = this.fileEditors.find((f) => f.filename === filename);
    if (!fe) return;

    const editorEl = this.root.querySelector(`#editor-${filename}`) as HTMLElement;
    const previewEl = this.root.querySelector(`#preview-${filename}`) as HTMLElement;
    const textareaEl = this.root.querySelector(`#textarea-${filename}`) as HTMLTextAreaElement;

    if (!editorEl || !previewEl || !textareaEl) return;

    fe.editing = open;
    if (open) {
      textareaEl.value = fe.content;
      editorEl.style.display = 'block';
      previewEl.style.display = 'none';
      textareaEl.focus();
    } else {
      editorEl.style.display = 'none';
      previewEl.style.display = 'block';
    }
  }

  private async saveFile(filename: string): Promise<void> {
    const fe = this.fileEditors.find((f) => f.filename === filename);
    if (!fe) return;

    const textareaEl = this.root.querySelector(`#textarea-${filename}`) as HTMLTextAreaElement;
    if (!textareaEl) return;

    const content = textareaEl.value;

    try {
      const response = await fetch(`${API_URL}/api/settings/personality/files/${filename}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });

      if (response.ok) {
        fe.content = content;
        fe.exists = true;
        this.toggleFileEditor(filename, false);

        // Refresh preview
        const previewEl = this.root.querySelector(`#preview-${filename}`) as HTMLElement;
        if (previewEl) {
          const preview = content.length > 300 ? content.substring(0, 300) + '...' : content;
          const sizeKB = (content.length / 1024).toFixed(1);
          previewEl.innerHTML = `<span class="file-exists">✓ ${sizeKB} KB</span>\n${this.escapeHtml(preview)}`;
        }

        eventBus.emit(EVENTS.TOAST_SHOW, { message: `${filename} saved!`, type: 'success', duration: 2000 });
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (e) {
      console.error(`Failed to save ${filename}:`, e);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `Failed to save ${filename}`, type: 'error', duration: 4000 });
    }
  }

  private async resetFile(filename: string): Promise<void> {
    if (!confirm(`Reset ${filename} to default template? This will overwrite current content.`)) return;

    try {
      const response = await fetch(`${API_URL}/api/settings/personality/files/${filename}/reset`, {
        method: 'POST',
      });

      if (response.ok) {
        eventBus.emit(EVENTS.TOAST_SHOW, { message: `${filename} reset to default`, type: 'info', duration: 2000 });
        // Reload the file content
        const fe = this.fileEditors.find((f) => f.filename === filename);
        if (fe) {
          const fileResp = await fetch(`${API_URL}/api/settings/personality/files/${filename}`);
          if (fileResp.ok) {
            const data = await fileResp.json();
            fe.content = data.content || '';
            fe.exists = true;

            // Close editor if open
            this.toggleFileEditor(filename, false);

            // Update preview
            const previewEl = this.root.querySelector(`#preview-${filename}`) as HTMLElement;
            if (previewEl) {
              const preview = fe.content.length > 300 ? fe.content.substring(0, 300) + '...' : fe.content;
              const sizeKB = (fe.content.length / 1024).toFixed(1);
              previewEl.innerHTML = `<span class="file-exists">✓ ${sizeKB} KB</span>\n${this.escapeHtml(preview)}`;
            }
          }
        }
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (e) {
      console.error(`Failed to reset ${filename}:`, e);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `Failed to reset ${filename}`, type: 'error', duration: 4000 });
    }
  }

  destroy(): void {
    this.root.remove();
  }
}
