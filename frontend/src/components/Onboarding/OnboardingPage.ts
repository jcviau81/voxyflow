/**
 * OnboardingPage — First-launch setup form.
 * Single scrollable page, clean and simple. Collects essential config,
 * saves via /api/settings, then reloads into the main app.
 */

import { API_URL } from '../../utils/constants';

interface OnboardingData {
  user_name: string;
  assistant_name: string;
  api_url: string;
  api_key: string;
  fast_model: string;
  deep_model: string;
  theme: 'dark' | 'light';
  font_size: 'small' | 'medium' | 'large';
}

export class OnboardingPage {
  private root: HTMLElement;
  private data: OnboardingData = {
    user_name: '',
    assistant_name: 'Voxy',
    api_url: 'http://localhost:3456/v1',
    api_key: 'sk-any',
    fast_model: 'claude-sonnet-4-5',
    deep_model: 'claude-opus-4-5',
    theme: 'dark',
    font_size: 'medium',
  };

  constructor(container: HTMLElement) {
    this.root = container;
    this.render();
    this.bindEvents();
  }

  private render(): void {
    this.root.innerHTML = `
      <div class="onboarding-backdrop">
        <div class="onboarding-card">
          <div class="onboarding-header">
            <div class="onboarding-logo">🎙️</div>
            <h1 class="onboarding-title">Welcome to Voxyflow</h1>
            <p class="onboarding-subtitle">Your voice-first project assistant. Let's get you set up.</p>
          </div>

          <form class="onboarding-form" id="onboarding-form" autocomplete="off">
            <!-- Your Name -->
            <div class="onboarding-field">
              <label for="ob-user-name">Your name</label>
              <input type="text" id="ob-user-name" placeholder="What should I call you?"
                value="${this.esc(this.data.user_name)}" autofocus />
              <span class="onboarding-hint">Used to personalize your assistant</span>
            </div>

            <!-- Assistant Name -->
            <div class="onboarding-field">
              <label for="ob-assistant-name">Assistant name</label>
              <input type="text" id="ob-assistant-name" placeholder="Voxy"
                value="${this.esc(this.data.assistant_name)}" />
              <span class="onboarding-hint">Give your assistant a name</span>
            </div>

            <div class="onboarding-divider"></div>

            <!-- LLM API URL -->
            <div class="onboarding-field">
              <label for="ob-api-url">LLM API URL</label>
              <input type="text" id="ob-api-url"
                placeholder="http://localhost:3456/v1"
                value="${this.esc(this.data.api_url)}" />
              <span class="onboarding-hint">OpenAI-compatible API endpoint</span>
            </div>

            <!-- API Key -->
            <div class="onboarding-field">
              <label for="ob-api-key">API Key</label>
              <input type="text" id="ob-api-key"
                placeholder="sk-any"
                value="${this.esc(this.data.api_key)}" />
              <span class="onboarding-hint">Leave as-is for local proxies</span>
            </div>

            <!-- Fast Model -->
            <div class="onboarding-field">
              <label for="ob-fast-model">Fast model <span class="onboarding-tag">conversational</span></label>
              <input type="text" id="ob-fast-model"
                placeholder="claude-sonnet-4-5"
                value="${this.esc(this.data.fast_model)}" />
            </div>

            <!-- Deep Model -->
            <div class="onboarding-field">
              <label for="ob-deep-model">Deep model <span class="onboarding-tag">analysis</span></label>
              <input type="text" id="ob-deep-model"
                placeholder="claude-opus-4-5"
                value="${this.esc(this.data.deep_model)}" />
            </div>

            <div class="onboarding-divider"></div>

            <!-- Theme -->
            <div class="onboarding-field">
              <label>Theme</label>
              <div class="onboarding-pills" id="ob-theme-pills">
                <button type="button" class="onboarding-pill ${this.data.theme === 'dark' ? 'active' : ''}" data-theme="dark">🌙 Dark</button>
                <button type="button" class="onboarding-pill ${this.data.theme === 'light' ? 'active' : ''}" data-theme="light">☀️ Light</button>
              </div>
            </div>

            <!-- Font Size -->
            <div class="onboarding-field">
              <label>Font size</label>
              <div class="onboarding-pills" id="ob-font-pills">
                <button type="button" class="onboarding-pill ${this.data.font_size === 'small' ? 'active' : ''}" data-font="small">Small</button>
                <button type="button" class="onboarding-pill ${this.data.font_size === 'medium' ? 'active' : ''}" data-font="medium">Medium</button>
                <button type="button" class="onboarding-pill ${this.data.font_size === 'large' ? 'active' : ''}" data-font="large">Large</button>
              </div>
            </div>

            <!-- Submit -->
            <button type="submit" class="onboarding-submit" id="ob-submit">
              Let's go 🚀
            </button>
          </form>
        </div>
      </div>
    `;
  }

  private bindEvents(): void {
    // Theme pills
    this.root.querySelectorAll<HTMLButtonElement>('[data-theme]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.data.theme = btn.dataset.theme as 'dark' | 'light';
        this.root.querySelectorAll<HTMLButtonElement>('[data-theme]').forEach((b) =>
          b.classList.toggle('active', b.dataset.theme === this.data.theme));
        // Live preview
        document.documentElement.setAttribute('data-theme', this.data.theme);
      });
    });

    // Font size pills
    this.root.querySelectorAll<HTMLButtonElement>('[data-font]').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.data.font_size = btn.dataset.font as 'small' | 'medium' | 'large';
        this.root.querySelectorAll<HTMLButtonElement>('[data-font]').forEach((b) =>
          b.classList.toggle('active', b.dataset.font === this.data.font_size));
        // Live preview
        const sizeMap: Record<string, string> = { small: '15px', medium: '16px', large: '18px' };
        document.documentElement.style.setProperty('--font-size-base', sizeMap[this.data.font_size] || '16px');
      });
    });

    // Form submit
    const form = this.root.querySelector('#onboarding-form') as HTMLFormElement;
    form?.addEventListener('submit', (e) => {
      e.preventDefault();
      this.handleSubmit();
    });
  }

  private async handleSubmit(): Promise<void> {
    const submitBtn = this.root.querySelector('#ob-submit') as HTMLButtonElement;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Setting up...';
    }

    // Collect form values
    this.data.user_name = (this.root.querySelector('#ob-user-name') as HTMLInputElement)?.value.trim() || '';
    this.data.assistant_name = (this.root.querySelector('#ob-assistant-name') as HTMLInputElement)?.value.trim() || 'Voxy';
    this.data.api_url = (this.root.querySelector('#ob-api-url') as HTMLInputElement)?.value.trim() || 'http://localhost:3456/v1';
    this.data.api_key = (this.root.querySelector('#ob-api-key') as HTMLInputElement)?.value.trim() || 'sk-any';
    this.data.fast_model = (this.root.querySelector('#ob-fast-model') as HTMLInputElement)?.value.trim() || 'claude-sonnet-4-5';
    this.data.deep_model = (this.root.querySelector('#ob-deep-model') as HTMLInputElement)?.value.trim() || 'claude-opus-4-5';

    // Build settings payload
    const settings = {
      personality: {
        bot_name: this.data.assistant_name,
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
        fast: {
          provider_url: this.data.api_url,
          api_key: this.data.api_key,
          model: this.data.fast_model,
          enabled: true,
        },
        deep: {
          provider_url: this.data.api_url,
          api_key: this.data.api_key,
          model: this.data.deep_model,
          enabled: true,
        },
        analyzer: {
          provider_url: this.data.api_url,
          api_key: this.data.api_key,
          model: 'claude-haiku-4',
          enabled: true,
        },
      },
      voice: {
        stt_engine: 'native',
        stt_model: 'medium',
        stt_language: 'auto',
        tts_enabled: true,
        tts_auto_play: false,
        tts_url: 'http://192.168.1.59:5500',
        tts_voice: 'default',
        tts_speed: 1.0,
        volume: 80,
      },
      scheduler: {
        enabled: true,
        heartbeat_interval_minutes: 2,
        rag_index_interval_minutes: 15,
      },
      onboarding_complete: true,
      user_name: this.data.user_name,
      assistant_name: this.data.assistant_name,
    };

    try {
      // Save settings
      const response = await fetch(`${API_URL}/api/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      // Save theme to localStorage (ThemeService reads from there)
      localStorage.setItem('voxyflow-theme', this.data.theme);
      localStorage.setItem('voxyflow-font-size', this.data.font_size);

      // Update USER.md if user provided their name
      if (this.data.user_name) {
        try {
          await fetch(`${API_URL}/api/settings/personality/files/USER.md`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              content: `# USER.md — About You\n\n- **Name:** ${this.data.user_name}\n- **Preferred Language:** \n- **Timezone:** \n- **Notes:**\n\n## Preferences\n\n---\n_The more your assistant knows, the better it can help._\n`,
            }),
          });
        } catch {
          // Non-critical
        }
      }

      // Reload the app
      window.location.reload();
    } catch (e) {
      console.error('[Onboarding] Failed to save settings:', e);
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Let\'s go 🚀';
      }
      // Show error inline
      const errorEl = document.createElement('div');
      errorEl.className = 'onboarding-error';
      errorEl.textContent = 'Failed to save settings. Is the backend running?';
      const formEl = this.root.querySelector('#onboarding-form');
      formEl?.appendChild(errorEl);
      setTimeout(() => errorEl.remove(), 5000);
    }
  }

  private esc(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  destroy(): void {
    this.root.innerHTML = '';
  }
}
