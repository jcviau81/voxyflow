import { useRef, useState } from 'react';
import { Download, X } from 'lucide-react';
import type { CardAttachment } from '../../../types';
import {
  useAttachments,
  useUploadAttachment,
  useDeleteAttachment,
  getAttachmentDownloadUrl,
} from '../../../hooks/api/useCards';

function getAttachmentIcon(mimeType: string): string {
  if (mimeType.startsWith('image/')) return '🖼️';
  if (mimeType.includes('pdf')) return '📄';
  if (mimeType.includes('spreadsheet') || mimeType.includes('excel') || mimeType.includes('csv'))
    return '📊';
  if (mimeType.includes('word') || mimeType.includes('document')) return '📝';
  if (mimeType.includes('zip') || mimeType.includes('archive') || mimeType.includes('tar'))
    return '🗜️';
  if (mimeType.startsWith('video/')) return '🎬';
  if (mimeType.startsWith('audio/')) return '🎵';
  return '📄';
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AttachmentsSection({ cardId }: { cardId: string }) {
  const { data: attachments = [], isLoading } = useAttachments(cardId);
  const upload = useUploadAttachment();
  const deleteAttachment = useDeleteAttachment();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleFiles = (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      upload.mutate({ cardId, file });
    }
  };

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-muted-foreground">
        📎 Attachments {attachments.length > 0 && `(${attachments.length})`}
      </label>

      {/* Drop zone */}
      <div
        className={`cursor-pointer rounded border-2 border-dashed px-3 py-2 text-center text-[11px] transition-colors ${
          isDragging
            ? 'border-accent bg-accent/10 text-accent'
            : 'border-border text-muted-foreground/50 hover:border-muted-foreground/30'
        }`}
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
        }}
      >
        📎 Drop files here or <strong>click to upload</strong>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) {
              handleFiles(e.target.files);
              e.target.value = '';
            }
          }}
        />
      </div>

      {upload.isPending && (
        <p className="text-[10px] text-muted-foreground/60">⬆️ Uploading…</p>
      )}

      {isLoading ? (
        <p className="text-[10px] text-muted-foreground/40">Loading…</p>
      ) : attachments.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No attachments yet.</p>
      ) : (
        <div className="space-y-1.5">
          {attachments.map((att) => (
            <AttachmentItem
              key={att.id}
              cardId={cardId}
              attachment={att}
              onDelete={() =>
                deleteAttachment.mutate({ cardId, attachmentId: att.id })
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}

function AttachmentItem({
  cardId,
  attachment,
  onDelete,
}: {
  cardId: string;
  attachment: CardAttachment;
  onDelete: () => void;
}) {
  const downloadUrl = getAttachmentDownloadUrl(cardId, attachment.id);
  const isImage = attachment.mimeType.startsWith('image/');

  return (
    <div className="space-y-1">
      {isImage && (
        <img
          src={downloadUrl}
          alt={attachment.filename}
          className="max-h-20 w-full rounded object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = 'none';
          }}
        />
      )}
      <div className="flex items-center gap-1.5 text-[11px]">
        <span>{getAttachmentIcon(attachment.mimeType)}</span>
        <span className="flex-1 truncate font-medium" title={attachment.filename}>
          {attachment.filename}
        </span>
        <span className="text-muted-foreground/50">{formatFileSize(attachment.fileSize)}</span>
        <a
          href={downloadUrl}
          download={attachment.filename}
          className="text-muted-foreground/50 hover:text-muted-foreground"
          title={`Download ${attachment.filename}`}
          onClick={(e) => e.stopPropagation()}
        >
          <Download size={12} />
        </a>
        <button
          type="button"
          onClick={() => {
            if (window.confirm(`Delete "${attachment.filename}"?`)) onDelete();
          }}
          className="text-muted-foreground/40 hover:text-red-400"
          title={`Delete ${attachment.filename}`}
        >
          <X size={10} />
        </button>
      </div>
    </div>
  );
}
