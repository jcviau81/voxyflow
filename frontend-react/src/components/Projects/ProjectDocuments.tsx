import { useRef, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Upload, Trash2, Loader2, File, FileText, FileCode, BookOpen, Sheet } from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import type { LucideIcon } from 'lucide-react';

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

function getDocIconComponent(filename: string, mimeType: string): LucideIcon {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf' || mimeType === 'application/pdf') return BookOpen;
  if (ext === 'xlsx' || ext === 'xls' || mimeType.includes('spreadsheet') || mimeType.includes('excel')) return Sheet;
  if (ext === 'docx' || ext === 'doc' || mimeType.includes('word') || mimeType.includes('msword')) return FileText;
  if (ext === 'md') return FileCode;
  return File;
}

function DocIcon({ filename, mimeType }: { filename: string; mimeType: string }) {
  const Icon = getDocIconComponent(filename, mimeType);
  return <Icon size={14} className="shrink-0 text-muted-foreground" />;
}

const ALLOWED_EXTS = ['.txt', '.md', '.pdf', '.docx', '.xlsx'];

export function ProjectDocuments() {
  const projectId = useProjectStore(s => s.currentProjectId);
  const { showToast } = useToastStore();
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const { data: docs = [] } = useQuery<ProjectDocument[]>({
    queryKey: ['projects', projectId, 'documents'],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/documents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as ProjectDocument[] | { documents: ProjectDocument[] };
      return Array.isArray(data) ? data : (data.documents ?? []);
    },
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!projectId) throw new Error('No project selected');
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/projects/${projectId}/documents`, { method: 'POST', body: formData });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || `HTTP ${res.status}`);
      }
      return res.json() as Promise<ProjectDocument>;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] });
      showToast('Document indexed', 'success', 3000);
    },
    onError: (err: Error) => {
      showToast(`Upload failed: ${err.message}`, 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async ({ docId }: { docId: string; filename: string }) => {
      const res = await fetch(`/api/projects/${projectId}/documents/${docId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: (_data, { filename }) => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] });
      showToast(`"${filename}" removed`, 'info', 2500);
    },
    onError: () => {
      showToast('Delete failed', 'error');
    },
  });

  const handleFile = useCallback((file: File) => {
    const ext = '.' + (file.name.split('.').pop()?.toLowerCase() ?? '');
    if (!ALLOWED_EXTS.includes(ext)) {
      showToast(`File type not supported: ${ext}`, 'error');
      return;
    }
    uploadMutation.mutate(file);
  }, [uploadMutation, showToast]);

  const handleFileInputChange = useCallback(() => {
    const file = fileInputRef.current?.files?.[0];
    if (file) {
      handleFile(file);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, [handleFile]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }, [handleFile]);

  if (!projectId) {
    return (
      <div className="docs-view">
        <div className="docs-empty" style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-muted, #888)', fontSize: '13px' }}>
          No project selected.
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
          disabled={uploadMutation.isPending}
        >
          {uploadMutation.isPending
            ? <><Loader2 size={13} className="animate-spin" /> Uploading…</>
            : <><Upload size={13} /> Upload</>}
        </button>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.md,.pdf,.docx,.xlsx"
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
          Drag &amp; drop files here, or click <strong>Upload</strong>
        </span>
      </div>

      {/* Document list */}
      <div className="docs-list" style={{ marginTop: '16px' }}>
        {docs.length === 0 ? (
          <div
            className="docs-empty"
            style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-text-muted, #888)', fontSize: '13px' }}
          >
            No documents yet. Upload files to give Voxy context about this project.
          </div>
        ) : (
          docs.map((doc) => (
            <div key={doc.id} className="doc-item">
              <span className="doc-icon"><DocIcon filename={doc.filename} mimeType={doc.mime_type} /></span>
              <span className="doc-name">{doc.filename}</span>
              <span className="doc-meta">{formatBytes(doc.file_size)} · {formatDate(doc.created_at)}</span>
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
          ))
        )}
      </div>
    </div>
  );
}
