import { useRef, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, Trash2, Loader2, File, FileText, FileCode, BookOpen, Sheet, Image as ImageIcon, AlertTriangle } from 'lucide-react';
import { useWorkspaceStore } from '../../stores/useWorkspaceStore';
import { useToastStore } from '../../stores/useToastStore';
import type { LucideIcon } from 'lucide-react';

// Shape returned by GET /api/workspaces/{id}/documents — must match the backend
// DocumentResponse (size_bytes / filetype / chunk_count / indexed_at), NOT the
// older file_size / mime_type guess that crashed the render.
interface WorkspaceDocument {
  id: string;
  filename: string;
  filetype: string;        // ".pdf", ".png", … (extension, may be "")
  size_bytes: number;
  chunk_count: number;
  created_at: string;
  indexed_at: string | null;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
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

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'svg', 'heic'];
const CODE_EXTS = ['md', 'markdown', 'txt', 'json', 'yaml', 'yml', 'html', 'htm', 'xml', 'csv', 'py', 'js', 'ts', 'tsx', 'sh', 'log'];

// Derive the icon from the filename extension only. The previous version read a
// non-existent `mime_type` field and called `.includes()` on undefined, which
// threw during render and white-screened the whole panel.
function getDocIconComponent(filename: string): LucideIcon {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf') return BookOpen;
  if (ext === 'xlsx' || ext === 'xls' || ext === 'csv') return Sheet;
  if (ext === 'docx' || ext === 'doc') return FileText;
  if (IMAGE_EXTS.includes(ext)) return ImageIcon;
  if (CODE_EXTS.includes(ext)) return FileCode;
  return File;
}

function DocIcon({ filename }: { filename: string }) {
  const Icon = getDocIconComponent(filename);
  return <Icon size={14} className="shrink-0 text-muted-foreground" />;
}

export function WorkspaceDocuments() {
  const workspaceId = useWorkspaceStore(s => s.currentWorkspaceId);
  const { showToast } = useToastStore();
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);

  const { data: docs = [] } = useQuery<WorkspaceDocument[]>({
    queryKey: ['workspaces', workspaceId, 'documents'],
    queryFn: async () => {
      const res = await fetch(`/api/workspaces/${workspaceId}/documents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as WorkspaceDocument[] | { documents: WorkspaceDocument[] };
      return Array.isArray(data) ? data : (data.documents ?? []);
    },
    enabled: !!workspaceId,
    staleTime: 30_000,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!workspaceId) throw new Error('No workspace selected');
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/workspaces/${workspaceId}/documents`, { method: 'POST', body: formData });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }
      return res.json() as Promise<WorkspaceDocument>;
    },
    onSuccess: (doc) => {
      void qc.invalidateQueries({ queryKey: ['workspaces', workspaceId, 'documents'] });
      if (doc && doc.chunk_count === 0) {
        showToast(`"${doc.filename}" stored but no text could be indexed`, 'info', 4000);
      }
    },
    onError: (err: Error, file) => {
      showToast(`Upload failed${file ? ` (${file.name})` : ''}: ${err.message}`, 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async ({ docId }: { docId: string; filename: string }) => {
      const res = await fetch(`/api/workspaces/${workspaceId}/documents/${docId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: (_data, { filename }) => {
      void qc.invalidateQueries({ queryKey: ['workspaces', workspaceId, 'documents'] });
      showToast(`"${filename}" removed`, 'info', 2500);
    },
    onError: () => {
      showToast('Delete failed', 'error');
    },
  });

  // Upload all selected/dropped files. The backend accepts any type and stores
  // a record even when it cannot extract text, so there is no client-side gate.
  const handleFiles = useCallback(async (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    let indexed = 0;
    setUploadingCount(c => c + arr.length);
    for (const file of arr) {
      try {
        await uploadMutation.mutateAsync(file);
        indexed += 1;
      } catch {
        /* per-file error toast already fired in onError */
      } finally {
        setUploadingCount(c => c - 1);
      }
    }
    if (arr.length > 1 && indexed > 0) {
      showToast(`Uploaded ${indexed}/${arr.length} file${arr.length === 1 ? '' : 's'}`, 'success', 3000);
    } else if (arr.length === 1 && indexed === 1) {
      showToast('Document indexed', 'success', 3000);
    }
  }, [uploadMutation, showToast]);

  const handleFileInputChange = useCallback(() => {
    const files = fileInputRef.current?.files;
    if (files && files.length > 0) {
      void handleFiles(files);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [handleFiles]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) void handleFiles(files);
  }, [handleFiles]);

  const isUploading = uploadingCount > 0;

  if (!workspaceId) {
    return (
      <div className="docs-view">
        <div className="docs-empty" style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-muted, #888)', fontSize: '13px' }}>
          No workspace selected.
        </div>
      </div>
    );
  }

  return (
    <div className="docs-view">
      {/* Header */}
      <div className="docs-header">
        <span
          className="badge"
          style={{ background: 'var(--color-accent, #ff6b6b)', color: '#fff', borderRadius: '12px', padding: '2px 8px', fontSize: '11px', fontWeight: 600 }}
        >
          {docs.length}
        </span>
        <button
          className="btn btn-primary docs-upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
        >
          {isUploading
            ? <><Loader2 size={13} className="animate-spin" /> Uploading{uploadingCount > 1 ? ` ${uploadingCount}…` : '…'}</>
            : <><Upload size={13} /> Upload</>}
        </button>
      </div>

      {/* Hidden file input — any type, multiple files */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        style={{ display: 'none' }}
        onChange={handleFileInputChange}
      />

      {/* Drop zone */}
      <div
        className={`docs-drop-zone${isDragOver ? ' dragover' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <span style={{ color: 'var(--color-text-muted, #888)', fontSize: '13px' }}>
          Drag &amp; drop files here, or click <strong>Upload</strong> — PDF, Office, images, or any file
        </span>
      </div>

      {/* Document list */}
      <div className="docs-list" style={{ marginTop: '16px' }}>
        {docs.length === 0 ? (
          <div
            className="docs-empty"
            style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-muted, #888)', fontSize: '13px' }}
          >
            No documents yet. Upload files to give Voxy context about this workspace.
          </div>
        ) : (
          docs.map((doc) => {
            const notIndexed = !doc.chunk_count;
            return (
              <div key={doc.id} className="doc-item">
                <span className="doc-icon"><DocIcon filename={doc.filename} /></span>
                <span className="doc-name">{doc.filename}</span>
                <span className="doc-meta">
                  {formatBytes(doc.size_bytes)} · {formatDate(doc.created_at)}
                  {notIndexed
                    ? <span title="Stored, but no searchable text was extracted" style={{ marginLeft: 6, color: 'var(--color-warning, #d4a72c)', display: 'inline-flex', alignItems: 'center', gap: 3 }}><AlertTriangle size={11} /> not indexed</span>
                    : <span style={{ marginLeft: 6, opacity: 0.7 }}>· {doc.chunk_count} chunk{doc.chunk_count === 1 ? '' : 's'}</span>}
                </span>
                <button
                  className="btn btn-ghost doc-delete"
                  title="Delete document"
                  style={{ padding: '4px 8px', fontSize: '14px', opacity: 0.6 }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = '1'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = '0.6'; }}
                  onClick={() => deleteMutation.mutate({ docId: doc.id, filename: doc.filename })}
                  disabled={deleteMutation.isPending}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
