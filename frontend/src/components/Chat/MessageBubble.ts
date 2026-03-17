import { Message } from '../../types';
import { createElement, markdownToHtml, formatTime } from '../../utils/helpers';

export class MessageBubble {
  private element: HTMLElement;
  private contentEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement, private message: Message) {
    this.element = createElement('div', {
      className: `message-bubble message-${message.role}`,
      'data-message-id': message.id,
    });
    this.render();
  }

  render(): void {
    this.element.innerHTML = '';

    // Avatar
    const avatar = createElement('div', { className: 'message-avatar' });
    avatar.textContent = this.message.role === 'user' ? '👤' : '🔥';

    // Content wrapper
    const wrapper = createElement('div', { className: 'message-content-wrapper' });

    // Content
    this.contentEl = createElement('div', { className: 'message-content' });
    if (this.message.role === 'assistant') {
      this.contentEl.innerHTML = markdownToHtml(this.message.content);
    } else {
      this.contentEl.textContent = this.message.content;
    }

    // Streaming indicator
    if (this.message.streaming) {
      const cursor = createElement('span', { className: 'streaming-cursor' }, '▊');
      this.contentEl.appendChild(cursor);
    }

    // Timestamp
    const time = createElement('span', { className: 'message-time' }, formatTime(this.message.timestamp));

    wrapper.appendChild(this.contentEl);
    wrapper.appendChild(time);

    this.element.appendChild(avatar);
    this.element.appendChild(wrapper);

    this.parentElement.appendChild(this.element);
  }

  updateContent(content: string, streaming: boolean): void {
    if (!this.contentEl) return;

    if (this.message.role === 'assistant') {
      this.contentEl.innerHTML = markdownToHtml(content);
    } else {
      this.contentEl.textContent = content;
    }

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
    this.element.remove();
  }
}
