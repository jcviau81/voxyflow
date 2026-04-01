import { useState } from 'react';
import { Link, X } from 'lucide-react';
import { useCardStore } from '../../../stores/useCardStore';

interface KnowledgeDoc {
  id: string;
  filename: string;
}

export function LinkedFiles({
  cardId,
  projectId,
  files,
}: {
  cardId: string;
  projectId?: string;
  files: string[];
}) {
  const updateCard = useCardStore((s) => s.updateCard);
  const [showPicker, setShowPicker] = useState(false);
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [loading, setLoading] = useState(false);

  const loadDocs = async () => {
    if (showPicker) {
      setShowPicker(false);
      return;
    }
    if (!projectId) return;
    setLoading(true);
    try {
      const resp = await fetch(`/api/projects/${projectId}/documents`);
      if (resp.ok) {
        const data = await resp.json() as { documents: KnowledgeDoc[] };
        setDocs(data.documents ?? []);
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to load knowledge docs:', e);
    } finally {
      setLoading(false);
      setShowPicker(true);
    }
  };

  const linkFile = async (docId: string) => {
    try {
      const resp = await fetch(`/api/cards/${cardId}/files`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: docId }),
      });
      if (resp.ok) {
        updateCard(cardId, { files: (await resp.json()) as string[] });
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to link file:', e);
    }
    setShowPicker(false);
  };

  const unlinkFile = async (docId: string) => {
    try {
      const resp = await fetch(
        `/api/cards/${cardId}/files?path=${encodeURIComponent(docId)}`,
        { method: 'DELETE' },
      );
      if (resp.ok) {
        updateCard(cardId, { files: (await resp.json()) as string[] });
      }
    } catch (e) {
      console.error('[LinkedFiles] Failed to unlink file:', e);
    }
  };

  const availableDocs = docs.filter((d) => !files.includes(d.id));

  // Resolve display name: match doc id to filename, fall back to raw value
  const displayName = (ref: string) =>
    docs.find((d) => d.id === ref)?.filename ?? ref.split('/').pop() ?? ref;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
          <Link size={12} /> Knowledge files
        </label>
        {projectId && (
          <button
            type="button"
            onClick={loadDocs}
            className="text-xs text-muted-foreground/60 hover:text-muted-foreground"
          >
            {loading ? '…' : showPicker ? <><X size={10} /> Close</> : '+ Link'}
          </button>
        )}
      </div>

      {files.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No linked knowledge files.</p>
      ) : (
        <div className="space-y-1">
          {files.map((ref) => (
            <div key={ref} className="flex items-center gap-1.5 text-[11px]">
              <span className="flex-1 truncate text-foreground" title={ref}>
                {displayName(ref)}
              </span>
              <button
                type="button"
                onClick={() => unlinkFile(ref)}
                className="text-muted-foreground/40 hover:text-muted-foreground"
                title="Unlink file"
              >
                <X size={10} />
              </button>
            </div>
          ))}
        </div>
      )}

      {showPicker && (
        <div className="max-h-40 overflow-y-auto rounded border border-border bg-card text-[11px]">
          {availableDocs.length === 0 ? (
            <div className="px-3 py-2 text-muted-foreground/60">
              {docs.length === 0 ? 'No documents in Knowledge' : 'All documents already linked'}
            </div>
          ) : (
            availableDocs.map((doc) => (
              <button
                key={doc.id}
                type="button"
                onClick={() => linkFile(doc.id)}
                className="block w-full px-3 py-1.5 text-left text-foreground hover:bg-muted"
                title={doc.filename}
              >
                {doc.filename}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
