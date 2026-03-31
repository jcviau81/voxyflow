import { useState } from 'react';
import { ListChecks, X } from 'lucide-react';
import type { ChecklistItem } from '../../../types';
import {
  useChecklist,
  useAddChecklistItem,
  useUpdateChecklistItem,
  useDeleteChecklistItem,
} from '../../../hooks/api/useCards';

export function ChecklistSection({ cardId }: { cardId: string }) {
  const { data: items = [], isLoading } = useChecklist(cardId);
  const addItem = useAddChecklistItem();
  const updateItem = useUpdateChecklistItem();
  const deleteItem = useDeleteChecklistItem();
  const [newText, setNewText] = useState('');

  const total = items.length;
  const done = items.filter((i) => i.completed).length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  const handleAdd = () => {
    const text = newText.trim();
    if (!text) return;
    addItem.mutate({ cardId, text }, { onSuccess: () => setNewText('') });
  };

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <ListChecks size={12} /> Checklist {total > 0 && `(${done}/${total})`}
      </label>

      {total > 0 && (
        <div className="flex items-center gap-2">
          <div className="h-1 flex-1 rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-[10px] text-muted-foreground/60">{pct}%</span>
        </div>
      )}

      {isLoading ? (
        <p className="text-[10px] text-muted-foreground/40">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[10px] text-muted-foreground/40">No items yet.</p>
      ) : (
        <div className="space-y-1">
          {items.map((item) => (
            <ChecklistItemRow
              key={item.id}
              item={item}
              onToggle={(completed) =>
                updateItem.mutate({ cardId, itemId: item.id, updates: { completed } })
              }
              onTextEdit={(text) => {
                if (text && text !== item.text) {
                  updateItem.mutate({ cardId, itemId: item.id, updates: { text } });
                }
              }}
              onDelete={() => deleteItem.mutate({ cardId, itemId: item.id })}
            />
          ))}
        </div>
      )}

      <input
        type="text"
        value={newText}
        onChange={(e) => setNewText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            handleAdd();
          }
        }}
        placeholder="Add item… (Enter to add)"
        className="w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none placeholder:text-muted-foreground/40 focus:border-accent"
      />
    </div>
  );
}

function ChecklistItemRow({
  item,
  onToggle,
  onTextEdit,
  onDelete,
}: {
  item: ChecklistItem;
  onToggle: (completed: boolean) => void;
  onTextEdit: (text: string) => void;
  onDelete: () => void;
}) {
  const [editText, setEditText] = useState(item.text);
  const [editing, setEditing] = useState(false);

  return (
    <div className="flex items-center gap-1.5 text-[11px]">
      <input
        type="checkbox"
        checked={item.completed}
        onChange={(e) => onToggle(e.target.checked)}
        className="h-3 w-3 accent-emerald-500"
      />
      {editing ? (
        <input
          autoFocus
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={() => {
            onTextEdit(editText.trim());
            setEditing(false);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            if (e.key === 'Escape') {
              setEditText(item.text);
              setEditing(false);
            }
          }}
          className="flex-1 rounded border border-border bg-transparent px-1 py-0.5 text-[11px] outline-none focus:border-accent"
        />
      ) : (
        <span
          onDoubleClick={() => setEditing(true)}
          className={`flex-1 cursor-default select-none ${
            item.completed ? 'text-muted-foreground/40 line-through' : 'text-foreground'
          }`}
          title="Double-click to edit"
        >
          {item.text}
        </span>
      )}
      <button
        type="button"
        onClick={onDelete}
        className="text-muted-foreground/40 hover:text-muted-foreground"
        title="Remove item"
      >
        <X size={10} />
      </button>
    </div>
  );
}
