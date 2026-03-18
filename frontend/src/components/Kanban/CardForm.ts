import { Card, CardStatus, AgentPersona, AgentInfo } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUS_LABELS, CARD_STATUSES } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';

export interface CardFormShowEvent {
  mode: 'create' | 'edit';
  card?: Card;
  projectId: string;
  prefillTitle?: string;
  prefillStatus?: CardStatus;
  prefillAgentType?: string;  // auto-detected agent type for new cards
}

export interface CardFormData {
  title: string;
  description: string;
  agent: string;
  agentType: string;
  status: CardStatus;
  priority: number;
  dependencies: string[];
  tags: string[];
  enrichAfterCreate?: boolean;
}

// Fallback static agents if API isn't available yet
const FALLBACK_AGENTS: AgentInfo[] = [
  { type: 'ember', name: 'Ember', emoji: '🔥', description: 'Default', strengths: [], keywords: [] },
  { type: 'researcher', name: 'Recherchiste', emoji: '🔍', description: 'Research & analysis', strengths: [], keywords: [] },
  { type: 'coder', name: 'Codeuse', emoji: '💻', description: 'Code implementation', strengths: [], keywords: [] },
  { type: 'designer', name: 'Designer', emoji: '🎨', description: 'UI/UX design', strengths: [], keywords: [] },
  { type: 'architect', name: 'Architecte', emoji: '🏗️', description: 'System design', strengths: [], keywords: [] },
  { type: 'writer', name: 'Rédactrice', emoji: '✍️', description: 'Content & docs', strengths: [], keywords: [] },
  { type: 'qa', name: 'QA', emoji: '🧪', description: 'Testing & QA', strengths: [], keywords: [] },
];

const PRIORITIES = [
  { value: 0, label: '🟢 Low' },
  { value: 1, label: '🟡 Medium' },
  { value: 2, label: '🟠 High' },
  { value: 3, label: '🔴 Critical' },

];

const AGENT_TO_PERSONA: Record<string, AgentPersona> = {
  ember: 'codeuse',
  researcher: 'analyste',
  coder: 'codeuse',
  designer: 'designer',
  architect: 'architecte',
  writer: 'documenteur',
  qa: 'testeur',
};

export class CardForm {
  private container: HTMLElement;
  private mode: 'create' | 'edit';
  private card: Card | null;
  private projectId: string;
  private selectedStatus: CardStatus = 'idea';
  private selectedDependencies: Set<string> = new Set();
  private titleInput: HTMLInputElement | null = null;
  private descInput: HTMLTextAreaElement | null = null;
  private selectedAgentType: string = 'ember';
  private agentSelectorEl: HTMLElement | null = null;
  private prioritySelect: HTMLSelectElement | null = null;
  private tagsInput: HTMLInputElement | null = null;
  private titleError: HTMLElement | null = null;
  private enrichCheckbox: HTMLInputElement | null = null;
  private agents: AgentInfo[] = FALLBACK_AGENTS;

  constructor(private parentElement: HTMLElement, event: CardFormShowEvent) {
    this.mode = event.mode;
    this.card = event.card || null;
    this.projectId = event.projectId;
    if (this.card) {
      this.selectedStatus = this.card.status;
      this.selectedDependencies = new Set(this.card.dependencies);
      this.selectedAgentType = this.card.agentType || 'ember';
    }
    if (event.prefillStatus) this.selectedStatus = event.prefillStatus;
    if (event.prefillAgentType) this.selectedAgentType = event.prefillAgentType;
    this.container = createElement('div', { className: 'card-form-wrapper' });
    // Load agents from API, then render
    cardService.getAgents().then((agents) => {
      if (agents.length > 0) this.agents = agents;
      this.render();
    }).catch(() => {
      this.render();
    });
  }

  render(): void {
    this.container.innerHTML = '';
    const form = createElement('div', { className: 'card-form', 'data-testid': 'card-form' });
    form.appendChild(createElement('h3', {}, this.mode === 'create' ? 'Create Card' : 'Edit Card'));
    form.appendChild(this.renderTitleField());
    form.appendChild(this.renderDescriptionField());
    form.appendChild(this.renderAgentSelector());
    form.appendChild(this.renderPriorityRow());
    form.appendChild(this.renderStatusPills());
    form.appendChild(this.renderDependencies());
    form.appendChild(this.renderTagsField());
    form.appendChild(this.renderActions());
    this.container.appendChild(form);
    this.parentElement.appendChild(this.container);
    if (this.card) this.prefillForm();
    requestAnimationFrame(() => this.titleInput?.focus());
  }

  private renderTitleField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Title *'));
    this.titleInput = document.createElement('input');
    this.titleInput.type = 'text';
    this.titleInput.className = 'form-input';
    this.titleInput.placeholder = 'What needs to be done?';
    this.titleInput.maxLength = 200;
    this.titleInput.setAttribute('data-testid', 'card-title-input');
    this.titleInput.addEventListener('input', () => this.validateTitle());
    this.titleInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.handleSubmit(); }
    });
    this.titleError = createElement('div', { className: 'form-error', 'data-testid': 'card-title-error' });
    group.appendChild(this.titleInput);
    group.appendChild(this.titleError);
    return group;
  }

  private renderDescriptionField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Description'));
    this.descInput = document.createElement('textarea');
    this.descInput.className = 'form-textarea';
    this.descInput.placeholder = 'Details, requirements, notes...';
    this.descInput.maxLength = 2000;
    this.descInput.setAttribute('data-testid', 'card-description-input');
    group.appendChild(this.descInput);
    return group;
  }

  private renderAgentSelector(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Agent'));
    const selector = createElement('div', {
      className: 'agent-selector',
      'data-testid': 'card-agent-selector',
    });
    this.agentSelectorEl = selector;
    this.agents.forEach((agent) => {
      const chip = createElement('button', {
        className: 'agent-chip' + (this.selectedAgentType === agent.type ? ' selected' : ''),
        'data-agent-type': agent.type,
        title: agent.description,
      }, `${agent.emoji} ${agent.name}`);
      (chip as HTMLButtonElement).type = 'button';
      chip.addEventListener('click', () => {
        this.selectedAgentType = agent.type;
        // Update chip highlights
        selector.querySelectorAll('.agent-chip').forEach((el) => el.classList.remove('selected'));
        chip.classList.add('selected');
      });
      selector.appendChild(chip);
    });
    group.appendChild(selector);
    return group;
  }

  private renderPriorityRow(): HTMLElement {
    const row = createElement('div', { className: 'form-row' });
    const prioGroup = createElement('div', { className: 'form-group' });
    prioGroup.appendChild(createElement('label', {}, 'Priority'));
    this.prioritySelect = document.createElement('select');
    this.prioritySelect.className = 'form-select';
    this.prioritySelect.setAttribute('data-testid', 'card-priority-select');
    PRIORITIES.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.value.toString(); opt.textContent = p.label;
      this.prioritySelect!.appendChild(opt);
    });
    prioGroup.appendChild(this.prioritySelect);
    row.appendChild(prioGroup);
    return row;
  }

  private renderStatusPills(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Status'));
    const pills = createElement('div', { className: 'status-pills', 'data-testid': 'card-status-pills' });
    const emojis: Record<string, string> = { 'idea': '\u{1F4A1}', 'todo': '\u{1F4CB}', 'in-progress': '\u{1F3C3}', 'done': '\u2705' };
    CARD_STATUSES.forEach((status) => {
      const text = (emojis[status] || '') + ' ' + (CARD_STATUS_LABELS[status] || status).replace(/^[^\s]+\s/, '');
      const btn = createElement('button', {
        className: 'status-pill' + (status === this.selectedStatus ? ' active' : ''),
        'data-status': status,
      }, text);
      (btn as HTMLButtonElement).type = 'button';
      btn.addEventListener('click', () => {
        this.selectedStatus = status as CardStatus;
        pills.querySelectorAll('.status-pill').forEach((el) => el.classList.remove('active'));
        btn.classList.add('active');
      });
      pills.appendChild(btn);
    });
    group.appendChild(pills);
    return group;
  }

  private renderDependencies(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Dependencies'));
    const depList = createElement('div', { className: 'dependency-list', 'data-testid': 'card-dependencies' });
    const allCards = appState.getCardsByProject(this.projectId);
    const filtered = this.card ? allCards.filter((c) => c.id !== this.card!.id) : allCards;
    if (filtered.length === 0) {
      depList.appendChild(createElement('div', { className: 'dependency-empty' }, 'No other cards in this project'));
    } else {
      filtered.forEach((card) => {
        const item = createElement('div', { className: 'dependency-item' });
        const cb = document.createElement('input');
        cb.type = 'checkbox'; cb.id = 'dep-' + card.id;
        cb.checked = this.selectedDependencies.has(card.id);
        cb.addEventListener('change', () => {
          if (cb.checked) this.selectedDependencies.add(card.id);
          else this.selectedDependencies.delete(card.id);
        });
        const lbl = document.createElement('label');
        lbl.htmlFor = 'dep-' + card.id;
        const emoji = CARD_STATUS_LABELS[card.status]?.split(' ')[0] || '';
        lbl.textContent = emoji + ' ' + card.title;
        item.appendChild(cb); item.appendChild(lbl);
        depList.appendChild(item);
      });
    }
    group.appendChild(depList);
    return group;
  }

  private renderTagsField(): HTMLElement {
    const group = createElement('div', { className: 'form-group' });
    group.appendChild(createElement('label', {}, 'Tags'));
    this.tagsInput = document.createElement('input');
    this.tagsInput.type = 'text';
    this.tagsInput.className = 'form-input';
    this.tagsInput.placeholder = 'Comma-separated: frontend, bug, urgent';
    this.tagsInput.setAttribute('data-testid', 'card-tags-input');
    group.appendChild(this.tagsInput);
    return group;
  }

  private renderActions(): HTMLElement {
    const actions = createElement('div', { className: 'form-actions' });

    // "AI Enrich after create" checkbox (only on create mode)
    if (this.mode === 'create') {
      const enrichRow = createElement('div', { className: 'enrich-checkbox-row' });
      this.enrichCheckbox = document.createElement('input');
      this.enrichCheckbox.type = 'checkbox';
      this.enrichCheckbox.id = 'enrich-after-create';
      this.enrichCheckbox.className = 'enrich-checkbox';
      this.enrichCheckbox.checked = true; // default: opt-in
      const enrichLabel = document.createElement('label');
      enrichLabel.htmlFor = 'enrich-after-create';
      enrichLabel.className = 'enrich-checkbox-label';
      enrichLabel.textContent = '✨ AI Enrich after create';
      enrichRow.appendChild(this.enrichCheckbox);
      enrichRow.appendChild(enrichLabel);
      actions.appendChild(enrichRow);
    }

    const submitBtn = createElement('button', {
      className: 'btn-primary', 'data-testid': 'card-form-submit',
    }, this.mode === 'create' ? 'Create Card' : 'Save Changes');
    submitBtn.addEventListener('click', () => this.handleSubmit());
    const cancelBtn = createElement('button', {
      className: 'btn-ghost', 'data-testid': 'card-form-cancel',
    }, 'Cancel');
    cancelBtn.addEventListener('click', () => this.handleCancel());
    actions.appendChild(submitBtn);
    actions.appendChild(cancelBtn);
    if (this.mode === 'edit' && this.card) {
      const deleteBtn = createElement('button', {
        className: 'btn-danger', 'data-testid': 'card-form-delete',
      }, '\u{1F5D1}\uFE0F Delete');
      deleteBtn.addEventListener('click', () => this.handleDelete());
      actions.appendChild(deleteBtn);
    }
    return actions;
  }

  private prefillForm(): void {
    if (!this.card) return;
    if (this.titleInput) this.titleInput.value = this.card.title;
    if (this.descInput) this.descInput.value = this.card.description || '';
    // Set agent type from card (prefer agentType, fall back to legacy assignedAgent mapping)
    if (this.card.agentType) {
      this.selectedAgentType = this.card.agentType;
    } else if (this.card.assignedAgent) {
      const val = Object.entries(AGENT_TO_PERSONA).find(([, p]) => p === this.card!.assignedAgent)?.[0] || 'ember';
      this.selectedAgentType = val;
    }
    // Update chip selection
    if (this.agentSelectorEl) {
      this.agentSelectorEl.querySelectorAll('.agent-chip').forEach((el) => {
        el.classList.toggle('selected', (el as HTMLElement).dataset.agentType === this.selectedAgentType);
      });
    }
    if (this.prioritySelect) this.prioritySelect.value = this.card.priority.toString();
    if (this.tagsInput && this.card.tags.length > 0) this.tagsInput.value = this.card.tags.join(', ');
  }

  prefillTitle(title: string): void {
    if (this.titleInput) this.titleInput.value = title;
  }

  private validateTitle(): boolean {
    if (!this.titleInput || !this.titleError) return false;
    const value = this.titleInput.value.trim();
    if (!value) {
      this.titleInput.classList.add('error');
      this.titleInput.classList.remove('valid');
      this.titleError.textContent = 'Title is required';
      return false;
    }
    this.titleInput.classList.remove('error');
    this.titleInput.classList.add('valid');
    this.titleError.textContent = '';
    return true;
  }

  private handleSubmit(): void {
    if (!this.validateTitle()) return;
    const tagsRaw = this.tagsInput?.value.trim() || '';
    const tags = tagsRaw ? tagsRaw.split(',').map((t) => t.trim()).filter(Boolean) : [];
    const agentType = this.selectedAgentType || 'ember';
    const enrichAfterCreate = this.mode === 'create' ? (this.enrichCheckbox?.checked ?? true) : undefined;
    const data: CardFormData = {
      title: this.titleInput!.value.trim(),
      description: this.descInput?.value.trim() || '',
      agent: agentType,
      agentType,
      status: this.selectedStatus,
      priority: parseInt(this.prioritySelect?.value || '0', 10),
      dependencies: Array.from(this.selectedDependencies),
      tags,
      enrichAfterCreate,
    };
    eventBus.emit(EVENTS.CARD_FORM_SUBMIT, {
      mode: this.mode, data, cardId: this.card?.id,
      projectId: this.projectId,
      agentType,
      assignedAgent: AGENT_TO_PERSONA[agentType] || undefined,
    });
  }

  private handleCancel(): void { eventBus.emit(EVENTS.CARD_FORM_CANCEL); }

  private handleDelete(): void {
    if (!this.card) return;
    if (confirm('Delete "' + this.card.title + '"?')) {
      eventBus.emit(EVENTS.CARD_FORM_DELETE, { cardId: this.card.id });
    }
  }

  update(): void { /* no-op */ }
  destroy(): void { this.container.remove(); }
}
