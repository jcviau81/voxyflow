/**
 * ProjectArchives — view for archived cards in a project.
 *
 * Displays all archived cards for the current project with options to
 * restore or permanently delete each card, plus a "Vider les archives"
 * bulk-delete button with confirmation dialog.
 */

import { useState } from 'react';
import { Archive, RotateCcw, Trash2, Loader2, Search, X, AlertTriangle } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { cn } from '../../lib/utils';
import { useArchivedCards, useRestoreCard, useDeleteCard, cardKeys } from '../../hooks/api/useCards';
import { useProjectStore } from '../../stores/useProjectStore';
import { useToastStore } from '../../stores/useToastStore';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../ui/dialog';
import type { Card } from '../../types';

const PRIORITY_LABELS: Record<number, { label: string; color: string }> = {
  0: { label: 'Low',      color: 'text-green-400' },
  1: { label: 'Medium',   color: 'text-yellow-400' },
  2: { label: 'High',     color: 'text-orange-400' },
  3: { label: 'Critical', color: 'text-red-400' },
};

function formatDate(ts: number): string {
  try {
    return new Date(ts).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return '';
  }
}

interface ArchivedCardRowProps {
  card: Card;
  projectId: string;
  onRestored: () => void;
  onDeleted: () => void;
}

function ArchivedCardRow({ card, projectId, onRestored, onDeleted }: ArchivedCardRowProps) {
  const { showToast } = useToastStore();
  const restoreCard = useRestoreCard();
  const deleteCard = useDeleteCard();
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleRestore = async () => {
    try {
      await restoreCard.mutateAsync({ cardId: card.id, projectId });
      showToast(`"${card.title}" restored`, 'success', 2500);
      onRestored();
    } catch {
      showToast('Failed to restore card', 'error');
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    try {
      await deleteCard.mutateAsync({ cardId: card.id, projectId });
      showToast(`"${card.title}" permanently deleted`, 'info', 2500);
      onDeleted();
    } catch {
      showToast('Failed to delete card', 'error');
    }
  };

  const priority = PRIORITY_LABELS[card.priority ?? 0] ?? PRIORITY_LABELS[0];
  const isLoading = restoreCard.isPending || deleteCard.isPending;

  return (
    <div className="flex items-start gap-3 px-4 py-3 border-b border-border last:border-b-0 hover:bg-accent/30 transition-colors group">
      {/* Archive icon */}
      <Archive size={15} className="shrink-0 mt-0.5 text-muted-foreground" />

      {/* Card info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-foreground truncate">{card.title}</span>
          {card.priority != null && (
            <span className={cn('text-[0.65rem] font-medium', priority.color)}>
              {priority.label}
            </span>
          )}
          {card.agentType && (
            <span className="text-[0.65rem] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
              {card.agentType}
            </span>
          )}
        </div>
        {card.description && (
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">
            {card.description}
          </p>
        )}
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {card.tags && card.tags.length > 0 && card.tags.slice(0, 3).map((tag) => (
            <span key={tag} className="text-[0.625rem] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
              {tag}
            </span>
          ))}
          <span className="text-[0.625rem] text-muted-foreground">
            Archived {formatDate(card.updatedAt)}
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1.5 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-accent transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          title="Restore card"
          onClick={handleRestore}
          disabled={isLoading}
        >
          {restoreCard.isPending
            ? <Loader2 size={12} className="animate-spin" />
            : <RotateCcw size={12} />}
          <span className="hidden sm:inline">Restore</span>
        </button>
        <button
          className={cn(
            'flex items-center gap-1.5 px-2 py-1 rounded text-xs transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed',
            confirmDelete
              ? 'bg-destructive/20 text-destructive border border-destructive/50 hover:bg-destructive/30'
              : 'text-muted-foreground hover:text-destructive hover:bg-destructive/10',
          )}
          title={confirmDelete ? 'Click again to confirm deletion' : 'Permanently delete'}
          onClick={handleDelete}
          disabled={isLoading}
        >
          {deleteCard.isPending
            ? <Loader2 size={12} className="animate-spin" />
            : <Trash2 size={12} />}
          <span className="hidden sm:inline">
            {confirmDelete ? 'Confirm?' : 'Delete'}
          </span>
        </button>
      </div>
    </div>
  );
}

interface ProjectArchivesProps {
  projectId?: string;
}

export function ProjectArchives({ projectId: projectIdProp }: ProjectArchivesProps = {}) {
  const storeProjectId = useProjectStore((s) => s.currentProjectId);
  const projectId = projectIdProp ?? storeProjectId ?? '';
  const { showToast } = useToastStore();
  const [search, setSearch] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [showDeleteAllDialog, setShowDeleteAllDialog] = useState(false);
  const [isDeletingAll, setIsDeletingAll] = useState(false);

  const qc = useQueryClient();
  const deleteForAll = useDeleteCard();

  const { data: archivedCards = [], isLoading, error } = useArchivedCards(projectId);

  // Filter by search
  const filtered: Card[] = archivedCards.filter((c) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      c.title.toLowerCase().includes(q) ||
      (c.description ?? '').toLowerCase().includes(q) ||
      (c.tags ?? []).some((t) => t.toLowerCase().includes(q))
    );
  });

  const handleRestored = () => setRefreshKey((k) => k + 1);
  const handleDeleted = () => setRefreshKey((k) => k + 1);

  const handleDeleteAll = async () => {
    setIsDeletingAll(true);
    let successCount = 0;
    let errorCount = 0;
    try {
      for (const card of archivedCards) {
        try {
          await deleteForAll.mutateAsync({ cardId: card.id, projectId });
          successCount++;
        } catch {
          errorCount++;
        }
      }
      if (errorCount === 0) {
        showToast(`${successCount} carte(s) supprimée(s) définitivement`, 'success', 3000);
      } else {
        showToast(`${successCount} supprimée(s), ${errorCount} erreur(s)`, 'error', 3000);
      }
    } finally {
      setIsDeletingAll(false);
      setShowDeleteAllDialog(false);
      qc.invalidateQueries({ queryKey: cardKeys.archived(projectId) });
      setRefreshKey((k) => k + 1);
    }
  };

  if (!projectId) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm p-10">
        No project selected.
      </div>
    );
  }

  return (
    <>
      <div key={refreshKey} className="flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border shrink-0 bg-background">
          <Archive size={16} className="text-muted-foreground shrink-0" />
          <span className="text-sm font-semibold text-foreground flex-1">
            Archived Cards
            {!isLoading && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                ({archivedCards.length} total)
              </span>
            )}
          </span>

          {/* Search */}
          <div className="relative w-48 shrink-0">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              placeholder="Search archives…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full h-7 pl-6 pr-6 text-xs bg-muted border border-border rounded-md outline-none focus:border-primary transition-colors placeholder:text-muted-foreground"
            />
            {search && (
              <button
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setSearch('')}
              >
                <X size={11} />
              </button>
            )}
          </div>

          {/* Vider les archives button */}
          {archivedCards.length > 0 && (
            <button
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs text-destructive border border-destructive/40 hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
              title="Supprimer toutes les archives définitivement"
              onClick={() => setShowDeleteAllDialog(true)}
              disabled={isLoading || isDeletingAll}
            >
              <Trash2 size={12} />
              <span>Vider les archives</span>
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground gap-2">
              <Loader2 size={16} className="animate-spin" />
              <span className="text-sm">Loading archives…</span>
            </div>
          ) : error ? (
            <div className="flex items-center justify-center py-16 text-destructive text-sm">
              Failed to load archived cards.
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
              <Archive size={32} className="opacity-30" />
              <p className="text-sm">
                {search ? 'No archived cards match your search.' : 'No archived cards yet.'}
              </p>
              {search && (
                <button
                  className="text-xs text-primary hover:underline cursor-pointer"
                  onClick={() => setSearch('')}
                >
                  Clear search
                </button>
              )}
            </div>
          ) : (
            <div>
              {filtered.map((card) => (
                <ArchivedCardRow
                  key={card.id}
                  card={card}
                  projectId={projectId}
                  onRestored={handleRestored}
                  onDeleted={handleDeleted}
                />
              ))}
            </div>
          )}
        </div>

        {/* Footer hint */}
        {filtered.length > 0 && (
          <div className="shrink-0 px-4 py-2 border-t border-border bg-muted/20">
            <p className="text-[0.65rem] text-muted-foreground">
              Hover a card to restore it or permanently delete it. Restore moves the card back to its original column.
            </p>
          </div>
        )}
      </div>

      {/* Confirmation dialog — Vider les archives */}
      <Dialog open={showDeleteAllDialog} onOpenChange={(open) => { if (!isDeletingAll) setShowDeleteAllDialog(open); }}>
        <DialogContent className="max-w-sm" showCloseButton={!isDeletingAll}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle size={18} />
              Vider les archives
            </DialogTitle>
            <DialogDescription>
              Cette action va supprimer{' '}
              <strong className="text-foreground">{archivedCards.length} carte(s) archivée(s)</strong>{' '}
              de façon permanente. Cette opération est irréversible.
            </DialogDescription>
          </DialogHeader>

          {isDeletingAll && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
              <Loader2 size={14} className="animate-spin shrink-0" />
              <span>Suppression en cours…</span>
            </div>
          )}

          <DialogFooter>
            <DialogClose asChild>
              <button
                className="px-3 py-1.5 rounded text-sm border border-border hover:bg-accent transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                disabled={isDeletingAll}
              >
                Annuler
              </button>
            </DialogClose>
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-sm bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
              onClick={handleDeleteAll}
              disabled={isDeletingAll}
            >
              {isDeletingAll
                ? <Loader2 size={13} className="animate-spin" />
                : <Trash2 size={13} />}
              Supprimer tout
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
