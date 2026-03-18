import { Card, CardStatus, AgentPersona } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUS_LABELS, CARD_STATUSES } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export interface CardFormShowEvent {
  mode: 'create' | 'edit';
  card?: Card;
  projectId: string;
  prefillTitle?: string;
  prefillStatus?: CardStatus;
}

export interface CardFormData {
  title: string;
  description: string;
  agent: string;
  status: CardStatus;
  priority: number;
  dependencies: string[];
  tags: string[];
}

const AGENTS = [
  { value: 'ember', label: '\u{1F525} Ember' },
  { value: 'researcher', label: '\u{1F50D} Recherchiste' },
  { value: 'coder', label: '\u{1F4BB} Codeuse' },
  { value: 'designer', label: '\u{1F3A8} Designer' },
  { value: 'architect', label: '\u{1F3D7}\uFE0F Architecte' },
  { value: 'writer', label: '\u270D\uFE0F R\u00E9dactrice' },
  { value: 'qa', label: '\u{1F9EA} QA/Tester' },
];

const PRIORITIES = [
  { value: 0, label: '\u{1F7E2} Low' },
  { value: 1, label: '\u{1F7E1} Medium' },
  { value: 2, label: '\u{1F7E0} High' },
  { value: 3, label: '\u{1F534} Critical' },
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
  private agentSelect: HTMLSelectElement | null = null;
  private prioritySelect: HTMLSelectElement | null = null;
  private tagsInput: HTMLInputElement | null = null;
  private titleError: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement, event: CardFormShowEvent) {
    this.mode = event.mode;
    this.card = event.card || null;
    this.projectId = event.projectId;
    if (this.card) {
      this.selectedStatus = this.card.status;
      this.selectedDependencies = new Set(this.card.dependencies);
    }
    if (event.prefillStatus) this.selectedStatus = event.prefillStatus;
    this.container = createElement('div', { className: 'card-form-wrapper' });
    this.render();
  }

  render(): void {
    this.container.innerHTML = '';
    const form = createElement('div', { className: 'card-form', 'data-testid': 'card-form' });
    form.appendChild(createElement('h3', {}, this.mode === 'create' ? 'Create Card' : 'Edit Card'));
    form.appendChild(this.renderTitleField());
    form.appendChild(this.renderDescriptionField());
    form.appendChild(this.renderAgentPriorityRow());
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

  private renderAgentPriorityRow(): HTMLElement {
    const row = createElement('div', { className: 'form-row' });
    const agentGroup = createElement('div', { className: 'form-group half' });
    agentGroup.appendChild(createElement('label', {}, 'Agent'));
    this.agentSelect = document.createElement('select');
    this.agentSelect.className = 'form-select';
    this.agentSelect.setAttribute('data-testid', 'card-agent-select');
    AGENTS.forEach((a) => {
      const opt = document.createElement('option');
      opt.value = a.value; opt.textContent = a.label;
      this.agentSelect!.appendChild(opt);
    });
    agentGroup.appendChild(this.agentSelect);
    const prioGroup = createElement('div', { className: 'form-group half' });
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
    row.appendChild(agentGroup);
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
    if (this.agentSelect && this.card.assignedAgent) {
      const val = Object.entries(AGENT_TO_PERSONA).find(([, p]) => p === this.card!.assignedAgent)?.[0] || 'ember';
      this.agentSelect.value = val;
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
    const agentValue = this.agentSelect?.value || 'ember';
    const data: CardFormData = {
      title: this.titleInput!.value.trim(),
      description: this.descInput?.value.trim() || '',
      agent: agentValue,
      status: this.selectedStatus,
      priority: parseInt(this.prioritySelect?.value || '0', 10),
      dependencies: Array.from(this.selectedDependencies),
      tags,
    };
    eventBus.emit(EVENTS.CARD_FORM_SUBMIT, {
      mode: this.mode, data, cardId: this.card?.id,
      projectId: this.projectId,
      assignedAgent: AGENT_TO_PERSONA[agentValue] || undefined,
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
