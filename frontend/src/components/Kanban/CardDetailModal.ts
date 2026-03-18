import { Card, AgentPersona, CardStatus, AgentInfo } from '../../types';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, CARD_STATUSES, CARD_STATUS_LABELS, AGENT_PERSONAS, AGENT_TYPE_INFO } from '../../utils/constants';
import { createElement, formatTime } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { cardService } from '../../services/CardService';

export class CardDetailModal {
  private overlay: HTMLElement;
  private modal: HTMLElement;
  private card: Card | null = null;
  private unsubscribers: (() => void)[] = [];
  private agents: AgentInfo[] = Object.entries(AGENT_TYPE_INFO).map(([type, info]) => ({
    type,
    name: info.name,
    emoji: info.emoji,
    description: info.description,
    strengths: [],
    keywords: [],
  }));

  constructor(private parentElement: HTMLElement) {
    this.overlay = createElement('div', { className: 'modal-overlay hidden' });
    this.modal = createElement('div', { className: 'modal card-detail-modal' });
    this.overlay.appendChild(this.modal);
    this.parentElement.appendChild(this.overlay);
    this.setupListeners();
    // Load agents from API (for richer descriptions)
    cardService.getAgents().then((agents) => {
      if (agents.length > 0) this.agents = agents;
    }).catch(() => {/* fallback already set */});
  }

  private setupListeners(): void {
    this.overlay.addEventListener('click', (e) => {
      if (e.target === this.overlay) this.close();
    });

    this.unsubscribers.push(
      eventBus.on(EVENTS.MODAL_OPEN, (data: unknown) => {
        const { type, cardId } = data as { type: string; cardId: string };
        if (type === 'card-detail') {
          this.open(cardId);
        }
      })
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.MODAL_CLOSE, () => this.close())
    );

    this.unsubscribers.push(
      eventBus.on(EVENTS.CARD_UPDATED, (data: unknown) => {
        const { id } = data as { id: string };
        if (this.card && this.card.id === id) {
          this.card = appState.getCard(id) || null;
          if (this.card) this.renderContent();
        }
      })
    );

    // ESC to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.overlay.classList.contains('hidden')) {
        this.close();
      }
    });
  }

  open(cardId: string): void {
    this.card = appState.getCard(cardId) || null;
    if (!this.card) return;

    this.renderContent();
    this.overlay.classList.remove('hidden');
  }

  close(): void {
    this.overlay.classList.add('hidden');
    appState.selectCard(null);
  }

  private renderContent(): void {
    if (!this.card) return;
    this.modal.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'modal-header' });
    const titleInput = createElement('input', {
      className: 'modal-title-input',
      value: this.card.title,
    }) as HTMLInputElement;
    titleInput.addEventListener('change', () => {
      if (this.card) {
        cardService.update(this.card.id, { title: titleInput.value });
      }
    });

    const closeBtn = createElement('button', { className: 'modal-close-btn' }, '✕');
    closeBtn.addEventListener('click', () => this.close());

    header.appendChild(titleInput);
    header.appendChild(closeBtn);

    // Status buttons
    const statusRow = createElement('div', { className: 'modal-status-row' });
    for (const status of CARD_STATUSES) {
      const btn = createElement(
        'button',
        {
          className: `status-btn ${this.card.status === status ? 'active' : ''}`,
          'data-status': status,
        },
        CARD_STATUS_LABELS[status]
      );
      btn.addEventListener('click', () => {
        if (this.card) {
          cardService.move(this.card.id, status as CardStatus);
        }
      });
      statusRow.appendChild(btn);
    }

    // Description
    const descSection = createElement('div', { className: 'modal-section' });
    const descLabel = createElement('label', { className: 'modal-label' }, 'Description');
    const descInput = createElement('textarea', {
      className: 'modal-description',
      placeholder: 'Add a description...',
    }) as HTMLTextAreaElement;
    descInput.value = this.card.description;
    descInput.addEventListener('change', () => {
      if (this.card) {
        cardService.update(this.card.id, { description: descInput.value });
      }
    });
    descSection.appendChild(descLabel);
    descSection.appendChild(descInput);

    // Agent assignment — chip selector
    const currentAgentType = this.card.agentType || 'ember';
    const agentSection = createElement('div', { className: 'modal-section' });
    const agentLabel = createElement('label', { className: 'modal-label' }, 'Agent');
    const agentSelector = createElement('div', { className: 'agent-selector agent-selector--modal' });

    this.agents.forEach((agent) => {
      const chip = createElement('button', {
        className: 'agent-chip' + (currentAgentType === agent.type ? ' selected' : ''),
        'data-agent-type': agent.type,
        title: agent.description,
      }, `${agent.emoji} ${agent.name}`);
      (chip as HTMLButtonElement).type = 'button';
      chip.addEventListener('click', () => {
        if (!this.card) return;
        agentSelector.querySelectorAll('.agent-chip').forEach((el) => el.classList.remove('selected'));
        chip.classList.add('selected');
        cardService.updateAgentType(this.card.id, agent.type);
      });
      agentSelector.appendChild(chip);
    });

    agentSection.appendChild(agentLabel);
    agentSection.appendChild(agentSelector);

    // Dependencies
    const depsSection = createElement('div', { className: 'modal-section' });
    const depsLabel = createElement('label', { className: 'modal-label' }, 'Dependencies');
    const depsList = createElement('div', { className: 'modal-deps-list' });

    if (this.card.dependencies.length > 0) {
      this.card.dependencies.forEach((depId) => {
        const depCard = appState.getCard(depId);
        const depItem = createElement('div', { className: 'dep-item' });
        const depName = createElement(
          'span',
          {},
          depCard ? depCard.title : depId
        );
        const removeBtn = createElement('button', { className: 'dep-remove' }, '✕');
        removeBtn.addEventListener('click', () => {
          if (this.card) cardService.removeDependency(this.card.id, depId);
        });
        depItem.appendChild(depName);
        depItem.appendChild(removeBtn);
        depsList.appendChild(depItem);
      });
    } else {
      depsList.appendChild(createElement('span', { className: 'empty-text' }, 'No dependencies'));
    }

    depsSection.appendChild(depsLabel);
    depsSection.appendChild(depsList);

    // Tags
    const tagsSection = createElement('div', { className: 'modal-section' });
    const tagsLabel = createElement('label', { className: 'modal-label' }, 'Tags');
    const tagsContainer = createElement('div', { className: 'modal-tags' });

    this.card.tags.forEach((tag) => {
      const tagEl = createElement('span', { className: 'tag' }, tag);
      const removeBtn = createElement('span', { className: 'tag-remove' }, '✕');
      removeBtn.addEventListener('click', () => {
        if (this.card) cardService.removeTag(this.card.id, tag);
      });
      tagEl.appendChild(removeBtn);
      tagsContainer.appendChild(tagEl);
    });

    const addTagBtn = createElement('button', { className: 'add-tag-btn' }, '+ Tag');
    addTagBtn.addEventListener('click', () => {
      const tagInput = document.createElement('input');
      tagInput.type = 'text';
      tagInput.className = 'form-input tag-inline-input';
      tagInput.placeholder = 'Tag name...';
      tagInput.style.width = '120px';
      tagInput.style.fontSize = '12px';
      tagInput.style.padding = '3px 8px';
      const commitTag = () => {
        const tag = tagInput.value.trim();
        if (tag && this.card) cardService.addTag(this.card.id, tag);
        tagInput.remove();
      };
      tagInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') commitTag();
        if (e.key === 'Escape') tagInput.remove();
      });
      tagInput.addEventListener('blur', commitTag);
      tagsContainer.insertBefore(tagInput, addTagBtn);
      tagInput.focus();
    });
    tagsContainer.appendChild(addTagBtn);

    tagsSection.appendChild(tagsLabel);
    tagsSection.appendChild(tagsContainer);

    // Metadata
    const metaSection = createElement('div', { className: 'modal-meta' });
    metaSection.appendChild(
      createElement('span', {}, `Created: ${formatTime(this.card.createdAt)}`)
    );
    metaSection.appendChild(
      createElement('span', {}, `Updated: ${formatTime(this.card.updatedAt)}`)
    );

    // Card-specific chat placeholder
    const chatSection = createElement('div', { className: 'modal-section modal-chat' });
    const chatLabel = createElement('label', { className: 'modal-label' }, 'Card Discussion');
    const chatPlaceholder = createElement(
      'div',
      { className: 'card-chat-placeholder' },
      'Card-specific chat coming soon...'
    );
    chatSection.appendChild(chatLabel);
    chatSection.appendChild(chatPlaceholder);

    // Delete button
    const dangerZone = createElement('div', { className: 'modal-danger' });
    const deleteBtn = createElement('button', { className: 'delete-btn' }, '🗑️ Delete Card');
    deleteBtn.addEventListener('click', () => {
      if (this.card && confirm(`Delete "${this.card.title}"?`)) {
        cardService.delete(this.card.id);
        this.close();
      }
    });
    dangerZone.appendChild(deleteBtn);

    // Assemble
    this.modal.appendChild(header);
    this.modal.appendChild(statusRow);
    this.modal.appendChild(descSection);
    this.modal.appendChild(agentSection);
    this.modal.appendChild(depsSection);
    this.modal.appendChild(tagsSection);
    this.modal.appendChild(chatSection);
    this.modal.appendChild(metaSection);
    this.modal.appendChild(dangerZone);
  }

  update(): void {
    if (this.card) {
      this.card = appState.getCard(this.card.id) || null;
      if (this.card) this.renderContent();
    }
  }

  destroy(): void {
    this.unsubscribers.forEach((unsub) => unsub());
    this.unsubscribers = [];
    this.overlay.remove();
  }
}
