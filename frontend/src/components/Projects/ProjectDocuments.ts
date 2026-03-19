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

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
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

export class ProjectDocuments {
  private container: HTMLElement;
  private projectId: string;
  private docs: ProjectDocument[] = [];
  private listEl: HTMLElement | null = null;
  private badgeEl: HTMLElement | null = null;
  private uploading = false;
  private fileInput: HTMLInputElement | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'docs-view' });
    this.projectId = appState.get('currentProjectId') || '';
    this.render();
    this.loadDocs();
    this.parentElement.appendChild(this.container);
  }

  private render(): void {
    this.container.innerHTML = '';

    // Header
    const header = createElement('div', { className: 'docs-header' });

    // (page title handled by ProjectHeader)
    this.badgeEl = createElement('span', { className: 'badge' }, '0');
    this.badgeEl.style.cssText = 'background:var(--color-accent,#7c6ff7);color:#fff;border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600;';

    const uploadBtn = createElement('button', { className: 'btn btn-primary docs-upload-btn' }, '⬆️ Upload');
    uploadBtn.addEventListener('click', () => this.triggerFilePicker());

    header.appendChild(this.badgeEl);
    header.appendChild(uploadBtn);
    this.container.appendChild(header);

    // Hidden file input
    this.fileInput = createElement('input', {
      type: 'file',
      accept: '.txt,.md,.pdf,.docx,.xlsx',
      style: 'display:none',
    }) as HTMLInputElement;
    this.fileInput.addEventListener('change', () => this.handleFileInputChange());
    this.container.appendChild(this.fileInput);

    // Drop zone
    const dropZone = createElement('div', { className: 'docs-drop-zone' });
    dropZone.innerHTML = '<span style="color:var(--color-text-muted,#888);font-size:13px;">Drag &amp; drop files here, or click <strong>Upload</strong></span>';
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        this.uploadFile(files[0]);
      }
    });
    dropZone.addEventListener('click', () => this.triggerFilePicker());
    this.container.appendChild(dropZone);

    // Document list
    this.listEl = createElement('div', { className: 'docs-list' });
    this.listEl.style.marginTop = '16px';
    this.container.appendChild(this.listEl);

    this.renderList();
  }

  private renderList(): void {
    if (!this.listEl) return;
    this.listEl.innerHTML = '';

    if (this.badgeEl) this.badgeEl.textContent = String(this.docs.length);

    if (this.docs.length === 0) {
      const empty = createElement('div', { className: 'docs-empty' });
      empty.style.cssText = 'text-align:center;padding:32px 0;color:var(--color-text-muted,#888);font-size:13px;';
      empty.textContent = 'No documents yet. Upload files to give Voxy context about this project.';
      this.listEl.appendChild(empty);
      return;
    }

    for (const doc of this.docs) {
      const item = createElement('div', { className: 'doc-item' });

      const icon = createElement('span', { className: 'doc-icon' }, getDocIcon(doc.filename, doc.mime_type));

      const nameEl = createElement('span', { className: 'doc-name' }, doc.filename);

      const meta = createElement('span', { className: 'doc-meta' },
        `${formatBytes(doc.file_size)} · ${formatDate(doc.created_at)}`);

      const deleteBtn = createElement('button', { className: 'btn btn-ghost doc-delete', title: 'Delete document' }, '🗑️');
      deleteBtn.style.cssText = 'padding:4px 8px;font-size:14px;opacity:0.6;';
      deleteBtn.addEventListener('mouseenter', () => { deleteBtn.style.opacity = '1'; });
      deleteBtn.addEventListener('mouseleave', () => { deleteBtn.style.opacity = '0.6'; });
      deleteBtn.addEventListener('click', () => this.deleteDoc(doc.id, doc.filename));

      item.appendChild(icon);
      item.appendChild(nameEl);
      item.appendChild(meta);
      item.appendChild(deleteBtn);

      this.listEl.appendChild(item);
    }
  }

  private triggerFilePicker(): void {
    this.fileInput?.click();
  }

  private handleFileInputChange(): void {
    const files = this.fileInput?.files;
    if (files && files.length > 0) {
      this.uploadFile(files[0]);
      // Reset so same file can be re-uploaded
      if (this.fileInput) this.fileInput.value = '';
    }
  }

  private async uploadFile(file: File): Promise<void> {
    if (this.uploading) return;
    if (!this.projectId) {
      eventBus.emit(EVENTS.TOAST_SHOW, { message: '❌ No project selected', type: 'error' });
      return;
    }

    // Check file extension
    const allowedExts = ['.txt', '.md', '.pdf', '.docx', '.xlsx'];
    const ext = '.' + (file.name.split('.').pop()?.toLowerCase() || '');
    if (!allowedExts.includes(ext)) {
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `❌ File type not supported: ${ext}`,
        type: 'error',
      });
      return;
    }

    this.uploading = true;
    const uploadBtn = this.container.querySelector('.docs-upload-btn') as HTMLButtonElement | null;
    if (uploadBtn) {
      uploadBtn.disabled = true;
      uploadBtn.textContent = '⏳ Uploading…';
    }

    try {
      const baseUrl = API_URL || '';
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errText = await response.text();
        throw new Error(errText || `HTTP ${response.status}`);
      }

      // Show toast and fire document_uploaded event (App.ts handles activity/notification)
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `✅ Document indexed`,
        type: 'success',
        duration: 3000,
      });
      eventBus.emit(EVENTS.DOCUMENT_UPLOADED, { filename: file.name, projectId: this.projectId });

      // Refresh list
      await this.loadDocs();
    } catch (err) {
      console.error('[ProjectDocuments] upload error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `❌ Upload failed: ${(err as Error).message}`,
        type: 'error',
      });
    } finally {
      this.uploading = false;
      if (uploadBtn) {
        uploadBtn.disabled = false;
        uploadBtn.textContent = '⬆️ Upload';
      }
    }
  }

  private async deleteDoc(docId: string, filename: string): Promise<void> {
    if (!this.projectId) return;

    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents/${docId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      this.docs = this.docs.filter((d) => d.id !== docId);
      this.renderList();

      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `🗑️ "${filename}" removed`,
        type: 'info',
        duration: 2500,
      });
    } catch (err) {
      console.error('[ProjectDocuments] delete error:', err);
      eventBus.emit(EVENTS.TOAST_SHOW, {
        message: `❌ Delete failed`,
        type: 'error',
      });
    }
  }

  private async loadDocs(): Promise<void> {
    if (!this.projectId) return;

    try {
      const baseUrl = API_URL || '';
      const response = await fetch(`${baseUrl}/api/projects/${this.projectId}/documents`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as ProjectDocument[];
      this.docs = data;
      this.renderList();
    } catch (err) {
      console.error('[ProjectDocuments] loadDocs error:', err);
    }
  }

  update(_data: unknown): void {
    // No-op
  }

  destroy(): void {
    this.container.remove();
  }
}
