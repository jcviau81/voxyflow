import { useState, useCallback } from 'react';
import type React from 'react';
import { X } from 'lucide-react';

const TAG_COLORS: Array<[string, string]> = [
  ['rgba(255, 107, 107, 0.18)', '#ff6b6b'],
  ['rgba(78, 205, 196, 0.18)', '#4ecdc4'],
  ['rgba(255, 183, 77, 0.18)', '#ffb74d'],
  ['rgba(66, 165, 245, 0.18)', '#42a5f5'],
  ['rgba(171, 145, 249, 0.18)', '#ab91f9'],
  ['rgba(102, 187, 106, 0.18)', '#66bb6a'],
  ['rgba(255, 138, 101, 0.18)', '#ff8a65'],
  ['rgba(236, 64, 122, 0.18)', '#ec407a'],
];

function stringHash(s: string): number {
  let hash = 0;
  for (let i = 0; i < s.length; i++) {
    hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  }
  return hash;
}

function getTagColor(tag: string): [string, string] {
  return TAG_COLORS[stringHash(tag) % TAG_COLORS.length];
}

interface TagsSectionProps {
  tags: string[];
  onAdd: (tag: string) => void;
  onRemove: (tag: string) => void;
}

export function TagsSection({ tags, onAdd, onRemove }: TagsSectionProps) {
  const [input, setInput] = useState('');

  const commitTags = useCallback(
    (raw: string) => {
      const newTags = raw
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean);
      newTags.forEach((tag) => {
        if (!tags.includes(tag)) onAdd(tag);
      });
      setInput('');
    },
    [tags, onAdd],
  );

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      commitTags(input);
    } else if (e.key === 'Escape') {
      setInput('');
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    if (val.includes(',')) {
      commitTags(val);
    } else {
      setInput(val);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tags.map((tag) => {
        const [bg, color] = getTagColor(tag);
        return (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            style={{ background: bg, color }}
            title={tag}
          >
            {tag}
            <button
              type="button"
              onClick={() => onRemove(tag)}
              className="hover:opacity-70"
              title={`Remove "${tag}"`}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        );
      })}
      <input
        type="text"
        value={input}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder="Add tag..."
        className="min-w-[80px] flex-1 border-none bg-transparent text-xs outline-none placeholder:text-muted-foreground/50"
      />
    </div>
  );
}
