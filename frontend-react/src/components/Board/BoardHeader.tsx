/**
 * BoardHeader — shared toolbar for KanbanBoard and FreeBoard.
 *
 * Includes: search, priority/agent/tag filter chips, filter match count,
 * + Card button, dep graph, export, import.
 * Does NOT include the Execute Kanban button (KanbanBoard-only).
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  X, Link2, Upload, Download, Filter,
  AlertCircle, AlertTriangle, Minus, ArrowDown,
  Bot, Search, Code2, Paintbrush, Building2, PenLine, FlaskConical,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Input } from '../ui/input';
import { Button } from '../ui/button';
import { useIsDesktop } from '../../hooks/useIsDesktop';

// ── Shared constants ───────────────────────────────────────────────────────────

export const PRIORITY_FILTERS: Array<{ label: string; value: number | null; icon?: LucideIcon; color?: string }> = [
  { label: 'All',      value: null },
  { label: 'Critical', value: 3, icon: AlertCircle,   color: 'text-red-400' },
  { label: 'High',     value: 2, icon: AlertTriangle, color: 'text-orange-400' },
  { label: 'Medium',   value: 1, icon: Minus,         color: 'text-yellow-400' },
  { label: 'Low',      value: 0, icon: ArrowDown,     color: 'text-green-400' },
];

export const AGENT_ICONS: Record<string, LucideIcon> = {
  general:    Bot,
  researcher: Search,
  coder:      Code2,
  designer:   Paintbrush,
  architect:  Building2,
  writer:     PenLine,
  qa:         FlaskConical,
};

export const AGENT_COLORS: Record<string, string> = {
  general:    'text-slate-400',
  researcher: 'text-blue-400',
  coder:      'text-emerald-400',
  designer:   'text-pink-400',
  architect:  'text-orange-400',
  writer:     'text-violet-400',
  qa:         'text-amber-400',
};

export const AGENT_FILTERS: Array<{ label: string; value: string | null }> = [
  { label: 'All', value: null },
  ...Object.keys(AGENT_ICONS).filter((k) => k !== 'general').map((key) => ({
    label: key.charAt(0).toUpperCase() + key.slice(1),
    value: key,
  })),
];

// ── Debounce hook ──────────────────────────────────────────────────────────────

export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

// ── BoardHeader component ──────────────────────────────────────────────────────

export interface BoardHeaderProps {
  searchInput: string;
  onSearchChange: (value: string) => void;
  priorityFilter: number | null;
  onPriorityChange: (value: number | null) => void;
  agentFilter: string | null;
  onAgentChange: (value: string | null) => void;
  tagFilter: string | null;
  onTagChange: (value: string | null) => void;
  allTags: string[];
  filterMatchInfo?: { visible: number; total: number } | null;
  onNewCard: () => void;
  onDepGraph: () => void;
  onExport: () => void;
  onImport: (file: File) => void;
  /** Optional extra action buttons rendered before the standard actions (e.g. Execute Kanban). */
  extraActions?: React.ReactNode;
}

// ── Filter chips (shared between desktop inline and mobile dropdown) ──────────

function FilterChips({
  priorityFilter,
  onPriorityChange,
  agentFilter,
  onAgentChange,
  tagFilter,
  onTagChange,
  allTags,
}: Pick<BoardHeaderProps, 'priorityFilter' | 'onPriorityChange' | 'agentFilter' | 'onAgentChange' | 'tagFilter' | 'onTagChange' | 'allTags'>) {
  return (
    <>
      {/* Priority filter chips */}
      {PRIORITY_FILTERS.slice(1).map((pf) => {
        const PIcon = pf.icon;
        return (
          <button
            key={String(pf.value)}
            className={cn(
              'shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border transition-colors whitespace-nowrap',
              priorityFilter === pf.value
                ? 'bg-primary text-primary-foreground border-primary'
                : 'text-muted-foreground border-transparent hover:border-border',
            )}
            onClick={() => onPriorityChange(priorityFilter === pf.value ? null : pf.value)}
          >
            {PIcon && <PIcon size={10} className={priorityFilter === pf.value ? undefined : pf.color} />}
            {pf.label}
          </button>
        );
      })}

      <div className="w-px h-5 bg-border shrink-0" />

      {/* Agent filter chips */}
      {AGENT_FILTERS.slice(1).map((af) => {
        const AIcon = af.value ? AGENT_ICONS[af.value] : undefined;
        const aColor = af.value ? AGENT_COLORS[af.value] : undefined;
        return (
          <button
            key={String(af.value)}
            className={cn(
              'shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border transition-colors whitespace-nowrap',
              agentFilter === af.value
                ? 'bg-primary text-primary-foreground border-primary'
                : 'text-muted-foreground border-transparent hover:border-border',
            )}
            onClick={() => onAgentChange(agentFilter === af.value ? null : af.value)}
          >
            {AIcon && <AIcon size={10} className={agentFilter === af.value ? undefined : aColor} />}
            {af.label}
          </button>
        );
      })}

      {allTags.length > 0 && (
        <>
          <div className="w-px h-5 bg-border shrink-0" />
          {allTags.slice(0, 5).map((tag) => (
            <button
              key={tag}
              className={cn(
                'shrink-0 px-1.5 py-0.5 rounded text-[10px] border transition-colors whitespace-nowrap',
                tagFilter === tag
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'text-muted-foreground border-transparent hover:border-border',
              )}
              onClick={() => onTagChange(tagFilter === tag ? null : tag)}
            >
              {tag}
            </button>
          ))}
        </>
      )}
    </>
  );
}

// ── BoardHeader component ──────────────────────────────────────────────────────

export function BoardHeader({
  searchInput,
  onSearchChange,
  priorityFilter,
  onPriorityChange,
  agentFilter,
  onAgentChange,
  tagFilter,
  onTagChange,
  allTags,
  filterMatchInfo,
  onNewCard,
  onDepGraph,
  onExport,
  onImport,
  extraActions,
}: BoardHeaderProps) {
  const importInputRef = useRef<HTMLInputElement>(null);
  const isDesktop = useIsDesktop();
  const [filtersOpen, setFiltersOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on click outside
  useEffect(() => {
    if (!filtersOpen) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setFiltersOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [filtersOpen]);

  const activeFilterCount =
    (priorityFilter !== null ? 1 : 0) +
    (agentFilter !== null ? 1 : 0) +
    (tagFilter !== null ? 1 : 0) +
    (searchInput ? 1 : 0);

  return (
    <div className={cn('flex items-center gap-1.5 px-3 py-1.5 border-b border-border bg-background shrink-0', isDesktop && 'overflow-x-auto')}>

      {/* ── Desktop: inline filters ── */}
      {isDesktop && (
        <>
          {/* Search */}
          <div className="relative shrink-0 w-40">
            <Input
              type="text"
              placeholder="Search..."
              value={searchInput}
              onChange={(e) => onSearchChange(e.target.value)}
              className="h-7 text-xs pr-6"
            />
            {searchInput && (
              <button
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => onSearchChange('')}
              >
                <X size={11} />
              </button>
            )}
          </div>

          <div className="w-px h-5 bg-border shrink-0" />

          <FilterChips
            priorityFilter={priorityFilter}
            onPriorityChange={onPriorityChange}
            agentFilter={agentFilter}
            onAgentChange={onAgentChange}
            tagFilter={tagFilter}
            onTagChange={onTagChange}
            allTags={allTags}
          />

          {filterMatchInfo && (
            <span className="shrink-0 text-[10px] text-muted-foreground ml-1">
              {filterMatchInfo.visible}/{filterMatchInfo.total}
            </span>
          )}
        </>
      )}

      {/* ── Mobile: filter dropdown toggle ── */}
      {!isDesktop && (
        <div className="relative" ref={dropdownRef}>
          <Button
            variant="outline"
            size="sm"
            className={cn('h-7 px-2 shrink-0 flex items-center gap-1', activeFilterCount > 0 && 'border-primary')}
            onClick={() => setFiltersOpen((o) => !o)}
          >
            <Filter size={12} />
            <span className="text-xs">Filters</span>
            {activeFilterCount > 0 && (
              <span className="ml-0.5 w-4 h-4 flex items-center justify-center rounded-full bg-primary text-primary-foreground text-[9px] font-bold">
                {activeFilterCount}
              </span>
            )}
          </Button>

          {filtersOpen && (
            <div className="absolute top-full left-0 mt-1 z-50 w-72 rounded-lg border border-border bg-popover shadow-xl p-3 space-y-3">
              {/* Search */}
              <div className="relative">
                <Input
                  type="text"
                  placeholder="Search..."
                  value={searchInput}
                  onChange={(e) => onSearchChange(e.target.value)}
                  className="h-8 text-xs pr-6"
                  autoFocus
                />
                {searchInput && (
                  <button
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => onSearchChange('')}
                  >
                    <X size={11} />
                  </button>
                )}
              </div>

              {/* Priority */}
              <div>
                <div className="text-[10px] font-medium text-muted-foreground mb-1">Priority</div>
                <div className="flex flex-wrap gap-1">
                  <FilterChips
                    priorityFilter={priorityFilter}
                    onPriorityChange={onPriorityChange}
                    agentFilter={null}
                    onAgentChange={() => {}}
                    tagFilter={null}
                    onTagChange={() => {}}
                    allTags={[]}
                  />
                </div>
              </div>

              {/* Agent */}
              <div>
                <div className="text-[10px] font-medium text-muted-foreground mb-1">Agent</div>
                <div className="flex flex-wrap gap-1">
                  {AGENT_FILTERS.slice(1).map((af) => {
                    const AIcon = af.value ? AGENT_ICONS[af.value] : undefined;
                    const aColor = af.value ? AGENT_COLORS[af.value] : undefined;
                    return (
                      <button
                        key={String(af.value)}
                        className={cn(
                          'shrink-0 flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border transition-colors whitespace-nowrap',
                          agentFilter === af.value
                            ? 'bg-primary text-primary-foreground border-primary'
                            : 'text-muted-foreground border-transparent hover:border-border',
                        )}
                        onClick={() => onAgentChange(agentFilter === af.value ? null : af.value)}
                      >
                        {AIcon && <AIcon size={10} className={agentFilter === af.value ? undefined : aColor} />}
                        {af.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Tags */}
              {allTags.length > 0 && (
                <div>
                  <div className="text-[10px] font-medium text-muted-foreground mb-1">Tags</div>
                  <div className="flex flex-wrap gap-1">
                    {allTags.slice(0, 8).map((tag) => (
                      <button
                        key={tag}
                        className={cn(
                          'shrink-0 px-1.5 py-0.5 rounded text-[10px] border transition-colors whitespace-nowrap',
                          tagFilter === tag
                            ? 'bg-primary text-primary-foreground border-primary'
                            : 'text-muted-foreground border-transparent hover:border-border',
                        )}
                        onClick={() => onTagChange(tagFilter === tag ? null : tag)}
                      >
                        {tag}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {filterMatchInfo && (
                <div className="text-[10px] text-muted-foreground">
                  Showing {filterMatchInfo.visible}/{filterMatchInfo.total} cards
                </div>
              )}

              {/* Clear all */}
              {activeFilterCount > 0 && (
                <button
                  className="text-[10px] text-destructive hover:underline"
                  onClick={() => {
                    onSearchChange('');
                    onPriorityChange(null);
                    onAgentChange(null);
                    onTagChange(null);
                  }}
                >
                  Clear all filters
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Extra actions slot (e.g. Execute Kanban button) */}
      {extraActions}

      {/* Actions */}
      <Button
        variant="default"
        size="sm"
        className="h-6 text-[10px] px-2 shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground border-0"
        title="Create a new card"
        onClick={onNewCard}
      >
        + Card
      </Button>
      <Button variant="outline" size="sm" className="h-6 px-2 shrink-0" title="View dependency graph" onClick={onDepGraph}>
        <Link2 size={12} className="text-sky-400" />
      </Button>
      <Button variant="outline" size="sm" className="h-6 px-2 shrink-0" title="Export project as JSON" onClick={onExport}>
        <Upload size={12} className="text-violet-400" />
      </Button>
      <Button variant="outline" size="sm" className="h-6 px-2 shrink-0" title="Import project from JSON" onClick={() => importInputRef.current?.click()}>
        <Download size={12} className="text-blue-400" />
      </Button>
      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onImport(file);
          e.target.value = '';
        }}
      />
    </div>
  );
}
