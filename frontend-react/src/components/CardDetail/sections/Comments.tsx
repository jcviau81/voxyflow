import { useState } from 'react';
import { useComments, useAddComment, useDeleteComment } from '../../../hooks/api/useCards';

export function CommentsSection({ cardId }: { cardId: string }) {
  const { data: comments = [], isLoading } = useComments(cardId);
  const addComment = useAddComment();
  const deleteComment = useDeleteComment();
  const [content, setContent] = useState('');

  const handleSubmit = () => {
    const text = content.trim();
    if (!text) return;
    addComment.mutate({ cardId, content: text }, { onSuccess: () => setContent('') });
  };

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-muted-foreground">
        💬 Comments {comments.length > 0 && `(${comments.length})`}
      </label>

      {isLoading ? (
        <p className="text-[10px] text-muted-foreground/40">Loading…</p>
      ) : comments.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No comments yet.</p>
      ) : (
        <div className="space-y-2">
          {[...comments].reverse().map((comment) => {
            const initials = comment.author
              .split(' ')
              .map((w) => w[0] ?? '')
              .join('')
              .toUpperCase()
              .slice(0, 2);
            return (
              <div key={comment.id} className="flex gap-2 text-[11px]">
                <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-accent text-[9px] font-bold text-accent-foreground">
                  {initials}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-muted-foreground/60">
                    {comment.author} ·{' '}
                    {new Date(comment.createdAt).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </div>
                  <div className="text-foreground">{comment.content}</div>
                </div>
                <button
                  type="button"
                  onClick={() => deleteComment.mutate({ cardId, commentId: comment.id })}
                  disabled={deleteComment.isPending}
                  className="flex-shrink-0 text-muted-foreground/40 hover:text-muted-foreground"
                  title="Delete comment"
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex gap-1.5">
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          placeholder="Add a comment… (Ctrl+Enter to post)"
          rows={2}
          className="flex-1 resize-none rounded border border-border bg-transparent px-2 py-1 text-xs outline-none placeholder:text-muted-foreground/40 focus:border-accent"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={addComment.isPending || !content.trim()}
          className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-40"
        >
          Post
        </button>
      </div>
    </div>
  );
}
