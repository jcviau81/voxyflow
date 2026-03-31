import { useRef, useState, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';

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
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf' || mimeType === 'application/pdf') return '📕';
  if (ext === 'xlsx' || ext === 'xls' || mimeType.includes('spreadsheet') || mimeType.includes('excel')) return '📊';
  if (ext === 'docx' || ext === 'doc' || mimeType.includes('word') || mimeType.includes('msword')) return '📝';
  if (ext === 'md') return '📋';
  return '📄';
}

const ALLOWED_EXTS = ['.txt', '.md', '.pdf', '.docx', '.xlsx'];

interface KnowledgeSectionProps {
  title: string;
  children: React.ReactNode;
}

function KnowledgeSection({ title, children }: KnowledgeSectionProps) {
  return (
    <div className="knowledge-section">
      <h3 className="knowledge-section-title">{title}</h3>
      {children}
    </div>
  );
}

export function ProjectKnowledge() {
  const projectId = useProjectStore(s => s.currentProjectId);
  const project = useProjectStore(s => s.getActiveProject());
  const { showToast } = useToastStore();
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  // --- Documents ---
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

  // --- Wiki pages ---
  const { data: wikiPages = [] } = useQuery<WikiPageSummary[]>({
    queryKey: ['projects', projectId, 'wiki'],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/wiki`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageSummary[]>;
    },
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
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
      <div className="knowledge-view">
        <div className="knowledge-empty">No project selected.</div>
      </div>
    );
  }

  const techStack = project?.techStack as string[] | undefined;

  // RAG summary entries
  const ragItems: Array<{ icon: string; name: string; status: string }> = [];
  if (techStack && techStack.length > 0) {
    for (const tech of techStack) {
      ragItems.push({ icon: '⚙️', name: tech, status: 'auto-detected' });
    }
  }
  if (docs.length > 0) {
    ragItems.push({
      icon: '📄',
      name: `${docs.length} document${docs.length === 1 ? '' : 's'} indexed`,
      status: 'indexed',
    });
  }
  if (wikiPages.length > 0) {
    ragItems.push({
      icon: '📖',
      name: `${wikiPages.length} wiki page${wikiPages.length === 1 ? '' : 's'}`,
      status: 'indexed',
    });
  }

  return (
    <div className="knowledge-view">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.md,.pdf,.docx,.xlsx"
        style={{ display: 'none' }}
        onChange={handleFileInputChange}
      />

      {/* Section 1: Documents */}
      <KnowledgeSection title="📄 Documents">
        {/* Upload area */}
        <div className="knowledge-upload-row">
          <button
            className="btn btn-primary knowledge-upload-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending ? '⏳ Uploading…' : '⬆️ Upload'}
          </button>
        </div>

        {/* Drop zone */}
        <div
          className={`knowledge-drop-zone${isDragOver ? ' dragover' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <span>Drag &amp; drop files here, or click <strong>Upload</strong></span>
        </div>

        {/* Docs list */}
        <div className="knowledge-list">
          {docs.length === 0 ? (
            <div className="knowledge-empty">No documents uploaded yet.</div>
          ) : (
            docs.map((doc) => (
              <div key={doc.id} className="knowledge-item">
                <span className="knowledge-item-icon">{getDocIcon(doc.filename, doc.mime_type)}</span>
                <span className="knowledge-item-name">{doc.filename}</span>
                <span className="knowledge-item-meta">{formatBytes(doc.file_size)} · {formatDate(doc.created_at)}</span>
                <button
                  className="btn btn-ghost knowledge-item-delete"
                  title="Delete"
                  onClick={() => deleteMutation.mutate({ docId: doc.id, filename: doc.filename })}
                  disabled={deleteMutation.isPending}
                >
                  🗑️
                </button>
              </div>
            ))
          )}
        </div>
      </KnowledgeSection>

      {/* Section 2: Wiki Pages */}
      <KnowledgeSection title="📖 Wiki Pages">
        <div className="knowledge-list">
          {wikiPages.length === 0 ? (
            <div className="knowledge-empty">No wiki pages yet.</div>
          ) : (
            wikiPages.map((page) => (
              <div key={page.id} className="knowledge-item">
                <span className="knowledge-item-icon">📖</span>
                <span className="knowledge-item-name">{page.title || 'Untitled'}</span>
                <span className="knowledge-item-meta">{formatDate(page.updated_at)}</span>
              </div>
            ))
          )}
        </div>
      </KnowledgeSection>

      {/* Section 3: RAG Sources */}
      <KnowledgeSection title="🔗 RAG Sources">
        <div className="knowledge-list">
          {ragItems.length === 0 ? (
            <div className="knowledge-empty">
              No knowledge sources yet. Add documents above or link external docs.
            </div>
          ) : (
            ragItems.map((item, i) => (
              <div key={i} className="knowledge-item">
                <span className="knowledge-item-icon">{item.icon}</span>
                <span className="knowledge-item-name">{item.name}</span>
                <span className="knowledge-rag-status indexed">{item.status}</span>
              </div>
            ))
          )}
        </div>
      </KnowledgeSection>
    </div>
  );
}
