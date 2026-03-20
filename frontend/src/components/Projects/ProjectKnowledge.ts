import { createElement } from '../../utils/helpers';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS, API_URL } from '../../utils/constants';

interface ProjectDocument {
  id: string;
  filename: string;
  file_size: number;
  mime_type: string;
  created_at: string;
}

interface WikiPageSummary {
  id: string;
  title: string;
  updated_at: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}

function getDocIcon(filename: string, mimeType: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  if (ext === 'pdf' || mimeType === 'application/pdf') return '📕';
  if (ext === 'xlsx' || ext === 'xls' || mimeType.includes('spreadsheet') || mimeType.includes('excel')) return '📊';
  if (ext === 'docx' || ext === 'doc' || mimeType.includes('word') || mimeType.includes('msword')) return '📝';
  if (ext === 'md') return '📋';
  return '📄';
}

export class ProjectKnowledge {
  private container: HTMLElement;
  private projectId: string;
  private docs: ProjectDocument[] = [];
  private wikiPages: WikiPageSummary[] = [];
  private uploading = false;
  private fileInput: HTMLInputElement | null = null;
  private docsListEl: HTMLElement | null = null;
  private wikiListEl: HTMLElement | null = null;
  private ragListEl: HTMLElement | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'knowledge-view' });
    this.projectId = appState.get('currentProjectId') || '';
    this.render();
    this.loadData();
    this.parentElement.appendChild(this.container);
  }

  private render(): void {
    this.container.innerHTML = '';

    // --- Section 1: Documents ---
    const docsSection = this.createSection('📄 Documents', 'Upload files to give Voxy context about this project.');

    // Upload area
    const uploadRow = createElement('div', { className: 'knowledge-upload-row' });
    const uploadBtn = createElement('button', { className: 'btn btn-primary knowledge-upload-btn' }, '⬆️ Upload');
    uploadBtn.addEventListener('click', () => this.triggerFilePicker());
    uploadRow.appendChild(uploadBtn);
    docsSection.appendChild(uploadRow);

    this.fileInput = createElement('input', {
      type: 'file',
      accept: '.txt,.md,.pdf,.docx,.xlsx',
      style: 'display:none',
    }) as HTMLInputElement;
    this.fileInput.addEventListener('change', () => this.handleFileInputChange());
    docsSection.appendChild(this.fileInput);

    // Drop zone
    const dropZone = createElement('div', { className: 'knowledge-drop-zone' });
    dropZone.innerHTML = '<span>Drag & drop files here, or click <strong>Upload</strong></span>';
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) this.uploadFile(files[0]);
    });
    dropZone.addEventListener('click', () => this.triggerFilePicker());
    docsSection.appendChild(dropZone);

    this.docsListEl = createElement('div', { className: 'knowledge-list' });
    docsSection.appendChild(this.docsListEl);
    this.container.appendChild(docsSection);

    // --- Section 2: Wiki Pages ---
    const wikiSection = this.createSection('📖 Wiki Pages', 'No wiki pages yet.');
    this.wikiListEl = createElement('div', { className: 'knowledge-list' });
    wikiSection.appendChild(this.wikiListEl);
    this.container.appendChild(wikiSection);

    // --- Section 3: RAG Sources ---
    const ragSection = this.createSection('🔗 RAG Sources', 'No knowledge sources yet. Add documents above or link external docs.');
    this.ragListEl = createElement('div', { className: 'knowledge-list' });
    ragSection.appendChild(this.ragListEl);
    this.container.appendChild(ragSection);
  }

  private createSection(title: string, _emptyText: string): HTMLElement {
    const section = createElement('div', { className: 'knowledge-section' });
    const header = createElement('h3', { className: 'knowledge-section-title' }, title);
    section.appendChild(header);
    return section;
  }

  private async loadData(): Promise<void> {
    await Promise.all([this.loadDocs(), this.loadWiki(), this.loadRagSources()]);
  }

  // --- Documents ---

  private async loadDocs(): Promise<void> {
    if (!this.projectId) return;
    try {
      const baseUrl = API_URL || '';
      const res = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.docs = await res.json();
    } catch (err) {
      console.error('[ProjectKnowledge] loadDocs error:', err);
      this.docs = [];
    }
    this.renderDocsList();
  }

  private renderDocsList(): void {
    if (!this.docsListEl) return;
    this.docsListEl.innerHTML = '';

    if (this.docs.length === 0) {
      this.docsListEl.appendChild(this.createEmpty('No documents uploaded yet.'));
      return;
    }

    for (const doc of this.docs) {
      const item = createElement('div', { className: 'knowledge-item' });
      item.appendChild(createElement('span', { className: 'knowledge-item-icon' }, getDocIcon(doc.filename, doc.mime_type)));
      item.appendChild(createElement('span', { className: 'knowledge-item-name' }, doc.filename));
      item.appendChild(createElement('span', { className: 'knowledge-item-meta' }, `${formatBytes(doc.file_size)} · ${formatDate(doc.created_at)}`));

      const deleteBtn = createElement('button', { className: 'btn btn-ghost knowledge-item-delete', title: 'Delete' }, '🗑️');
      deleteBtn.addEventListener('click', () => this.deleteDoc(doc.id, doc.filename));
      item.appendChild(deleteBtn);

      this.docsListEl.appendChild(item);
    }
  }

  private triggerFilePicker(): void {
    this.fileInput?.click();
  }

  private handleFileInputChange(): void {
    const files = this.fileInput?.files;
    if (files && files.length > 0) {
      this.uploadFile(files[0]);
      if (this.fileInput) this.fileInput.value = '';
    }
  }

  private async uploadFile(file: File): Promise<void> {
    if (this.uploading || !this.projectId) return;

    const allowedExts = ['.txt', '.md', '.pdf', '.docx', '.xlsx'];
    const ext = '.' + (file.name.split('.').pop()?.toLowerCase() || '');
    if (!allowedExts.includes(ext)) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `File type not supported: ${ext}`, type: 'error' });
      return;
    }

    this.uploading = true;
    const uploadBtn = this.container.querySelector('.knowledge-upload-btn') as HTMLButtonElement | null;
    if (uploadBtn) { uploadBtn.disabled = true; uploadBtn.textContent = '⏳ Uploading…'; }

    try {
      const baseUrl = API_URL || '';
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents`, { method: 'POST', body: formData });
      if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);

      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Document indexed', type: 'success', duration: 3000 });
      eventBus.emit(EVENTS.DOCUMENT_UPLOADED, { filename: file.name, projectId: this.projectId });
      await this.loadDocs();
    } catch (err) {
      console.error('[ProjectKnowledge] upload error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `Upload failed: ${(err as Error).message}`, type: 'error' });
    } finally {
      this.uploading = false;
      if (uploadBtn) { uploadBtn.disabled = false; uploadBtn.textContent = '⬆️ Upload'; }
    }
  }

  private async deleteDoc(docId: string, filename: string): Promise<void> {
    if (!this.projectId) return;
    try {
      const baseUrl = API_URL || '';
      const res = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents/${docId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.docs = this.docs.filter((d) => d.id !== docId);
      this.renderDocsList();
      eventBus.emit(EVENTS.TOAST_SHOW, { message: `"${filename}" removed`, type: 'info', duration: 2500 });
    } catch (err) {
      console.error('[ProjectKnowledge] delete error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, { message: 'Delete failed', type: 'error' });
    }
  }

  // --- Wiki ---

  private async loadWiki(): Promise<void> {
    if (!this.projectId) return;
    try {
      const res = await fetch(`/api/projects/${this.projectId}/wiki`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this.wikiPages = await res.json();
    } catch (err) {
      console.error('[ProjectKnowledge] loadWiki error:', err);
      this.wikiPages = [];
    }
    this.renderWikiList();
  }

  private renderWikiList(): void {
    if (!this.wikiListEl) return;
    this.wikiListEl.innerHTML = '';

    if (this.wikiPages.length === 0) {
      this.wikiListEl.appendChild(this.createEmpty('No wiki pages yet.'));
      return;
    }

    for (const page of this.wikiPages) {
      const item = createElement('div', { className: 'knowledge-item' });
      item.appendChild(createElement('span', { className: 'knowledge-item-icon' }, '📖'));
      item.appendChild(createElement('span', { className: 'knowledge-item-name' }, page.title || 'Untitled'));
      item.appendChild(createElement('span', { className: 'knowledge-item-meta' }, formatDate(page.updated_at)));
      this.wikiListEl.appendChild(item);
    }
  }

  // --- RAG Sources ---

  private async loadRagSources(): Promise<void> {
    if (!this.ragListEl) return;
    this.ragListEl.innerHTML = '';

    const project = this.projectId ? appState.getProject(this.projectId) : null;
    const techStack = (project as unknown as Record<string, unknown>)?.tech_stack as string[] | undefined;
    let hasItems = false;

    if (techStack && techStack.length > 0) {
      for (const tech of techStack) {
        const item = createElement('div', { className: 'knowledge-item' });
        item.appendChild(createElement('span', { className: 'knowledge-item-icon' }, '⚙️'));
        item.appendChild(createElement('span', { className: 'knowledge-item-name' }, tech));
        item.appendChild(createElement('span', { className: 'knowledge-rag-status indexed' }, 'auto-detected'));
        this.ragListEl.appendChild(item);
        hasItems = true;
      }
    }

    if (this.docs.length > 0) {
      const item = createElement('div', { className: 'knowledge-item' });
      item.appendChild(createElement('span', { className: 'knowledge-item-icon' }, '📄'));
      item.appendChild(createElement('span', { className: 'knowledge-item-name' }, `${this.docs.length} document${this.docs.length === 1 ? '' : 's'} indexed`));
      item.appendChild(createElement('span', { className: 'knowledge-rag-status indexed' }, 'indexed'));
      this.ragListEl.appendChild(item);
      hasItems = true;
    }

    if (this.wikiPages.length > 0) {
      const item = createElement('div', { className: 'knowledge-item' });
      item.appendChild(createElement('span', { className: 'knowledge-item-icon' }, '📖'));
      item.appendChild(createElement('span', { className: 'knowledge-item-name' }, `${this.wikiPages.length} wiki page${this.wikiPages.length === 1 ? '' : 's'}`));
      item.appendChild(createElement('span', { className: 'knowledge-rag-status indexed' }, 'indexed'));
      this.ragListEl.appendChild(item);
      hasItems = true;
    }

    if (!hasItems) {
      this.ragListEl.appendChild(this.createEmpty('No knowledge sources yet. Add documents above or link external docs.'));
    }
  }

  // --- Helpers ---

  private createEmpty(text: string): HTMLElement {
    const el = createElement('div', { className: 'knowledge-empty' });
    el.textContent = text;
    return el;
  }

  destroy(): void {
    this.container.remove();
  }
}
