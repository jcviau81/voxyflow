import { Project, ProjectFormData, ProjectFormShowEvent, GitHubRepoInfo } from '../../types';
import { TechStack } from './TechStack';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, API_URL } from '../../utils/constants';
import { createElement } from '../../utils/helpers';

const PROJECT_EMOJIS = ['🎮', '🎙', '🌐', '📱', '🔧', '🎨', '📊', '🚀', '💡', '🔥', '📁', '🎯', '🛠️', '🧪', '📦', '🌟'];
const DEFAULT_EMOJI = '📁';

const COLOR_PALETTE = [
  '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4',
  '#feca57', '#ff9ff3', '#54a0ff', '#c47eff',
];

export class ProjectForm {
  private container: HTMLElement;
  private mode: 'create' | 'edit' = 'create';
  private project: Project | null = null;

  // Form state
  private selectedEmoji: string = DEFAULT_EMOJI;
  private selectedColor: string = '';
  private selectedStatus: 'active' | 'archived' = 'active';
  private githubInfo: GitHubRepoInfo | null = null;

  // DOM refs
  private nameInput: HTMLInputElement | null = null;
  private descInput: HTMLTextAreaElement | null = null;
  private nameError: HTMLElement | null = null;
  private descError: HTMLElement | null = null;
  private githubInput: HTMLInputElement | null = null;
  private githubStatusEl: HTMLElement | null = null;
  private localPathInput: HTMLInputElement | null = null;
  private techStackComponent: TechStack | null = null;

  constructor(private parentElement: HTMLElement, event: ProjectFormShowEvent) {
    this.mode = event.mode;
    this.project = event.project || null;

    if (this.project) {
      this.selectedEmoji = this.project.emoji || DEFAULT_EMOJI;
      this.selectedColor = this.project.color || '';
      this.selectedStatus = this.project.archived ? 'archived' : 'active';
    }

    this.container = createElement('div', { className: 'project-form-wrapper' });
    this.render();
  }

  render(): void {
    this.container.innerHTML = '';

    const form = createElement('div', {
      className: 'project-form',
      'data-testid': 'project-form',
    });

    // Title
    const heading = createElement('h2', {}, this.mode === 'create' ? 'Create Project' : 'Edit Project');
    form.appendChild(heading);

    // Name field
    form.appendChild(this.renderNameField());

    // Description field
    form.appendChild(this.renderDescriptionField());

    // Emoji selector
    form.appendChild(this.renderEmojiSelector());

    // Color palette
    form.appendChild(this.renderColorPalette());

    // GitHub repo
    form.appendChild(this.renderGitHubField());

    // Local path
    form.appendChild(this.renderLocalPathField());

    // Tech stack (read-only display)
    const techContainer = createElement('div', { className: 'form-group' });
    this.techStackComponent = new TechStack(techContainer);
    form.appendChild(techContainer);

    // Auto-detect if project already has localPath or techStack
    if (this.project?.localPath) {
      this.techStackComponent.detect(this.project.localPath);
    } else if (this.project?.techStack) {
      this.techStackComponent.setData(this.project.techStack);
    }

    // Status (edit only)
    if (this.mode === 'edit') {
      form.appendChild(this.renderStatusField());
    }

    // Actions
    form.appendChild(this.renderActions());

    this.container.appendChild(form);
    this.parentElement.appendChild(this.container);

    // Focus name input
    requestAnimationFrame(() => this.nameInput?.focus());
  }

  private renderNameField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, 'Project Name *');

    this.nameInput = document.createElement('input');
    this.nameInput.type = 'text';
    this.nameInput.className = 'form-input';
    this.nameInput.placeholder = 'My Awesome Project';
    this.nameInput.maxLength = 100;
    this.nameInput.setAttribute('data-testid', 'project-name-input');

    if (this.project) {
      this.nameInput.value = this.project.name;
    }

    // Live validation
    this.nameInput.addEventListener('input', () => this.validateName());

    this.nameError = createElement('div', { className: 'form-error', 'data-testid': 'project-name-error' });

    group.appendChild(label);
    group.appendChild(this.nameInput);
    group.appendChild(this.nameError);
    return group;
  }

  private renderDescriptionField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, 'Description');

    this.descInput = document.createElement('textarea');
    this.descInput.className = 'form-textarea';
    this.descInput.placeholder = "What's this project about?";
    this.descInput.maxLength = 500;
    this.descInput.setAttribute('data-testid', 'project-description-input');

    if (this.project) {
      this.descInput.value = this.project.description || '';
    }

    this.descInput.addEventListener('input', () => this.validateDescription());

    this.descError = createElement('div', { className: 'form-error' });

    group.appendChild(label);
    group.appendChild(this.descInput);
    group.appendChild(this.descError);
    return group;
  }

  private renderEmojiSelector(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, 'Emoji');
    const selector = createElement('div', { className: 'emoji-selector' });

    PROJECT_EMOJIS.forEach((emoji) => {
      const btn = createElement('button', {
        className: `emoji-option${emoji === this.selectedEmoji ? ' selected' : ''}`,
        'data-testid': `emoji-option-${emoji}`,
      }, emoji);
      btn.type = 'button';
      btn.addEventListener('click', () => {
        this.selectedEmoji = emoji;
        // Update selection UI
        selector.querySelectorAll('.emoji-option').forEach((el) => el.classList.remove('selected'));
        btn.classList.add('selected');
      });
      selector.appendChild(btn);
    });

    group.appendChild(label);
    group.appendChild(selector);
    return group;
  }

  private renderColorPalette(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, 'Color');
    const palette = createElement('div', { className: 'color-palette' });

    COLOR_PALETTE.forEach((color) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `color-option${color === this.selectedColor ? ' selected' : ''}`;
      btn.style.background = color;
      btn.setAttribute('data-color', color);
      btn.setAttribute('data-testid', `color-option-${color.replace('#', '')}`);
      btn.addEventListener('click', () => {
        this.selectedColor = color;
        palette.querySelectorAll('.color-option').forEach((el) => el.classList.remove('selected'));
        btn.classList.add('selected');
      });
      palette.appendChild(btn);
    });

    group.appendChild(label);
    group.appendChild(palette);
    return group;
  }

  private renderGitHubField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, '🔗 GitHub Repository');

    const row = createElement('div', { className: 'github-input-row' });

    this.githubInput = document.createElement('input');
    this.githubInput.type = 'text';
    this.githubInput.className = 'form-input';
    this.githubInput.placeholder = 'owner/repo or https://github.com/owner/repo';
    this.githubInput.setAttribute('data-testid', 'project-github-input');

    // Pre-fill if editing and project has github info
    if (this.project?.githubRepo) {
      this.githubInput.value = this.project.githubRepo;
    }

    // Enter key triggers connect
    this.githubInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        this.handleGitHubConnect();
      }
    });

    const connectBtn = createElement('button', {
      className: 'btn-secondary',
      'data-testid': 'github-connect-btn',
    }, 'Connect');
    (connectBtn as HTMLButtonElement).type = 'button';
    connectBtn.addEventListener('click', () => this.handleGitHubConnect());

    row.appendChild(this.githubInput);
    row.appendChild(connectBtn);

    this.githubStatusEl = createElement('div', {
      className: 'github-status',
      'data-testid': 'github-status',
    });

    // If editing with existing github info, show connected status
    if (this.project?.githubRepo && this.project?.githubUrl) {
      this.showGitHubConnected({
        valid: true,
        full_name: this.project.githubRepo,
        description: '',
        default_branch: this.project.githubBranch || 'main',
        language: this.project.githubLanguage || null,
        stars: 0,
        private: false,
        html_url: this.project.githubUrl,
        clone_url: '',
        updated_at: '',
      });
    }

    group.appendChild(label);
    group.appendChild(row);
    group.appendChild(this.githubStatusEl);
    return group;
  }

  private parseGitHubInput(input: string): { owner: string; repo: string } | null {
    let value = input.trim();
    if (!value) return null;

    // Strip .git suffix
    value = value.replace(/\.git$/, '');

    // Full URL: https://github.com/owner/repo
    const urlMatch = value.match(/github\.com\/([^/]+)\/([^/]+)/);
    if (urlMatch) {
      return { owner: urlMatch[1], repo: urlMatch[2] };
    }

    // Short form: owner/repo
    const shortMatch = value.match(/^([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)$/);
    if (shortMatch) {
      return { owner: shortMatch[1], repo: shortMatch[2] };
    }

    return null;
  }

  private async handleGitHubConnect(): Promise<void> {
    if (!this.githubInput || !this.githubStatusEl) return;

    const parsed = this.parseGitHubInput(this.githubInput.value);
    if (!parsed) {
      this.showGitHubError('Invalid format. Use owner/repo or https://github.com/owner/repo');
      return;
    }

    // Show loading
    this.githubStatusEl.className = 'github-status';
    this.githubStatusEl.innerHTML = '<span class="github-loading">⏳ Validating...</span>';

    try {
      const response = await fetch(`${API_URL}/api/github/validate/${parsed.owner}/${parsed.repo}`);
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Repository not found' }));
        this.showGitHubError(err.detail || 'Repository not found');
        return;
      }

      const info: GitHubRepoInfo = await response.json();
      this.githubInfo = info;
      this.showGitHubConnected(info);
    } catch (e) {
      this.showGitHubError('Failed to connect to GitHub API');
    }
  }

  private showGitHubConnected(info: GitHubRepoInfo): void {
    if (!this.githubStatusEl) return;
    this.githubInfo = info;

    const updatedAgo = info.updated_at ? this.formatTimeAgo(info.updated_at) : '';
    const metaParts = [
      info.language,
      info.default_branch,
      `⭐ ${info.stars}`,
      updatedAgo ? `Updated ${updatedAgo}` : '',
    ].filter(Boolean).join(' · ');

    this.githubStatusEl.className = 'github-status connected';
    this.githubStatusEl.innerHTML = `
      <span class="status-icon">✅</span>
      <div class="status-info">
        <div class="repo-name">${info.full_name}</div>
        <div class="repo-meta">${metaParts}</div>
        <a href="${info.html_url}" target="_blank" rel="noopener" class="repo-link">Open on GitHub ↗</a>
      </div>
    `;
  }

  private showGitHubError(message: string): void {
    if (!this.githubStatusEl) return;
    this.githubInfo = null;
    this.githubStatusEl.className = 'github-status error';
    this.githubStatusEl.innerHTML = `<span>❌ ${message}</span>`;
  }

  private formatTimeAgo(isoDate: string): string {
    try {
      const diff = Date.now() - new Date(isoDate).getTime();
      const minutes = Math.floor(diff / 60000);
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      const days = Math.floor(hours / 24);
      return `${days}d ago`;
    } catch {
      return '';
    }
  }

  private renderLocalPathField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, '📂 Local Path');

    const row = createElement('div', { className: 'github-input-row' });

    this.localPathInput = document.createElement('input');
    this.localPathInput.type = 'text';
    this.localPathInput.className = 'form-input';
    this.localPathInput.placeholder = '~/projects/my-app';
    this.localPathInput.setAttribute('data-testid', 'project-localpath-input');

    if (this.project?.localPath) {
      this.localPathInput.value = this.project.localPath;
    }

    const detectBtn = createElement('button', {
      className: 'btn-secondary',
      'data-testid': 'tech-detect-btn',
    }, 'Detect');
    (detectBtn as HTMLButtonElement).type = 'button';
    detectBtn.addEventListener('click', () => this.handleTechDetect());

    row.appendChild(this.localPathInput);
    row.appendChild(detectBtn);

    group.appendChild(label);
    group.appendChild(row);
    return group;
  }

  private async handleTechDetect(): Promise<void> {
    const path = this.localPathInput?.value.trim();
    if (!path || !this.techStackComponent) return;
    await this.techStackComponent.detect(path);
  }

  private renderStatusField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    const label = createElement('label', {}, 'Status');

    const select = document.createElement('select');
    select.className = 'form-input';
    select.setAttribute('data-testid', 'project-status-select');

    const activeOpt = document.createElement('option');
    activeOpt.value = 'active';
    activeOpt.textContent = 'Active';
    const archivedOpt = document.createElement('option');
    archivedOpt.value = 'archived';
    archivedOpt.textContent = 'Archived';

    select.appendChild(activeOpt);
    select.appendChild(archivedOpt);
    select.value = this.selectedStatus;

    select.addEventListener('change', () => {
      this.selectedStatus = select.value as 'active' | 'archived';
    });

    group.appendChild(label);
    group.appendChild(select);
    return group;
  }

  private renderActions(): HTMLElement {
    const actions = createElement('div', { className: 'form-actions' });

    const submitBtn = createElement('button', {
      className: 'btn-primary',
      'data-testid': 'project-form-submit',
    }, this.mode === 'create' ? 'Create Project' : 'Save Changes');
    submitBtn.addEventListener('click', () => this.handleSubmit());

    const cancelBtn = createElement('button', {
      className: 'btn-ghost',
      'data-testid': 'project-form-cancel',
    }, 'Cancel');
    cancelBtn.addEventListener('click', () => this.handleCancel());

    actions.appendChild(submitBtn);
    actions.appendChild(cancelBtn);

    if (this.mode === 'edit' && this.project) {
      const archiveBtn = createElement('button', {
        className: 'btn-danger',
        'data-testid': 'project-form-archive',
      }, this.project.archived ? 'Unarchive' : 'Archive');
      archiveBtn.addEventListener('click', () => this.handleArchive());
      actions.appendChild(archiveBtn);
    }

    return actions;
  }

  private validateName(): boolean {
    if (!this.nameInput || !this.nameError) return false;
    const value = this.nameInput.value.trim();
    if (!value) {
      this.nameInput.classList.add('error');
      this.nameInput.classList.remove('valid');
      this.nameError.textContent = 'Project name is required';
      return false;
    }
    if (value.length > 100) {
      this.nameInput.classList.add('error');
      this.nameInput.classList.remove('valid');
      this.nameError.textContent = 'Max 100 characters';
      return false;
    }
    this.nameInput.classList.remove('error');
    this.nameInput.classList.add('valid');
    this.nameError.textContent = '';
    return true;
  }

  private validateDescription(): boolean {
    if (!this.descInput || !this.descError) return false;
    const value = this.descInput.value;
    if (value.length > 500) {
      this.descInput.classList.add('error');
      this.descError.textContent = 'Max 500 characters';
      return false;
    }
    this.descInput.classList.remove('error');
    this.descError.textContent = '';
    return true;
  }

  private validate(): boolean {
    const nameValid = this.validateName();
    const descValid = this.validateDescription();
    return nameValid && descValid;
  }

  private handleSubmit(): void {
    if (!this.validate()) return;

    const data: ProjectFormData = {
      title: this.nameInput!.value.trim(),
      description: this.descInput?.value.trim() || undefined,
      emoji: this.selectedEmoji,
      color: this.selectedColor || undefined,
      localPath: this.localPathInput?.value.trim() || undefined,
    };

    // Include GitHub data if connected
    if (this.githubInfo) {
      data.githubRepo = this.githubInfo.full_name;
      data.githubUrl = this.githubInfo.html_url;
      data.githubBranch = this.githubInfo.default_branch;
      data.githubLanguage = this.githubInfo.language || undefined;
    }

    if (this.mode === 'edit') {
      data.status = this.selectedStatus;
    }

    eventBus.emit(EVENTS.PROJECT_FORM_SUBMIT, { mode: this.mode, data, projectId: this.project?.id });
  }

  private handleCancel(): void {
    eventBus.emit(EVENTS.PROJECT_FORM_CANCEL);
  }

  private handleArchive(): void {
    if (!this.project) return;
    const newArchived = !this.project.archived;
    eventBus.emit(EVENTS.PROJECT_FORM_SUBMIT, {
      mode: 'edit',
      data: { title: this.project.name, status: newArchived ? 'archived' : 'active' } as ProjectFormData,
      projectId: this.project.id,
    });
  }

  update(): void {
    // No-op for now
  }

  destroy(): void {
    this.techStackComponent?.destroy();
    this.container.remove();
  }
}
