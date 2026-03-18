import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';

export type ChatLevel = 'general' | 'project' | 'card';

/**
 * SmartSuggestions — lightweight contextual quick-reply chips.
 * Rendered above the textarea inside .chat-input-area.
 * No AI calls — all suggestions are static / rule-based.
 */
export class SmartSuggestions {
  private element: HTMLElement;
  private visible = true;
  private hiddenByTyping = false;

  constructor(
    private parentElement: HTMLElement,
    private onSelect: (text: string) => void,
  ) {
    this.element = createElement('div', { className: 'quick-replies', 'data-testid': 'quick-replies' });
    this.parentElement.appendChild(this.element);
    this.render();
  }

  // ─── Public API ───────────────────────────────────────────────────

  /** Called when the user starts typing — fade out chips. */
  onUserTyping(value: string): void {
    if (value.length > 0 && !this.hiddenByTyping) {
      this.hiddenByTyping = true;
      this.element.classList.add('quick-replies--hidden');
    } else if (value.length === 0 && this.hiddenByTyping) {
      this.hiddenByTyping = false;
      this.element.classList.remove('quick-replies--hidden');
    }
  }

  /** Called after an AI response — re-show chips based on response content. */
  onAiResponse(responseContent: string): void {
    this.hiddenByTyping = false;
    this.renderFollowUp(responseContent);
    this.element.classList.remove('quick-replies--hidden');
    this.show();
  }

  /** Re-render chips for the current context (called on context change). */
  refresh(): void {
    this.hiddenByTyping = false;
    this.render();
    this.element.classList.remove('quick-replies--hidden');
  }

  show(): void {
    this.visible = true;
    this.element.style.display = '';
  }

  hide(): void {
    this.visible = false;
    this.element.style.display = 'none';
  }

  destroy(): void {
    this.element.remove();
  }

  // ─── Internal ─────────────────────────────────────────────────────

  private getChatLevel(): ChatLevel {
    const cardId = appState.get('selectedCardId');
    if (cardId) return 'card';
    const activeTab = appState.getActiveTab();
    if (activeTab !== 'main') return 'project';
    return 'general';
  }

  private render(): void {
    const level = this.getChatLevel();
    let suggestions: string[];

    switch (level) {
      case 'general':
        suggestions = [
          'Create a new project',
          'What can you help me with?',
          'Show my projects',
        ];
        break;

      case 'project': {
        const projectId = appState.get('currentProjectId');
        const project = projectId ? appState.getProject(projectId) : null;
        const projectName = project?.name || 'this project';
        suggestions = [
          'Create a card',
          'Show the kanban board',
          "What's the project status?",
          `Help me with ${projectName}`,
        ];
        break;
      }

      case 'card':
        suggestions = [
          'Help me implement this',
          'Write tests for this',
          'What are the next steps?',
          'Break this into smaller tasks',
        ];
        break;

      default:
        suggestions = [];
    }

    this.renderChips(suggestions);
  }

  private renderFollowUp(responseContent: string): void {
    const lower = responseContent.toLowerCase();
    let suggestions: string[];

    // Detect code mentions
    const mentionsCode =
      lower.includes('```') ||
      lower.includes('function') ||
      lower.includes('implementation') ||
      lower.includes('code') ||
      lower.includes('snippet');

    // Detect task mentions
    const mentionsTasks =
      lower.includes('task') ||
      lower.includes('step') ||
      lower.includes('todo') ||
      lower.includes('card') ||
      lower.includes('action item');

    if (mentionsCode) {
      suggestions = [
        'Can you show me the implementation?',
        'Tell me more',
        'Give an example',
      ];
    } else if (mentionsTasks) {
      suggestions = [
        'Create cards for these tasks',
        'Tell me more',
        'Summarize',
      ];
    } else {
      suggestions = ['Tell me more', 'Give an example', 'Summarize'];
    }

    this.renderChips(suggestions);
  }

  private renderChips(suggestions: string[]): void {
    this.element.innerHTML = '';
    for (const text of suggestions) {
      const chip = createElement('button', {
        className: 'quick-reply-chip',
        type: 'button',
        title: text,
      }) as HTMLButtonElement;
      chip.textContent = text;
      chip.addEventListener('click', () => {
        this.onSelect(text);
        // Hide after selecting so it doesn't linger
        this.element.classList.add('quick-replies--hidden');
      });
      this.element.appendChild(chip);
    }
  }
}
