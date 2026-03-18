import { Message } from '../../types';
import { createElement, formatTime } from '../../utils/helpers';
import { renderMarkdown, addCodeCopyButtons, enhanceImages, replaceEmojiShortcodes } from '../../utils/markdown';
import { ttsService } from '../../services/TtsService';

export class MessageBubble {
  private element: HTMLElement;
  private contentEl: HTMLElement | null = null;
  private ttsBtnEl: HTMLElement | null = null;
  private ttsUnsubscribe: (() => void) | null = null;

  constructor(private parentElement: HTMLElement, private message: Message) {
    this.element = createElement('div', {
      className: `message-bubble message-${message.role}`,
      'data-message-id': message.id,
    });
    this.render();
  }

  render(): void {
    this.element.innerHTML = '';

    // Cleanup previous TTS listener if re-rendering
    if (this.ttsUnsubscribe) {
      this.ttsUnsubscribe();
      this.ttsUnsubscribe = null;
    }

    // Add enrichment class if applicable
    if (this.message.enrichment) {
      this.element.classList.add('message-enrichment');
      if (this.message.enrichmentAction === 'correct') {
        this.element.classList.add('message-correction');
      }
    }

    // Avatar
    const avatar = createElement('div', { className: 'message-avatar' });
    avatar.textContent = this.message.role === 'user' ? '👤' : this.message.enrichment ? '💭' : '🔥';

    // Content wrapper
    const wrapper = createElement('div', { className: 'message-content-wrapper' });

    // Content
    this.contentEl = createElement('div', { className: 'message-content' });
    this.renderContent(this.message.content);

    // Streaming indicator
    if (this.message.streaming) {
      const cursor = createElement('span', { className: 'streaming-cursor' }, '▊');
      this.contentEl.appendChild(cursor);
    }

    // Message meta (model badge + timestamp + TTS button)
    const meta = createElement('div', { className: 'message-meta' });

    // Model badge (assistant messages only)
    if (this.message.role === 'assistant' && this.message.model) {
      const badgeInfo = this.getModelBadge(this.message.model);
      const badge = createElement('span', {
        className: `model-badge model-${this.message.model}`,
      }, badgeInfo);
      meta.appendChild(badge);
    }

    const time = createElement('span', { className: 'message-time' }, formatTime(this.message.timestamp));
    meta.appendChild(time);

    // TTS speaker button — assistant messages only
    if (this.message.role === 'assistant') {
      this.ttsBtnEl = this.buildTtsButton();
      meta.appendChild(this.ttsBtnEl);
    }

    wrapper.appendChild(this.contentEl);
    wrapper.appendChild(meta);

    this.element.appendChild(avatar);
    this.element.appendChild(wrapper);

    this.parentElement.appendChild(this.element);
  }

  private buildTtsButton(): HTMLElement {
    const btn = createElement('button', {
      className: 'tts-speak-btn',
      title: 'Read aloud',
      type: 'button',
    }, '🔊');

    let isSpeakingThis = false;

    const updateBtn = () => {
      if (isSpeakingThis && ttsService.isSpeaking) {
        btn.textContent = '⏹';
        btn.title = 'Stop';
        btn.classList.add('tts-speaking');
      } else {
        isSpeakingThis = false;
        btn.textContent = '🔊';
        btn.title = 'Read aloud';
        btn.classList.remove('tts-speaking');
      }
    };

    // Subscribe to end events so button resets when audio finishes
    this.ttsUnsubscribe = ttsService.onEnd(() => {
      if (isSpeakingThis) {
        isSpeakingThis = false;
        updateBtn();
      }
    });

    btn.addEventListener('click', async (e) => {
      e.stopPropagation();

      if (isSpeakingThis && ttsService.isSpeaking) {
        // Stop playback
        ttsService.stop();
        isSpeakingThis = false;
        updateBtn();
        return;
      }

      // Speak this message
      isSpeakingThis = true;
      updateBtn();

      // Get plain text from the message content (strip markdown HTML)
      const plainText = this.getPlainText();
      await ttsService.speak(plainText);

      // Reset in case onEnd wasn't fired (e.g. error)
      if (isSpeakingThis) {
        isSpeakingThis = false;
        updateBtn();
      }
    });

    return btn;
  }

  /** Extract plain text from rendered message content. */
  private getPlainText(): string {
    if (!this.contentEl) return this.message.content;
    return this.contentEl.textContent || this.message.content;
  }

  private renderContent(content: string): void {
    if (!this.contentEl) return;
    const processed = replaceEmojiShortcodes(content);
    if (this.message.role === 'assistant') {
      this.contentEl.innerHTML = renderMarkdown(processed);
      addCodeCopyButtons(this.contentEl);
      enhanceImages(this.contentEl);
    } else {
      this.contentEl.textContent = processed;
    }
  }

  private getModelBadge(model: string): string {
    switch (model) {
      case 'fast': return '⚡ fast';
      case 'deep': return '🧠 deep';
      case 'sonnet': return '✨ sonnet';
      case 'analyzer': return '🔍 analyzer';
      default: return model;
    }
  }

  updateContent(content: string, streaming: boolean): void {
    if (!this.contentEl) return;

    this.renderContent(content);

    if (streaming) {
      const existing = this.contentEl.querySelector('.streaming-cursor');
      if (!existing) {
        const cursor = createElement('span', { className: 'streaming-cursor' }, '▊');
        this.contentEl.appendChild(cursor);
      }
    } else {
      const cursor = this.contentEl.querySelector('.streaming-cursor');
      cursor?.remove();
    }

    this.message.content = content;
    this.message.streaming = streaming;
  }

  destroy(): void {
    if (this.ttsUnsubscribe) {
      this.ttsUnsubscribe();
      this.ttsUnsubscribe = null;
    }
    this.element.remove();
  }
}
