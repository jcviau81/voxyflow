import { useRef, useState, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import {
  Upload, Save, Eye, Pencil, Trash2, Plus, Loader2,
  File, FileText, FileCode, BookOpen, Sheet,
  Files, BookMarked, Database, Settings,
  type LucideIcon,
} from 'lucide-react';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import { cn } from '../../lib/utils';

// ─── Types ────────────────────────────────────────────────────────────────────

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

interface WikiPageDetail extends WikiPageSummary {
  project_id: string;
  content: string;
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

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

function getDocIconComponent(filename: string, mimeType: string): LucideIcon {
  const ext = filename.split('.').pop()?.toLowerCase() ?? '';
  if (ext === 'pdf' || mimeType === 'application/pdf') return BookOpen;
  if (ext === 'xlsx' || ext === 'xls' || mimeType.includes('spreadsheet') || mimeType.includes('excel')) return Sheet;
  if (ext === 'docx' || ext === 'doc' || mimeType.includes('word') || mimeType.includes('msword')) return FileText;
  if (ext === 'md') return FileCode;
  return File;
}

function DocIcon({ filename, mimeType, size = 14 }: { filename: string; mimeType: string; size?: number }) {
  const Icon = getDocIconComponent(filename, mimeType);
  return <Icon size={size} className="shrink-0 text-muted-foreground" />;
}

const ALLOWED_EXTS = ['.txt', '.md', '.pdf', '.docx', '.xlsx'];

type KnowledgeTab = 'documents' | 'wiki' | 'rag';

// ─── Documents tab ────────────────────────────────────────────────────────────

interface DocumentsTabProps {
  projectId: string;
}

function DocumentsTab({ projectId }: DocumentsTabProps) {
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
    staleTime: 30_000,
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
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
    onError: (err: Error) => showToast(`Upload failed: ${err.message}`, 'error'),
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
    onError: () => showToast('Delete failed', 'error'),
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

  return (
    <div className="knowledge-view">
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.md,.pdf,.docx,.xlsx"
        style={{ display: 'none' }}
        onChange={handleFileInputChange}
      />

      <div className="knowledge-upload-row">
        <button
          className="btn flex flex-col btn-primary place-items-center text-center"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploadMutation.isPending}
        >
          {uploadMutation.isPending
            ? <><Loader2 size={13} className="animate-spin" /> Uploading…</>
            : <><Upload size={13} /> Upload</>}
        </button>
      </div>

      <div
        className={`knowledge-drop-zone${isDragOver ? ' dragover' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <span>Drag &amp; drop files here, or click <strong>Upload</strong></span>
      </div>

      <div className="knowledge-list place-items-center">
        {docs.length === 0 ? (
          <div className="knowledge-empty place-items-center">No documents uploaded yet.</div>
        ) : (
          docs.map((doc) => (
            <div key={doc.id} className="knowledge-item">
              <span className="knowledge-item-icon">
                <DocIcon filename={doc.filename} mimeType={doc.mime_type} />
              </span>
              <span className="knowledge-item-name">{doc.filename}</span>
              <span className="knowledge-item-meta">{formatBytes(doc.file_size)} · {formatDate(doc.created_at)}</span>
              <button
                className="btn btn-ghost knowledge-item-delete"
                title="Delete"
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

// ─── Wiki tab ─────────────────────────────────────────────────────────────────

interface WikiTabProps {
  projectId: string;
}

function WikiTab({ projectId }: WikiTabProps) {
  const { showToast } = useToastStore();
  const qc = useQueryClient();

  const [activePageId, setActivePageId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [dirty, setDirty] = useState(false);
  const [previewMode, setPreviewMode] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  const { data: pages = [] } = useQuery<WikiPageSummary[]>({
    queryKey: ['projects', projectId, 'wiki'],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/wiki`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageSummary[]>;
    },
    staleTime: 60_000,
    retry: false,
  });

  const { data: activePage } = useQuery<WikiPageDetail>({
    queryKey: ['projects', projectId, 'wiki', activePageId],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/wiki/${activePageId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageDetail>;
    },
    enabled: !!activePageId,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (pages.length > 0 && !activePageId) {
      setActivePageId(pages[0].id);
    }
  }, [pages, activePageId]);

  useEffect(() => {
    if (activePage) {
      setEditTitle(activePage.title);
      setEditContent(activePage.content);
      setDirty(false);
      setPreviewMode(false);
    }
  }, [activePage]);

  const createMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/wiki`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Page', content: '' }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageDetail>;
    },
    onSuccess: (page) => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'wiki'] });
      setActivePageId(page.id);
      setTimeout(() => titleInputRef.current?.focus(), 50);
    },
    onError: () => showToast('Failed to create page', 'error'),
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!activePageId) throw new Error('No active page');
      const res = await fetch(`/api/projects/${projectId}/wiki/${activePageId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: editTitle.trim() || 'Untitled', content: editContent }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageDetail>;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'wiki'] });
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'wiki', activePageId] });
      setDirty(false);
      showToast('Wiki page saved', 'success', 2000);
    },
    onError: () => showToast('Failed to save page', 'error'),
  });

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!activePageId) throw new Error('No active page');
      const res = await fetch(`/api/projects/${projectId}/wiki/${activePageId}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['projects', projectId, 'wiki'] });
      const remaining = pages.filter(p => p.id !== activePageId);
      setActivePageId(remaining.length > 0 ? remaining[0].id : null);
      showToast('Page deleted', 'success', 2000);
    },
    onError: () => showToast('Failed to delete page', 'error'),
  });

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (dirty) saveMutation.mutate();
    }
  }, [dirty, saveMutation]);

  const handleDeleteClick = useCallback(() => {
    if (!activePage) return;
    if (window.confirm(`Delete page "${activePage.title}"? This cannot be undone.`)) {
      deleteMutation.mutate();
    }
  }, [activePage, deleteMutation]);

  return (
    <div className="flex flex-col md:flex-row h-full overflow-hidden">
      {/* Sidebar — horizontal tabs on mobile, vertical panel on desktop */}
      <div className="w-full md:w-[220px] md:min-w-[180px] shrink-0 border-b md:border-b-0 md:border-r border-border bg-muted/20 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-3 py-2 md:px-3.5 md:py-3 border-b border-border gap-2">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Pages</span>
          <button
            className="flex items-center justify-center w-6 h-6 rounded-full bg-primary text-primary-foreground shrink-0 cursor-pointer transition-opacity hover:opacity-85 disabled:opacity-40 disabled:cursor-not-allowed"
            title="New page"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
          >
            <Plus size={13} />
          </button>
        </div>

        <div className="flex md:flex-col overflow-x-auto md:overflow-x-hidden md:overflow-y-auto md:flex-1 px-1 md:px-0 py-1 md:py-1.5 gap-1 md:gap-0">
          {pages.length === 0 ? (
            <div className="px-3.5 py-4 text-xs text-muted-foreground italic leading-relaxed whitespace-nowrap md:whitespace-normal">
              No pages yet. Hit + to start.
            </div>
          ) : (
            pages.map((page) => (
              <div
                key={page.id}
                className={cn(
                  'flex shrink-0 md:shrink cursor-pointer transition-colors',
                  // Mobile: horizontal pill style
                  'flex-row items-center gap-1.5 px-2.5 py-1 md:py-2 md:px-3.5 rounded md:rounded-none whitespace-nowrap md:whitespace-normal text-xs md:text-sm',
                  // Desktop: vertical list with left border
                  'md:flex-col md:items-start md:gap-0.5 md:border-l-[3px] border-transparent',
                  'hover:bg-accent/50',
                  activePageId === page.id
                    ? 'bg-accent md:border-l-primary text-primary font-medium'
                    : 'text-foreground',
                )}
                onClick={() => {
                  if (activePageId !== page.id) setActivePageId(page.id);
                }}
              >
                <span className="truncate font-medium">{page.title || 'Untitled'}</span>
                <span className="hidden md:inline text-[0.75rem] text-muted-foreground">{formatDate(page.updated_at)}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        {!activePageId ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm italic p-10 text-center">
            <p>Select a page from the sidebar or create a new one.</p>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 px-3 md:px-4 py-2.5 border-b border-border bg-muted/20 shrink-0">
              <input
                ref={titleInputRef}
                className="flex-1 bg-transparent border-none outline-none text-base font-semibold text-foreground py-1 min-w-0 placeholder:text-muted-foreground placeholder:font-normal"
                type="text"
                placeholder="Page title…"
                value={editTitle}
                onChange={(e) => { setEditTitle(e.target.value); setDirty(true); }}
              />
              <button
                className={cn(
                  'flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors cursor-pointer',
                  dirty && !saveMutation.isPending
                    ? 'border-green-500/50 text-green-500 hover:bg-green-500/10'
                    : 'text-muted-foreground disabled:opacity-40 disabled:cursor-not-allowed',
                )}
                title="Save (Ctrl+S)"
                onClick={() => saveMutation.mutate()}
                disabled={!dirty || saveMutation.isPending}
              >
                {saveMutation.isPending
                ? <><Loader2 size={13} className="animate-spin" /> Saving…</>
                : <><Save size={13} /> <span className="hidden sm:inline">Save</span></>}
              </button>
              <button
                className={cn(
                  'flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors cursor-pointer',
                  previewMode
                    ? 'border-accent text-accent-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
                title="Toggle preview"
                onClick={() => setPreviewMode(p => !p)}
              >
                {previewMode ? <><Pencil size={13} /> <span className="hidden sm:inline">Edit</span></>
                : <><Eye size={13} /> <span className="hidden sm:inline">Preview</span></>}
              </button>
              <button
                className="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs text-muted-foreground transition-colors cursor-pointer hover:border-destructive hover:text-destructive hover:bg-destructive/10 disabled:opacity-40 disabled:cursor-not-allowed"
                title="Delete page"
                onClick={handleDeleteClick}
                disabled={deleteMutation.isPending}
              >
                <Trash2 size={13} /> <span className="hidden sm:inline">Delete</span>
              </button>
            </div>

            <div className="flex-1 overflow-hidden flex flex-col">
              {previewMode ? (
                <div className="flex-1 overflow-y-auto p-5 md:p-6 prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown>{editContent}</ReactMarkdown>
                </div>
              ) : (
                <textarea
                  className="flex-1 w-full bg-background text-foreground border-none outline-none resize-none p-5 md:p-6 font-mono text-sm leading-relaxed placeholder:text-muted-foreground"
                  placeholder="Write your page in Markdown…"
                  value={editContent}
                  onChange={(e) => { setEditContent(e.target.value); setDirty(true); }}
                  onKeyDown={handleKeyDown}
                />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── RAG Sources tab ──────────────────────────────────────────────────────────

interface RagTabProps {
  projectId: string;
}

function RagTab({ projectId }: RagTabProps) {
  const project = useProjectStore(s => s.getActiveProject());

  const { data: docs = [] } = useQuery<ProjectDocument[]>({
    queryKey: ['projects', projectId, 'documents'],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/documents`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as ProjectDocument[] | { documents: ProjectDocument[] };
      return Array.isArray(data) ? data : (data.documents ?? []);
    },
    staleTime: 30_000,
  });

  const { data: wikiPages = [] } = useQuery<WikiPageSummary[]>({
    queryKey: ['projects', projectId, 'wiki'],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/wiki`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json() as Promise<WikiPageSummary[]>;
    },
    staleTime: 60_000,
    retry: false,
  });

  const techStack = project?.techStack as string[] | undefined;
  const ragItems: Array<{ Icon: LucideIcon; name: string; status: string }> = [];

  if (techStack && techStack.length > 0) {
    for (const tech of techStack) {
      ragItems.push({ Icon: Settings, name: tech, status: 'auto-detected' });
    }
  }
  if (docs.length > 0) {
    ragItems.push({
      Icon: Files,
      name: `${docs.length} document${docs.length === 1 ? '' : 's'} indexed`,
      status: 'indexed',
    });
  }
  if (wikiPages.length > 0) {
    ragItems.push({
      Icon: BookMarked,
      name: `${wikiPages.length} wiki page${wikiPages.length === 1 ? '' : 's'}`,
      status: 'indexed',
    });
  }

  return (
    <div className="knowledge-view">
      <div className="knowledge-list">
        {ragItems.length === 0 ? (
          <div className="knowledge-empty">
            No knowledge sources yet. Add documents or wiki pages.
          </div>
        ) : (
          ragItems.map((item, i) => (
            <div key={i} className="knowledge-item">
              <span className="knowledge-item-icon">
                <item.Icon size={14} className="text-muted-foreground" />
              </span>
              <span className="knowledge-item-name">{item.name}</span>
              <span className="knowledge-rag-status indexed">{item.status}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

const KNOWLEDGE_TABS: { id: KnowledgeTab; Icon: LucideIcon; label: string }[] = [
  { id: 'documents', Icon: Files,       label: 'Documents' },
  { id: 'wiki',      Icon: BookMarked,  label: 'Wiki' },
  { id: 'rag',       Icon: Database,    label: 'RAG Sources' },
];

interface ProjectKnowledgeProps {
  projectId?: string;
}

export function ProjectKnowledge({ projectId: projectIdProp }: ProjectKnowledgeProps = {}) {
  const storeProjectId = useProjectStore(s => s.currentProjectId);
  const projectId = projectIdProp ?? storeProjectId;
  const [activeTab, setActiveTab] = useState<KnowledgeTab>('documents');

  if (!projectId) {
    return (
      <div className="knowledge-view">
        <div className="knowledge-empty">No project selected.</div>
      </div>
    );
  }

  return (
    <div className="knowledge-container">
      {/* Sub-tab bar */}
      <div className="knowledge-tabs p-0">
        {KNOWLEDGE_TABS.map(tab => (
          <button
            key={tab.id}
            className={cn('flex gap-1.5 items-center knowledge-tab-btn', activeTab === tab.id && 'active')}
            onClick={() => setActiveTab(tab.id)}
          >
            <tab.Icon size={13} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'documents' && <DocumentsTab projectId={projectId} />}
      {activeTab === 'wiki'      && <WikiTab projectId={projectId} />}
      {activeTab === 'rag'       && <RagTab projectId={projectId} />}
    </div>
  );
}
