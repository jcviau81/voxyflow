/**
 * SettingsPage — Full settings UI with personality configuration, connection, and data management.
 */

import { createElement } from '../../utils/helpers';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, API_URL } from '../../utils/constants';
import { appState } from '../../state/AppState';
import { apiClient } from '../../services/ApiClient';
import { ttsService } from '../../services/TtsService';
import { sttService } from '../../services/SttService';
import { jobsService, Job, ServiceHealth } from '../../services/JobsService';
import {
  themeService,
  ACCENT_PRESETS,
  type FontSize,
  type SidebarWidth,
  type CardDensity,
  type AnimationSpeed,
} from '../../services/ThemeService';

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

interface ModelLayerConfig {
  provider_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
}

interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;
  analyzer: ModelLayerConfig;
}

interface VoiceSettings {
  stt_engine: 'native' | 'whisper';
  stt_model: string;
  stt_language: string;
  tts_enabled: boolean;
  tts_auto_play: boolean;
  tts_url: string;
  tts_voice: string;
  tts_speed: number;
  volume: number;
}

interface AppSettings {
  personality: PersonalitySettings;
  models?: ModelsSettings;
  voice?: VoiceSettings;
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

const DEFAULT_MODEL_LAYER: ModelLayerConfig = {
  provider_url: 'http://localhost:3456/v1',
  api_key: '',
  model: '',
  enabled: true,
};

const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  stt_engine: 'native',
  stt_model: 'medium',
  stt_language: 'auto',
  tts_enabled: true,
  tts_auto_play: false,
  tts_url: 'http://192.168.1.59:5500',
  tts_voice: 'default',
  tts_speed: 1.0,
  volume: 80,
};

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
  models: {
    fast: { ...DEFAULT_MODEL_LAYER, model: 'claude-sonnet-4' },
    deep: { ...DEFAULT_MODEL_LAYER, model: 'claude-opus-4' },
    analyzer: { ...DEFAULT_MODEL_LAYER, model: 'claude-haiku-4' },
  },
  voice: { ...DEFAULT_VOICE_SETTINGS },
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

  // Jobs state
  private jobs: Job[] = [];
  private jobsLoading = false;
  private showAddJobForm = false;
  private jobsHealthInterval: ReturnType<typeof setInterval> | null = null;

  // Health state
  private serviceHealth: ServiceHealth[] = [];

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
        const dm = DEFAULT_SETTINGS.models!;
        const sm = data.models || {};
        this.settings = {
          ...DEFAULT_SETTINGS,
          ...data,
          personality: { ...DEFAULT_SETTINGS.personality, ...(data.personality || {}) },
          models: {
            fast: { ...dm.fast, ...(sm.fast || {}) },
            deep: { ...dm.deep, ...(sm.deep || {}) },
            analyzer: { ...dm.analyzer, ...(sm.analyzer || {}) },
          },
          voice: { ...DEFAULT_VOICE_SETTINGS, ...(data.voice || {}) },
        };
      }
    } catch (e) {
      console.warn('Failed to load settings, using defaults:', e);
    }
    this.render();
    this.loadPreviews();
    this.loadJobs();
    this.loadServiceHealth();
    // Refresh health every 30 seconds
    this.jobsHealthInterval = setInterval(() => this.loadServiceHealth(), 30_000);
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

      const previewEl = document.getElementById(`preview-${fe.filename}`) as HTMLElement;
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

    // Header with back button
    const header = createElement('div', { className: 'settings-header' });
    const backBtn = createElement('button', { className: 'settings-back-btn' }, '← Back');
    backBtn.addEventListener('click', () => appState.setView('chat'));
    const title = createElement('h2', {}, '\u2699\uFE0F Settings');
    header.appendChild(backBtn);
    header.appendChild(title);
    this.root.appendChild(header);

    this.root.insertAdjacentHTML('beforeend', this.renderHealthBar());
    this.root.insertAdjacentHTML('beforeend', this.renderAppearanceSection());
    this.root.insertAdjacentHTML('beforeend', this.renderPersonalitySection());
    this.root.insertAdjacentHTML('beforeend', this.renderModelsSection());
    this.root.insertAdjacentHTML('beforeend', this.renderGitHubSection());
    this.root.insertAdjacentHTML('beforeend', this.renderVoiceSection());
    this.root.insertAdjacentHTML('beforeend', this.renderConnectionSection());
    this.root.insertAdjacentHTML('beforeend', this.renderDataSection());
    this.root.insertAdjacentHTML('beforeend', this.renderJobsSection());
    this.root.insertAdjacentHTML('beforeend', this.renderAboutSection());
    this.root.insertAdjacentHTML('beforeend', this.renderSaveBar());

    this.bindEvents();
  }

  // ── Appearance Section ─────────────────────────────────────────────────────

  private renderAppearanceSection(): string {
    const currentTheme  = appState.get('theme') || 'dark';
    const currentAccent = themeService.accentColor;
    const currentFont   = themeService.fontSize;
    const currentSidebar = themeService.sidebarWidth;
    const currentDensity = themeService.cardDensity;
    const currentAnim    = themeService.animationSpeed;

    const swatchesHtml = ACCENT_PRESETS.map(({ name, value }) => `
      <button
        class="accent-swatch ${currentAccent.toLowerCase() === value ? 'active' : ''}"
        style="background:${value};"
        title="${name}"
        data-accent="${value}"
        aria-label="Accent color: ${name}"
      ></button>
    `).join('');

    const fontPills   = (['small', 'medium', 'large'] as FontSize[]).map((v) =>
      `<button class="appearance-pill ${currentFont === v ? 'active' : ''}" data-font-size="${v}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`
    ).join('');

    const sidebarPills = (['compact', 'normal', 'wide'] as SidebarWidth[]).map((v) =>
      `<button class="appearance-pill ${currentSidebar === v ? 'active' : ''}" data-sidebar-width="${v}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`
    ).join('');

    const densityPills = (['comfortable', 'compact'] as CardDensity[]).map((v) =>
      `<button class="appearance-pill ${currentDensity === v ? 'active' : ''}" data-card-density="${v}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`
    ).join('');

    const animPills = (['off', 'normal', 'snappy'] as AnimationSpeed[]).map((v) =>
      `<button class="appearance-pill ${currentAnim === v ? 'active' : ''}" data-anim-speed="${v}">${v.charAt(0).toUpperCase() + v.slice(1)}</button>`
    ).join('');

    return `
      <div class="settings-section" data-testid="settings-appearance">
        <h3>🎨 Appearance</h3>
        <div class="appearance-grid">

          <!-- Theme -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Theme</div>
              <div class="setting-description">Dark or Light interface</div>
            </div>
            <div class="appearance-pills">
              <button class="appearance-pill ${currentTheme === 'dark'  ? 'active' : ''}" data-theme-toggle="dark">🌙 Dark</button>
              <button class="appearance-pill ${currentTheme === 'light' ? 'active' : ''}" data-theme-toggle="light">☀️ Light</button>
            </div>
          </div>

          <!-- Accent Color -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Accent Color</div>
              <div class="setting-description">UI highlight color — changes live</div>
            </div>
            <div class="accent-swatches">${swatchesHtml}</div>
          </div>

          <!-- Font Size -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Font Size</div>
              <div class="setting-description">Small (12px) · Medium (16px) · Large (20px)</div>
            </div>
            <div class="appearance-pills">${fontPills}</div>
          </div>

          <!-- Sidebar Width -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Sidebar Width</div>
              <div class="setting-description">Compact (220px) · Normal (280px) · Wide (360px)</div>
            </div>
            <div class="appearance-pills">${sidebarPills}</div>
          </div>

          <!-- Card Density -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Card Density</div>
              <div class="setting-description">Comfortable keeps full padding; Compact is tighter</div>
            </div>
            <div class="appearance-pills">${densityPills}</div>
          </div>

          <!-- Animation Speed -->
          <div class="setting-row">
            <div class="setting-info">
              <div class="setting-label">Animation Speed</div>
              <div class="setting-description">Off disables all transitions</div>
            </div>
            <div class="appearance-pills">${animPills}</div>
          </div>

        </div>
      </div>
    `;
  }

  private bindAppearanceEvents(): void {
    const section = this.root.querySelector('[data-testid="settings-appearance"]');
    if (!section) return;

    // Theme toggle
    section.querySelectorAll<HTMLButtonElement>('[data-theme-toggle]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const theme = btn.dataset.themeToggle as 'dark' | 'light';
        appState.setTheme(theme);
        // Update pill active states
        section.querySelectorAll<HTMLButtonElement>('[data-theme-toggle]').forEach((b) => {
          b.classList.toggle('active', b.dataset.themeToggle === theme);
        });
      });
    });

    // Accent swatches
    section.querySelectorAll<HTMLButtonElement>('[data-accent]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const hex = btn.dataset.accent!;
        themeService.setAccentColor(hex);
        section.querySelectorAll<HTMLButtonElement>('[data-accent]').forEach((b) => {
          b.classList.toggle('active', b.dataset.accent === hex);
        });
      });
    });

    // Font size pills
    section.querySelectorAll<HTMLButtonElement>('[data-font-size]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const size = btn.dataset.fontSize as FontSize;
        themeService.setFontSize(size);
        section.querySelectorAll<HTMLButtonElement>('[data-font-size]').forEach((b) => {
          b.classList.toggle('active', b.dataset.fontSize === size);
        });
      });
    });

    // Sidebar width pills
    section.querySelectorAll<HTMLButtonElement>('[data-sidebar-width]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const width = btn.dataset.sidebarWidth as SidebarWidth;
        themeService.setSidebarWidth(width);
        section.querySelectorAll<HTMLButtonElement>('[data-sidebar-width]').forEach((b) => {
          b.classList.toggle('active', b.dataset.sidebarWidth === width);
        });
      });
    });

    // Card density pills
    section.querySelectorAll<HTMLButtonElement>('[data-card-density]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const density = btn.dataset.cardDensity as CardDensity;
        themeService.setCardDensity(density);
        section.querySelectorAll<HTMLButtonElement>('[data-card-density]').forEach((b) => {
          b.classList.toggle('active', b.dataset.cardDensity === density);
        });
      });
    });

    // Animation speed pills
    section.querySelectorAll<HTMLButtonElement>('[data-anim-speed]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const speed = btn.dataset.animSpeed as AnimationSpeed;
        themeService.setAnimationSpeed(speed);
        section.querySelectorAll<HTMLButtonElement>('[data-anim-speed]').forEach((b) => {
          b.classList.toggle('active', b.dataset.animSpeed === speed);
        });
      });
    });
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

  private renderModelLayerFields(
    layerKey: 'fast' | 'deep' | 'analyzer',
    label: string,
    showEnabled: boolean,
    placeholderModel: string,
  ): string {
    const m = this.settings.models?.[layerKey] ?? { ...DEFAULT_MODEL_LAYER };
    const enabledRow = showEnabled ? `
      <div class="setting-row">
        <div class="setting-info">
          <div class="setting-label">Enabled</div>
          <div class="setting-description">Enable this layer</div>
        </div>
        <input type="checkbox" class="setting-checkbox" data-model-layer="${layerKey}" data-model-field="enabled"
          ${m.enabled ? 'checked' : ''} />
      </div>` : '';

    return `
      <div class="settings-subsection">
        <h4>${label}</h4>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Provider URL</div>
            <div class="setting-description">OpenAI-compatible API base URL</div>
          </div>
          <input type="text" class="setting-input" data-model-layer="${layerKey}" data-model-field="provider_url"
            value="${this.escapeHtml(m.provider_url)}"
            placeholder="http://localhost:3456/v1" />
        </div>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">API Key</div>
            <div class="setting-description">Leave empty if not required (e.g. Ollama)</div>
          </div>
          <input type="password" class="setting-input" data-model-layer="${layerKey}" data-model-field="api_key"
            value="${this.escapeHtml(m.api_key)}"
            placeholder="Leave empty if not required"
            autocomplete="new-password" />
        </div>
        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Model Name</div>
            <div class="setting-description">Model identifier for this layer</div>
          </div>
          <input type="text" class="setting-input" data-model-layer="${layerKey}" data-model-field="model"
            value="${this.escapeHtml(m.model)}"
            placeholder="${placeholderModel}" />
        </div>
        ${enabledRow}
      </div>
    `;
  }

  private renderModelsSection(): string {
    return `
      <div class="settings-section" data-testid="settings-models">
        <h3>🤖 Models</h3>
        <p style="color: var(--color-text-secondary); font-size: 13px; margin-bottom: 16px;">
          Configure which LLM provider and model handles each layer.
          Leave fields empty to use the defaults from config.
        </p>
        ${this.renderModelLayerFields('fast', '⚡ Conversational (Fast)', false, 'claude-sonnet-4')}
        ${this.renderModelLayerFields('deep', '🧠 Deep Thinking', true, 'claude-opus-4')}
        ${this.renderModelLayerFields('analyzer', '🔍 Analyzer', true, 'claude-haiku-4')}
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

  private renderVoiceSection(): string {
    const v = this.settings.voice ?? { ...DEFAULT_VOICE_SETTINGS };
    const sttEngine = v.stt_engine ?? 'native';
    const whisperModelHidden = sttEngine !== 'whisper' ? 'style="display:none"' : '';

    const langOptions = [
      { value: 'auto', label: 'Auto' },
      { value: 'en', label: 'English' },
      { value: 'fr', label: 'French' },
      { value: 'es', label: 'Spanish' },
      { value: 'de', label: 'German' },
      { value: 'ja', label: 'Japanese' },
      { value: 'zh', label: 'Chinese' },
    ].map(({ value, label }) =>
      `<option value="${value}" ${(v.stt_language ?? 'auto') === value ? 'selected' : ''}>${label}</option>`
    ).join('');

    return `
      <div class="settings-section" data-testid="settings-voice">
        <h3>🎤 Voice</h3>

        <!-- ── STT subsection ─────────────────────────────────── -->
        <div class="settings-subsection-label">Speech-to-Text (STT)</div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Engine</div>
            <div class="setting-description">Native: Web Speech API (fast, browser-based) · Whisper: server transcription (better accuracy, offline)</div>
          </div>
          <div class="appearance-pills">
            <button class="appearance-pill ${sttEngine === 'native' ? 'active' : ''}" data-stt-engine="native">Native (Browser)</button>
            <button class="appearance-pill ${sttEngine === 'whisper' ? 'active' : ''}" data-stt-engine="whisper">Whisper (Server)</button>
          </div>
        </div>

        <div class="setting-row" id="voice-whisper-model-row" ${whisperModelHidden}>
          <div class="setting-info">
            <div class="setting-label">Whisper Model</div>
            <div class="setting-description">Model name (e.g. tiny, base, small, medium, large-v3, turbo)</div>
          </div>
          <input type="text" class="setting-input" id="voice-stt-model"
            value="${this.escapeHtml(v.stt_model ?? 'medium')}"
            placeholder="medium" />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Language</div>
            <div class="setting-description">Recognition language for both Native and Whisper engines</div>
          </div>
          <select class="setting-select" id="voice-stt-language">
            ${langOptions}
          </select>
        </div>

        <!-- ── TTS subsection ─────────────────────────────────── -->
        <div class="settings-subsection-label" style="margin-top: 20px;">Text-to-Speech (TTS)</div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Enable TTS</div>
            <div class="setting-description">Allow text-to-speech on assistant messages</div>
          </div>
          <input type="checkbox" class="setting-checkbox" id="voice-tts-enabled" ${v.tts_enabled ? 'checked' : ''} />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Auto-play responses</div>
            <div class="setting-description">Read Voxy's responses aloud automatically</div>
          </div>
          <input type="checkbox" class="setting-checkbox" id="voice-tts-autoplay" ${v.tts_auto_play ? 'checked' : ''} />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">TTS Service URL</div>
            <div class="setting-description">URL of your TTS server (XTTS, Coqui, etc.)</div>
          </div>
          <input type="text" class="setting-input" id="voice-tts-url"
            value="${this.escapeHtml(v.tts_url ?? 'http://192.168.1.59:5500')}"
            placeholder="http://192.168.1.59:5500" />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Voice</div>
            <div class="setting-description">Voice name or ID for the TTS server</div>
          </div>
          <input type="text" class="setting-input" id="voice-tts-voice"
            value="${this.escapeHtml(v.tts_voice ?? '')}"
            placeholder="default" />
        </div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Speed</div>
            <div class="setting-description">Playback speed — <span id="voice-tts-speed-label">${(v.tts_speed ?? 1.0).toFixed(1)}x</span></div>
          </div>
          <input type="range" class="setting-range" id="voice-tts-speed"
            min="0.5" max="2.0" step="0.1"
            value="${(v.tts_speed ?? 1.0).toFixed(1)}" />
        </div>

        <!-- ── Volume subsection ──────────────────────────────── -->
        <div class="settings-subsection-label" style="margin-top: 20px;">Volume</div>

        <div class="setting-row">
          <div class="setting-info">
            <div class="setting-label">Audio volume</div>
            <div class="setting-description">TTS and notification volume — <span id="voice-volume-label">${v.volume ?? 80}%</span></div>
          </div>
          <input type="range" class="setting-range" id="voice-volume-slider"
            min="0" max="100"
            value="${v.volume ?? 80}" />
        </div>

        <div style="display: flex; gap: 12px; align-items: center; margin-top: 12px;">
          <button class="btn-ghost" id="voice-tts-test-btn">🔊 Test TTS</button>
          <span id="voice-tts-test-result" style="font-size: 13px; color: var(--color-text-secondary);"></span>
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

  // ── Health Bar ─────────────────────────────────────────────────────────────

  private renderHealthBar(): string {
    const dots = this.serviceHealth.length === 0
      ? '<span class="health-dot" style="color: var(--color-text-muted);">Checking…</span>'
      : this.serviceHealth.map((s) => `
          <span class="health-dot ${s.status === 'ok' ? 'ok' : 'down'}">
            <span class="health-dot-indicator"></span>
            ${this.escapeHtml(s.name)}
          </span>
        `).join('');

    return `
      <div class="health-status-bar" id="health-status-bar">
        <span class="health-status-bar-label">🟢 Services</span>
        ${dots}
      </div>
    `;
  }

  private async loadServiceHealth(): Promise<void> {
    try {
      const response = await fetch(`${API_URL}/api/health/services`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as { services?: Record<string, { status: string; checked_at?: string }> };
      // Convert dict to array
      const svcDict = data.services || {};
      this.serviceHealth = Object.entries(svcDict).map(([name, info]) => ({
        name: name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        status: (info.status === 'ok' ? 'ok' : 'down') as 'ok' | 'down',
      }));
    } catch {
      // If endpoint doesn't exist or fails, show defaults as unknown
      this.serviceHealth = [
        { name: 'Claude Proxy', status: 'down' },
        { name: 'XTTS', status: 'down' },
        { name: 'ChromaDB', status: 'down' },
      ];
    }
    this.refreshHealthBar();
  }

  private refreshHealthBar(): void {
    const bar = this.root.querySelector('#health-status-bar');
    if (!bar) return;
    const parent = bar.parentElement;
    if (!parent) return;
    const next = bar.nextSibling;
    bar.remove();
    const tmp = document.createElement('div');
    tmp.innerHTML = this.renderHealthBar();
    const newBar = tmp.firstElementChild!;
    parent.insertBefore(newBar, next);
  }

  // ── Jobs Section ───────────────────────────────────────────────────────────

  private renderJobsSection(): string {
    const jobsListHtml = this.jobsLoading
      ? '<div class="jobs-loading">Loading jobs…</div>'
      : this.jobs.length === 0
        ? '<div class="jobs-empty-state">No scheduled jobs. Add one to automate tasks.</div>'
        : `<div class="jobs-list">${this.jobs.map((job) => this.renderJobItem(job)).join('')}</div>`;

    const addFormHtml = this.showAddJobForm ? this.renderAddJobForm() : '';

    return `
      <div class="settings-section jobs-section" data-testid="settings-jobs">
        <h3>⏰ Scheduled Jobs</h3>
        ${jobsListHtml}
        ${addFormHtml}
        ${!this.showAddJobForm ? `
          <button class="btn-secondary" id="jobs-add-btn" style="margin-top: 8px;">+ Add Job</button>
        ` : ''}
      </div>
    `;
  }

  private renderJobItem(job: Job): string {
    const lastRunText = job.last_run
      ? `Last: ${new Date(job.last_run).toLocaleString()}`
      : 'Never run';

    return `
      <div class="job-item" data-job-id="${this.escapeHtml(job.id)}">
        <input
          type="checkbox"
          class="setting-checkbox job-item-toggle"
          data-job-toggle="${this.escapeHtml(job.id)}"
          title="Enable/disable"
          ${job.enabled ? 'checked' : ''}
        />
        <div class="job-item-info">
          <div class="job-item-name">${this.escapeHtml(job.name)}</div>
          <div class="job-item-meta">
            <span class="job-item-type">${this.escapeHtml(job.type)}</span>
            <span class="job-item-schedule">${this.escapeHtml(job.schedule)}</span>
            <span class="job-item-lastrun">${lastRunText}</span>
          </div>
        </div>
        <div class="job-item-actions">
          <button class="btn-sm" data-job-run="${this.escapeHtml(job.id)}" title="Run now">▶️</button>
          <button class="btn-sm btn-danger-sm" data-job-delete="${this.escapeHtml(job.id)}" title="Delete">🗑️</button>
        </div>
      </div>
    `;
  }

  private renderAddJobForm(): string {
    return `
      <div class="job-add-form" id="job-add-form">
        <div class="job-add-form-title">New Scheduled Job</div>
        <div class="job-form-grid">
          <div class="job-form-row">
            <label for="job-form-name">Name</label>
            <input type="text" id="job-form-name" class="setting-input" placeholder="Daily standup reminder" />
          </div>
          <div class="job-form-row">
            <label for="job-form-type">Type</label>
            <select id="job-form-type" class="setting-select">
              <option value="reminder">reminder</option>
              <option value="github_sync">github_sync</option>
              <option value="rag_index">rag_index</option>
              <option value="custom">custom</option>
            </select>
          </div>
          <div class="job-form-row">
            <label for="job-form-schedule">Schedule</label>
            <input type="text" id="job-form-schedule" class="setting-input" placeholder="0 9 * * 1-5" />
            <span class="job-form-hint">Cron or: every_30min, every_hour, every_day</span>
          </div>
          <div class="job-form-row" style="justify-content: flex-end;">
            <label>&nbsp;</label>
            <div class="job-form-enabled-row">
              <input type="checkbox" id="job-form-enabled" checked />
              <span>Enabled</span>
            </div>
          </div>
        </div>
        <div class="job-form-footer">
          <button class="btn-primary btn-sm" id="job-form-submit">Create Job</button>
          <button class="btn-ghost btn-sm" id="job-form-cancel">Cancel</button>
          <span id="job-form-error" style="font-size: 12px; color: var(--color-error, #ff6b6b);"></span>
        </div>
      </div>
    `;
  }

  private async loadJobs(): Promise<void> {
    this.jobsLoading = true;
    this.refreshJobsSection();
    try {
      this.jobs = await jobsService.getJobs();
    } catch (e) {
      console.warn('[SettingsPage] Failed to load jobs:', e);
      this.jobs = [];
    }
    this.jobsLoading = false;
    this.refreshJobsSection();
  }

  private refreshJobsSection(): void {
    const section = this.root.querySelector('[data-testid="settings-jobs"]');
    if (!section) return;
    const parent = section.parentElement;
    if (!parent) return;
    const next = section.nextSibling;
    section.remove();
    const tmp = document.createElement('div');
    tmp.innerHTML = this.renderJobsSection();
    const newSection = tmp.firstElementChild!;
    parent.insertBefore(newSection, next);
    this.bindJobsEvents();
  }

  private bindJobsEvents(): void {
    const addBtn = this.root.querySelector('#jobs-add-btn');
    if (addBtn) {
      addBtn.addEventListener('click', () => {
        this.showAddJobForm = true;
        this.refreshJobsSection();
      });
    }

    const cancelBtn = this.root.querySelector('#job-form-cancel');
    if (cancelBtn) {
      cancelBtn.addEventListener('click', () => {
        this.showAddJobForm = false;
        this.refreshJobsSection();
      });
    }

    const submitBtn = this.root.querySelector('#job-form-submit');
    if (submitBtn) {
      submitBtn.addEventListener('click', () => this.handleCreateJob());
    }

    // Toggle enabled
    this.root.querySelectorAll('[data-job-toggle]').forEach((el) => {
      el.addEventListener('change', async (e) => {
        const id = (el as HTMLElement).dataset.jobToggle!;
        const enabled = (e.target as HTMLInputElement).checked;
        try {
          const updated = await jobsService.updateJob(id, { enabled });
          const idx = this.jobs.findIndex((j) => j.id === id);
          if (idx !== -1) this.jobs[idx] = updated;
          this.refreshJobsSection();
        } catch (err) {
          console.error('[SettingsPage] Failed to toggle job:', err);
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to update job', type: 'error', duration: 3000 });
        }
      });
    });

    // Run now
    this.root.querySelectorAll('[data-job-run]').forEach((el) => {
      el.addEventListener('click', async () => {
        const id = (el as HTMLElement).dataset.jobRun!;
        const btn = el as HTMLButtonElement;
        btn.disabled = true;
        try {
          await jobsService.runJob(id);
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Job triggered!', type: 'success', duration: 2000 });
          await this.loadJobs();
        } catch (err) {
          console.error('[SettingsPage] Failed to run job:', err);
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to run job', type: 'error', duration: 3000 });
        } finally {
          btn.disabled = false;
        }
      });
    });

    // Delete
    this.root.querySelectorAll('[data-job-delete]').forEach((el) => {
      el.addEventListener('click', async () => {
        const id = (el as HTMLElement).dataset.jobDelete!;
        const job = this.jobs.find((j) => j.id === id);
        if (!confirm(`Delete job "${job?.name || id}"?`)) return;
        try {
          await jobsService.deleteJob(id);
          this.jobs = this.jobs.filter((j) => j.id !== id);
          this.refreshJobsSection();
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Job deleted', type: 'info', duration: 2000 });
        } catch (err) {
          console.error('[SettingsPage] Failed to delete job:', err);
          eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to delete job', type: 'error', duration: 3000 });
        }
      });
    });
  }

  private async handleCreateJob(): Promise<void> {
    const nameEl = this.root.querySelector('#job-form-name') as HTMLInputElement | null;
    const typeEl = this.root.querySelector('#job-form-type') as HTMLSelectElement | null;
    const scheduleEl = this.root.querySelector('#job-form-schedule') as HTMLInputElement | null;
    const enabledEl = this.root.querySelector('#job-form-enabled') as HTMLInputElement | null;
    const errorEl = this.root.querySelector('#job-form-error') as HTMLElement | null;
    const submitBtn = this.root.querySelector('#job-form-submit') as HTMLButtonElement | null;

    const name = nameEl?.value.trim() ?? '';
    const type = (typeEl?.value ?? 'custom') as Job['type'];
    const schedule = scheduleEl?.value.trim() ?? '';
    const enabled = enabledEl?.checked ?? true;

    if (!name) {
      if (errorEl) errorEl.textContent = 'Name is required';
      return;
    }
    if (!schedule) {
      if (errorEl) errorEl.textContent = 'Schedule is required';
      return;
    }

    if (submitBtn) submitBtn.disabled = true;
    if (errorEl) errorEl.textContent = '';

    try {
      const newJob = await jobsService.createJob({ name, type, schedule, enabled, payload: {} });
      this.jobs.push(newJob);
      this.showAddJobForm = false;
      this.refreshJobsSection();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `Job "${name}" created!`, type: 'success', duration: 2000 });
    } catch (err) {
      console.error('[SettingsPage] Failed to create job:', err);
      if (errorEl) errorEl.textContent = 'Failed to create job. Check console.';
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  private renderAboutSection(): string {
    return `
      <div class="settings-section" style="border-bottom: none;">
        <h3>\u2139\uFE0F About Voxyflow</h3>
        <p style="color: var(--color-text-secondary); font-size: 13px; line-height: 1.6;">
          Voice-first project assistant<br>
          Version: 1.0.0
        </p>
        <div class="setting-row" style="margin-top: 16px;">
          <div class="setting-info">
            <div class="setting-label">Reset Onboarding</div>
            <div class="setting-description">Show the first-launch setup screen again on next reload</div>
          </div>
          <button class="settings-btn" id="reset-onboarding-btn">Reset Onboarding</button>
        </div>
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
    this.bindAppearanceEvents();

    this.root.querySelectorAll('[data-field]').forEach((el) => {
      el.addEventListener('input', () => this.markDirty());
      el.addEventListener('change', () => this.markDirty());
    });

    this.root.querySelectorAll('[data-model-layer]').forEach((el) => {
      el.addEventListener('input', () => this.markDirty());
      el.addEventListener('change', () => this.markDirty());
    });

    this.bindVoiceEvents();

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

    // Reset onboarding button
    const resetOnboardingBtn = this.root.querySelector('#reset-onboarding-btn');
    if (resetOnboardingBtn) {
      resetOnboardingBtn.addEventListener('click', () => this.resetOnboarding());
    }

    // Jobs events (jobs section may not be populated yet, bindJobsEvents handles it)
    this.bindJobsEvents();
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

  private bindVoiceEvents(): void {
    // STT engine pills
    this.root.querySelectorAll<HTMLButtonElement>('[data-stt-engine]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const engine = btn.dataset.sttEngine as 'native' | 'whisper';

        // Update pill active states
        this.root.querySelectorAll<HTMLButtonElement>('[data-stt-engine]').forEach((b) => {
          b.classList.toggle('active', b.dataset.sttEngine === engine);
        });

        // Show/hide Whisper model row
        const whisperRow = this.root.querySelector<HTMLElement>('#voice-whisper-model-row');
        if (whisperRow) {
          whisperRow.style.display = engine === 'whisper' ? '' : 'none';
        }

        // Apply immediately
        sttService.setEngine(engine === 'whisper' ? 'whisper' : 'webspeech');

        // Mark dirty so Save persists
        this.markDirty();
      });
    });

    // STT language
    const langSelect = this.root.querySelector<HTMLSelectElement>('#voice-stt-language');
    if (langSelect) {
      langSelect.addEventListener('change', () => {
        const lang = langSelect.value;
        // Map code to BCP-47 for native engine
        const langMap: Record<string, string> = {
          auto: 'en-US', en: 'en-US', fr: 'fr-CA', es: 'es-ES',
          de: 'de-DE', ja: 'ja-JP', zh: 'zh-CN',
        };
        sttService.setLanguage(langMap[lang] ?? lang);
        this.markDirty();
      });
    }

    // Whisper model
    const modelInput = this.root.querySelector<HTMLInputElement>('#voice-stt-model');
    if (modelInput) {
      modelInput.addEventListener('input', () => this.markDirty());
    }

    // TTS enabled
    const ttsEnabled = this.root.querySelector<HTMLInputElement>('#voice-tts-enabled');
    if (ttsEnabled) {
      ttsEnabled.addEventListener('change', () => {
        ttsService.setEnabled(ttsEnabled.checked);
        this.markDirty();
      });
    }

    // TTS auto-play
    const ttsAutoplay = this.root.querySelector<HTMLInputElement>('#voice-tts-autoplay');
    if (ttsAutoplay) {
      ttsAutoplay.addEventListener('change', () => this.markDirty());
    }

    // TTS URL / voice
    ['#voice-tts-url', '#voice-tts-voice'].forEach((sel) => {
      const el = this.root.querySelector<HTMLInputElement>(sel);
      if (el) el.addEventListener('input', () => this.markDirty());
    });

    // TTS speed slider
    const speedSlider = this.root.querySelector<HTMLInputElement>('#voice-tts-speed');
    const speedLabel = this.root.querySelector<HTMLElement>('#voice-tts-speed-label');
    if (speedSlider) {
      speedSlider.addEventListener('input', () => {
        const val = parseFloat(speedSlider.value).toFixed(1);
        if (speedLabel) speedLabel.textContent = `${val}x`;
        this.markDirty();
      });
    }

    // Volume slider
    const volSlider = this.root.querySelector<HTMLInputElement>('#voice-volume-slider');
    const volLabel = this.root.querySelector<HTMLElement>('#voice-volume-label');
    if (volSlider) {
      volSlider.addEventListener('input', () => {
        const val = parseInt(volSlider.value);
        if (volLabel) volLabel.textContent = `${val}%`;
        appState.set('volume', val / 100);
        this.markDirty();
      });
    }

    // TTS test button
    const ttsTestBtn = this.root.querySelector('#voice-tts-test-btn');
    if (ttsTestBtn) {
      ttsTestBtn.addEventListener('click', () => this.testTts());
    }
  }

  private async testTts(): Promise<void> {
    const resultEl = this.root.querySelector('#voice-tts-test-result') as HTMLElement | null;
    if (resultEl) resultEl.textContent = 'Testing…';

    try {
      await ttsService.speak('Voxyflow TTS test. Hello!');
      if (resultEl) resultEl.textContent = '✓ Playing';
      setTimeout(() => { if (resultEl) resultEl.textContent = ''; }, 3000);
    } catch (e) {
      if (resultEl) resultEl.textContent = '✗ Failed (server may be down)';
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

    // Collect model layer settings
    const layers: Array<'fast' | 'deep' | 'analyzer'> = ['fast', 'deep', 'analyzer'];
    const models: ModelsSettings = {
      fast: { ...DEFAULT_MODEL_LAYER, model: 'claude-sonnet-4' },
      deep: { ...DEFAULT_MODEL_LAYER, model: 'claude-opus-4' },
      analyzer: { ...DEFAULT_MODEL_LAYER, model: 'claude-haiku-4' },
    };

    for (const layer of layers) {
      const urlEl = this.root.querySelector(`[data-model-layer="${layer}"][data-model-field="provider_url"]`) as HTMLInputElement | null;
      const keyEl = this.root.querySelector(`[data-model-layer="${layer}"][data-model-field="api_key"]`) as HTMLInputElement | null;
      const modelEl = this.root.querySelector(`[data-model-layer="${layer}"][data-model-field="model"]`) as HTMLInputElement | null;
      const enabledEl = this.root.querySelector(`[data-model-layer="${layer}"][data-model-field="enabled"]`) as HTMLInputElement | null;

      models[layer] = {
        provider_url: urlEl?.value ?? models[layer].provider_url,
        api_key: keyEl?.value ?? '',
        model: modelEl?.value ?? models[layer].model,
        enabled: enabledEl ? enabledEl.checked : true,
      };
    }

    // Collect voice settings
    const sttEngineEl = this.root.querySelector<HTMLButtonElement>('[data-stt-engine].active');
    const sttEngine = (sttEngineEl?.dataset.sttEngine ?? this.settings.voice?.stt_engine ?? 'native') as 'native' | 'whisper';
    const sttModelEl = this.root.querySelector<HTMLInputElement>('#voice-stt-model');
    const sttLangEl = this.root.querySelector<HTMLSelectElement>('#voice-stt-language');
    const ttsEnabledEl = this.root.querySelector<HTMLInputElement>('#voice-tts-enabled');
    const ttsAutoPlayEl = this.root.querySelector<HTMLInputElement>('#voice-tts-autoplay');
    const ttsUrlEl = this.root.querySelector<HTMLInputElement>('#voice-tts-url');
    const ttsVoiceEl = this.root.querySelector<HTMLInputElement>('#voice-tts-voice');
    const ttsSpeedEl = this.root.querySelector<HTMLInputElement>('#voice-tts-speed');
    const volSliderEl = this.root.querySelector<HTMLInputElement>('#voice-volume-slider');

    const voice: VoiceSettings = {
      stt_engine: sttEngine,
      stt_model: sttModelEl?.value.trim() ?? this.settings.voice?.stt_model ?? 'medium',
      stt_language: sttLangEl?.value ?? this.settings.voice?.stt_language ?? 'auto',
      tts_enabled: ttsEnabledEl ? ttsEnabledEl.checked : (this.settings.voice?.tts_enabled ?? true),
      tts_auto_play: ttsAutoPlayEl ? ttsAutoPlayEl.checked : (this.settings.voice?.tts_auto_play ?? false),
      tts_url: ttsUrlEl?.value.trim() || (this.settings.voice?.tts_url ?? 'http://192.168.1.59:5500'),
      tts_voice: ttsVoiceEl?.value.trim() || (this.settings.voice?.tts_voice ?? 'default'),
      tts_speed: ttsSpeedEl ? parseFloat(ttsSpeedEl.value) : (this.settings.voice?.tts_speed ?? 1.0),
      volume: volSliderEl ? parseInt(volSliderEl.value) : (this.settings.voice?.volume ?? 80),
    };

    return {
      personality: { ...this.settings.personality, ...personality } as PersonalitySettings,
      models,
      voice,
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

  private async resetOnboarding(): Promise<void> {
    if (!confirm('Reset onboarding? The setup screen will appear on next reload.')) return;

    try {
      const response = await fetch(`${API_URL}/api/settings`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      data.onboarding_complete = false;

      const saveResponse = await fetch(`${API_URL}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!saveResponse.ok) throw new Error(`HTTP ${saveResponse.status}`);

      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Onboarding reset! Reloading...', type: 'success', duration: 2000 });
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      console.error('[SettingsPage] Failed to reset onboarding:', e);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Failed to reset onboarding', type: 'error', duration: 3000 });
    }
  }

  private resetSettings(): void {
    if (!confirm('Reset all settings to defaults?')) return;

    this.settings = JSON.parse(JSON.stringify(DEFAULT_SETTINGS));
    this.render();
    this.loadPreviews();
    this.markDirty();
    eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Settings reset to defaults (save to persist)', type: 'info', duration: 3000 });
  }

  private toggleFileEditor(filename: string, open: boolean): void {
    const fe = this.fileEditors.find((f) => f.filename === filename);
    if (!fe) return;

    const editorEl = document.getElementById(`editor-${filename}`) as HTMLElement;
    const previewEl = document.getElementById(`preview-${filename}`) as HTMLElement;
    const textareaEl = document.getElementById(`textarea-${filename}`) as HTMLTextAreaElement;

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

    const textareaEl = document.getElementById(`textarea-${filename}`) as HTMLTextAreaElement;
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
        const previewEl = document.getElementById(`preview-${filename}`) as HTMLElement;
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
            const previewEl = document.getElementById(`preview-${filename}`) as HTMLElement;
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
    if (this.jobsHealthInterval) {
      clearInterval(this.jobsHealthInterval);
      this.jobsHealthInterval = null;
    }
    this.root.remove();
  }
}
