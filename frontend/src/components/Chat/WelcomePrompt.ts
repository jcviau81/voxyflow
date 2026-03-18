import { Project, Card } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, AGENT_PERSONAS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export type WelcomeMode = 'general' | 'project' | 'card';

export interface WelcomeContext {
  project?: Project;
  card?: Card;
  /** In-progress cards for the project (project mode) */
  inProgressCards?: Card[];
  /** Todo count for the project */
  todoCount?: number;
  /** Dependencies for the card */
  deps?: Card[];
  /** Tags for the card */
  tags?: string[];
}

export class WelcomePrompt {
  private element: HTMLElement;
  private visible = true;

  constructor(
    private parentElement: HTMLElement,
    private mode: WelcomeMode,
    private context: WelcomeContext = {},
  ) {
    this.element = createElement('div', { className: 'welcome-prompt-wrapper' });
    this.render();
  }

  private render(): void {
    this.element.innerHTML = '';

    switch (this.mode) {
      case 'general':
        this.renderGeneral();
        break;
      case 'project':
        this.renderProject();
        break;
      case 'card':
        this.renderCard();
        break;
    }

    this.parentElement.appendChild(this.element);
  }

  // ─── General Welcome ──────────────────────────────────────────────

  private renderGeneral(): void {
    const prompt = createElement('div', {
      className: 'welcome-prompt',
      'data-testid': 'welcome-prompt',
    });

    // Header
    const header = createElement('div', { className: 'welcome-header' });
    const emoji = createElement('div', { className: 'welcome-emoji' }, '🔥');
    const title = createElement('h2', {}, "Hey! Qu'est-ce qu'on fait?");
    header.appendChild(emoji);
    header.appendChild(title);

    // Actions
    const actions = createElement('div', { className: 'welcome-actions' });

    actions.appendChild(
      this.createButton('chat', '💬', 'Just chatting', 'Conversation libre avec Ember'),
    );
    actions.appendChild(
      this.createButton(
        'existing-project',
        '🏗️',
        'Work on an existing project',
        'Ouvre un projet existant',
      ),
    );
    actions.appendChild(
      this.createButton(
        'brainstorm',
        '💡',
        'Brainstorm a new project',
        'Commençons quelque chose de nouveau',
      ),
    );
    actions.appendChild(
      this.createButton('review', '📋', 'Review my tasks', "Vue d'ensemble de toutes les cartes"),
    );

    const hint = createElement('p', { className: 'welcome-hint' }, 'Or just start typing...');

    prompt.appendChild(header);
    prompt.appendChild(actions);
    prompt.appendChild(hint);
    this.element.appendChild(prompt);
  }

  // ─── Project Welcome ──────────────────────────────────────────────

  private renderProject(): void {
    const project = this.context.project;
    if (!project) return;

    const inProgressCards = this.context.inProgressCards || [];
    const todoCount = this.context.todoCount || 0;
    const inProgressCount = inProgressCards.length;

    const prompt = createElement('div', {
      className: 'welcome-prompt project-welcome',
      'data-testid': 'project-welcome',
    });

    // Header
    const header = createElement('div', { className: 'welcome-header' });
    const emoji = createElement('div', { className: 'welcome-emoji' }, project.emoji || '📁');
    const title = createElement('h2', {}, project.name);
    const stats = createElement(
      'div',
      { className: 'project-stats' },
      `📊 ${inProgressCount} in progress, ${todoCount} todo`,
    );
    header.appendChild(emoji);
    header.appendChild(title);
    header.appendChild(stats);

    // Actions
    const actions = createElement('div', { className: 'welcome-actions' });

    // Resume buttons for in-progress cards
    for (const card of inProgressCards) {
      const agentEmoji = card.assignedAgent
        ? AGENT_PERSONAS[card.assignedAgent]?.emoji || '🤖'
        : '🤖';
      const agentName = card.assignedAgent
        ? AGENT_PERSONAS[card.assignedAgent]?.name || 'Agent'
        : 'Unassigned';

      const btn = this.createButton(
        'resume',
        '▶️',
        `Resume: "${card.title}"`,
        `${agentEmoji} ${agentName}`,
      );
      btn.classList.add('resume');
      btn.setAttribute('data-card-id', card.id);
      actions.appendChild(btn);
    }

    actions.appendChild(
      this.createButton(
        'existing-task',
        '📋',
        'Work on an existing task',
        `Choose from ${todoCount} tasks`,
      ),
    );
    actions.appendChild(
      this.createButton(
        'brainstorm-task',
        '💡',
        'Brainstorm a new task',
        'Ajouter quelque chose au projet',
      ),
    );
    actions.appendChild(
      this.createButton('chat-project', '💬', 'Just chat about the project', 'Discussion libre'),
    );

    const hint = createElement('p', { className: 'welcome-hint' }, 'Or just start typing...');

    prompt.appendChild(header);
    prompt.appendChild(actions);
    prompt.appendChild(hint);
    this.element.appendChild(prompt);
  }

  // ─── Card Welcome ─────────────────────────────────────────────────

  private renderCard(): void {
    const card = this.context.card;
    if (!card) return;

    const agentEmoji = card.assignedAgent
      ? AGENT_PERSONAS[card.assignedAgent]?.emoji || '🤖'
      : '🤖';
    const agentName = card.assignedAgent
      ? AGENT_PERSONAS[card.assignedAgent]?.name || 'Agent'
      : 'Unassigned';
    const deps = this.context.deps || [];
    const tags = this.context.tags || card.tags || [];

    const prompt = createElement('div', {
      className: 'welcome-prompt card-welcome',
      'data-testid': 'card-welcome',
    });

    // Header
    const header = createElement('div', { className: 'welcome-header' });
    const emoji = createElement('div', { className: 'welcome-emoji' }, agentEmoji);
    const title = createElement('h2', {}, card.title);
    const meta = createElement(
      'div',
      { className: 'card-meta' },
      `Agent: ${agentEmoji} ${agentName} · Status: ${card.status} · Priority: ${card.priority}`,
    );
    header.appendChild(emoji);
    header.appendChild(title);
    header.appendChild(meta);

    if (card.description) {
      const desc = createElement('p', { className: 'card-desc' }, card.description);
      header.appendChild(desc);
    }

    // Actions
    const actions = createElement('div', { className: 'welcome-actions' });

    actions.appendChild(
      this.createButton('start-work', '🚀', 'Start working on this', 'Agent begins execution'),
    );
    actions.appendChild(
      this.createButton(
        'enrich',
        '📝',
        'Enrich details / write PRD',
        'Define requirements and specs',
      ),
    );
    actions.appendChild(
      this.createButton(
        'research',
        '🔍',
        'Research before starting',
        'Explore options and best practices',
      ),
    );
    actions.appendChild(
      this.createButton('edit-card', '✏️', 'Edit card details', 'Change title, agent, priority'),
    );
    actions.appendChild(
      this.createButton('discuss', '💬', 'Just discuss this task', 'Chat freely about this card'),
    );

    // Deps & Tags
    const depsSection = createElement('div', {
      className: 'card-deps',
      'data-testid': 'card-deps',
    });

    if (deps.length > 0) {
      const depsLabel = document.createTextNode('Dependencies: ');
      depsSection.appendChild(depsLabel);
      for (const d of deps) {
        const tag = createElement('span', { className: 'dep-tag' }, d.title);
        depsSection.appendChild(tag);
      }
    }

    if (tags.length > 0) {
      if (deps.length > 0) depsSection.appendChild(document.createTextNode(' '));
      const tagsLabel = document.createTextNode('Tags: ');
      depsSection.appendChild(tagsLabel);
      for (const t of tags) {
        const tag = createElement('span', { className: 'tag' }, `#${t}`);
        depsSection.appendChild(tag);
      }
    }

    prompt.appendChild(header);
    prompt.appendChild(actions);
    if (deps.length > 0 || tags.length > 0) {
      prompt.appendChild(depsSection);
    }
    this.element.appendChild(prompt);
  }

  // ─── Helpers ──────────────────────────────────────────────────────

  private createButton(
    action: string,
    icon: string,
    label: string,
    desc: string,
  ): HTMLButtonElement {
    const btn = createElement('button', {
      className: 'welcome-btn',
      'data-action': action,
    }) as HTMLButtonElement;

    const iconSpan = createElement('span', { className: 'welcome-btn-icon' }, icon);
    const labelSpan = createElement('span', { className: 'welcome-btn-label' }, label);
    const descSpan = createElement('span', { className: 'welcome-btn-desc' }, desc);

    const textWrap = createElement('div', { className: 'welcome-btn-text' });
    textWrap.appendChild(labelSpan);
    textWrap.appendChild(descSpan);

    btn.appendChild(iconSpan);
    btn.appendChild(textWrap);

    btn.addEventListener('click', () => this.handleAction(action, btn));

    return btn;
  }

  private handleAction(action: string, btn: HTMLElement): void {
    const cardId = btn.getAttribute('data-card-id') || undefined;

    switch (action) {
      case 'chat':
        // Just hide welcome, focus on input
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'chat', mode: this.mode });
        break;

      case 'existing-project':
        // Switch to projects view
        this.hide();
        appState.setView('projects');
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'existing-project', mode: this.mode });
        break;

      case 'brainstorm':
        // Hide welcome, send brainstorm opening
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'brainstorm', mode: this.mode });
        break;

      case 'review':
        // Switch to kanban view
        this.hide();
        appState.setView('kanban');
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'review', mode: this.mode });
        break;

      case 'resume':
        this.hide();
        if (cardId) {
          appState.selectCard(cardId);
        }
        eventBus.emit(EVENTS.WELCOME_ACTION, {
          action: 'resume',
          mode: this.mode,
          cardId,
        });
        break;

      case 'existing-task':
        this.hide();
        appState.setView('kanban');
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'existing-task', mode: this.mode });
        break;

      case 'brainstorm-task':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'brainstorm-task', mode: this.mode });
        break;

      case 'chat-project':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'chat-project', mode: this.mode });
        break;

      case 'start-work':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'start-work', mode: this.mode, cardId: this.context.card?.id });
        break;

      case 'enrich':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'enrich', mode: this.mode, cardId: this.context.card?.id });
        break;

      case 'research':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'research', mode: this.mode, cardId: this.context.card?.id });
        break;

      case 'edit-card':
        this.hide();
        if (this.context.card) {
          eventBus.emit(EVENTS.CARD_FORM_SHOW, { mode: 'edit', card: this.context.card });
        }
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'edit-card', mode: this.mode, cardId: this.context.card?.id });
        break;

      case 'discuss':
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action: 'discuss', mode: this.mode, cardId: this.context.card?.id });
        break;

      default:
        this.hide();
        eventBus.emit(EVENTS.WELCOME_ACTION, { action, mode: this.mode });
    }
  }

  hide(): void {
    if (!this.visible) return;
    this.visible = false;
    this.element.classList.add('welcome-hidden');
    // After animation
    setTimeout(() => {
      this.element.style.display = 'none';
    }, 300);
  }

  show(): void {
    if (this.visible) return;
    this.visible = true;
    this.element.style.display = '';
    // Force reflow for animation
    void this.element.offsetHeight;
    this.element.classList.remove('welcome-hidden');
  }

  isVisible(): boolean {
    return this.visible;
  }

  destroy(): void {
    this.element.remove();
  }
}
