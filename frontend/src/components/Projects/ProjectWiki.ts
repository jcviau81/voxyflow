import { createElement } from '../../utils/helpers';
import { renderMarkdown } from '../../utils/markdown';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';

interface WikiPageSummary {
  id: string;
  title: string;
  updated_at: string;
}

interface WikiPageDetail extends WikiPageSummary {
  project_id: string;
  content: string;
  created_at: string;
}

export class ProjectWiki {
  private container: HTMLElement;
  private projectId: string;
  private pages: WikiPageSummary[] = [];
  private activePage: WikiPageDetail | null = null;
  private previewMode = false;
  private dirty = false;

  // DOM refs
  private sidebar: HTMLElement | null = null;
  private editor: HTMLElement | null = null;
  private titleInput: HTMLInputElement | null = null;
  private contentArea: HTMLTextAreaElement | null = null;
  private previewDiv: HTMLElement | null = null;
  private saveBtn: HTMLButtonElement | null = null;
  private previewBtn: HTMLButtonElement | null = null;
  private pageListEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'wiki-view' });
    this.projectId = appState.get('currentProjectId') || '';

    this.render();
    this.loadPages();
    this.parentElement.appendChild(this.container);
  }

  private render(): void {
    this.container.innerHTML = '';

    // --- Sidebar ---
    this.sidebar = createElement('div', { className: 'wiki-sidebar' });

    // Sidebar header — title removed, project name + tabs are in shared ProjectHeader
    const sidebarHeader = createElement('div', { className: 'wiki-sidebar-header' });
    const sidebarTitle = createElement('span', { className: 'wiki-sidebar-title' }, 'Pages');
    const newPageBtn = createElement('button', { className: 'wiki-new-page-btn', title: 'New page' }, '+');
    newPageBtn.addEventListener('click', () => this.handleNewPage());
    sidebarHeader.appendChild(sidebarTitle);
    sidebarHeader.appendChild(newPageBtn);

    this.pageListEl = createElement('div', { className: 'wiki-page-list' });

    this.sidebar.appendChild(sidebarHeader);
    this.sidebar.appendChild(this.pageListEl);

    // --- Editor area ---
    this.editor = createElement('div', { className: 'wiki-editor' });

    const emptyState = createElement('div', { className: 'wiki-empty-state' });
    emptyState.innerHTML = '<p>Select a page from the sidebar or create a new one.</p>';
    this.editor.appendChild(emptyState);

    this.container.appendChild(this.sidebar);
    this.container.appendChild(this.editor);
  }

  private renderPageList(): void {
    if (!this.pageListEl) return;
    this.pageListEl.innerHTML = '';

    if (this.pages.length === 0) {
      const empty = createElement('div', { className: 'wiki-no-pages' }, 'No pages yet. Hit + to start.');
      this.pageListEl.appendChild(empty);
      return;
    }

    for (const page of this.pages) {
      const item = createElement('div', {
        className: `wiki-page-item ${this.activePage?.id === page.id ? 'active' : ''}`,
        'data-page-id': page.id,
      });
      const titleEl = createElement('span', { className: 'wiki-page-item-title' }, page.title || 'Untitled');
      const dateEl = createElement('span', { className: 'wiki-page-item-date' }, this.formatDate(page.updated_at));
      item.appendChild(titleEl);
      item.appendChild(dateEl);
      item.addEventListener('click', () => this.loadPage(page.id));
      this.pageListEl!.appendChild(item);
    }
  }

  private renderEditor(): void {
    if (!this.editor) return;
    this.editor.innerHTML = '';

    if (!this.activePage) {
      const empty = createElement('div', { className: 'wiki-empty-state' });
      empty.innerHTML = '<p>Select a page from the sidebar or create a new one.</p>';
      this.editor.appendChild(empty);
      return;
    }

    // Toolbar
    const toolbar = createElement('div', { className: 'wiki-toolbar' });

    this.titleInput = createElement('input', {
      className: 'wiki-title-input',
      type: 'text',
      placeholder: 'Page title…',
      value: this.activePage.title,
    }) as HTMLInputElement;
    this.titleInput.addEventListener('input', () => { this.dirty = true; this.updateSaveBtn(); });

    this.saveBtn = createElement('button', {
      className: 'wiki-save-btn',
      title: 'Save (Ctrl+S)',
      disabled: 'true',
    }, '💾 Save') as HTMLButtonElement;
    this.saveBtn.disabled = true;
    this.saveBtn.addEventListener('click', () => this.handleSave());

    this.previewBtn = createElement('button', {
      className: `wiki-preview-btn ${this.previewMode ? 'active' : ''}`,
      title: 'Toggle preview',
    }, this.previewMode ? '✏️ Edit' : '👁 Preview') as HTMLButtonElement;
    this.previewBtn.addEventListener('click', () => this.togglePreview());

    const deleteBtn = createElement('button', {
      className: 'wiki-delete-btn',
      title: 'Delete page',
    }, '🗑️');
    deleteBtn.addEventListener('click', () => this.handleDelete());

    toolbar.appendChild(this.titleInput);
    toolbar.appendChild(this.saveBtn);
    toolbar.appendChild(this.previewBtn);
    toolbar.appendChild(deleteBtn);

    // Content area
    const body = createElement('div', { className: 'wiki-body' });

    this.contentArea = createElement('textarea', {
      className: `wiki-content-textarea ${this.previewMode ? 'hidden' : ''}`,
      placeholder: 'Write your page in Markdown…',
    }) as HTMLTextAreaElement;
    this.contentArea.value = this.activePage.content;
    this.contentArea.addEventListener('input', () => { this.dirty = true; this.updateSaveBtn(); });
    // Ctrl+S shortcut
    this.contentArea.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        this.handleSave();
      }
    });

    this.previewDiv = createElement('div', {
      className: `wiki-preview ${this.previewMode ? '' : 'hidden'}`,
    });
    if (this.previewMode) {
      this.previewDiv.innerHTML = renderMarkdown(this.activePage.content);
    }

    body.appendChild(this.contentArea);
    body.appendChild(this.previewDiv);

    this.editor.appendChild(toolbar);
    this.editor.appendChild(body);
  }

  private async loadPages(): Promise<void> {
    if (!this.projectId) return;
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki`);
      if (!res.ok) throw new Error('Failed to load wiki pages');
      this.pages = await res.json();
      this.renderPageList();

      // Auto-select first page
      if (this.pages.length > 0 && !this.activePage) {
        await this.loadPage(this.pages[0].id);
      }
    } catch (err) {
      console.error('[ProjectWiki] loadPages error:', err);
    }
  }

  private async loadPage(pageId: string): Promise<void> {
    if (!this.projectId) return;
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki/${pageId}`);
      if (!res.ok) throw new Error('Failed to load wiki page');
      this.activePage = await res.json();
      this.previewMode = false;
      this.dirty = false;
      this.renderPageList();
      this.renderEditor();
    } catch (err) {
      console.error('[ProjectWiki] loadPage error:', err);
    }
  }

  private async handleNewPage(): Promise<void> {
    if (!this.projectId) return;
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Page', content: '' }),
      });
      if (!res.ok) throw new Error('Failed to create wiki page');
      const page: WikiPageDetail = await res.json();
      this.pages.unshift({ id: page.id, title: page.title, updated_at: page.updated_at });
      this.activePage = page;
      this.previewMode = false;
      this.dirty = false;
      this.renderPageList();
      this.renderEditor();
      // Focus title
      setTimeout(() => this.titleInput?.focus(), 50);
    } catch (err) {
      console.error('[ProjectWiki] handleNewPage error:', err);
    }
  }

  private async handleSave(): Promise<void> {
    if (!this.activePage || !this.projectId) return;
    const title = this.titleInput?.value.trim() || 'Untitled';
    const content = this.contentArea?.value || '';
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki/${this.activePage.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content }),
      });
      if (!res.ok) throw new Error('Failed to save wiki page');
      const updated: WikiPageDetail = await res.json();
      this.activePage = updated;
      // Update sidebar list entry
      const idx = this.pages.findIndex((p) => p.id === updated.id);
      if (idx !== -1) {
        this.pages[idx] = { id: updated.id, title: updated.title, updated_at: updated.updated_at };
      }
      this.dirty = false;
      this.updateSaveBtn();
      this.renderPageList();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '📖 Wiki page saved', type: 'success', duration: 2000 });
    } catch (err) {
      console.error('[ProjectWiki] handleSave error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Failed to save page', type: 'error' });
    }
  }

  private async handleDelete(): Promise<void> {
    if (!this.activePage || !this.projectId) return;
    const confirmed = window.confirm(`Delete page "${this.activePage.title}"? This cannot be undone.`);
    if (!confirmed) return;
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki/${this.activePage.id}`, {
        method: 'DELETE',
      });
      if (!res.ok && res.status !== 204) throw new Error('Failed to delete wiki page');
      this.pages = this.pages.filter((p) => p.id !== this.activePage!.id);
      this.activePage = null;
      this.dirty = false;
      this.renderPageList();

      // Load next page if available
      if (this.pages.length > 0) {
        await this.loadPage(this.pages[0].id);
      } else {
        this.renderEditor();
      }
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '🗑️ Page deleted', type: 'success', duration: 2000 });
    } catch (err) {
      console.error('[ProjectWiki] handleDelete error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ Failed to delete page', type: 'error' });
    }
  }

  private togglePreview(): void {
    this.previewMode = !this.previewMode;
    if (!this.contentArea || !this.previewDiv || !this.previewBtn) return;

    if (this.previewMode) {
      const content = this.contentArea.value;
      this.previewDiv.innerHTML = renderMarkdown(content);
      this.contentArea.classList.add('hidden');
      this.previewDiv.classList.remove('hidden');
      this.previewBtn.textContent = '✏️ Edit';
      this.previewBtn.classList.add('active');
    } else {
      this.contentArea.classList.remove('hidden');
      this.previewDiv.classList.add('hidden');
      this.previewBtn.textContent = '👁 Preview';
      this.previewBtn.classList.remove('active');
    }
  }

  private updateSaveBtn(): void {
    if (!this.saveBtn) return;
    this.saveBtn.disabled = !this.dirty;
  }

  private formatDate(iso: string): string {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  }

  destroy(): void {
    this.container.remove();
  }
}
