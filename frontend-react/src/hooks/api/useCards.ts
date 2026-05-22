import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { Card, CardStatus, CardRelation, CardRelationType, CardHistoryEntry, TimeEntry, ChecklistItem, CardAttachment } from '../../types';
import { useCardStore } from '../../stores/useCardStore';

const API = '';

// --- Mappers ---

export function mapRawCard(c: Record<string, unknown>): Card {
  return {
    ...(c as unknown as Card),
    workspaceId: (c.workspace_id as string) ?? null,
    agentType: c.agent_type as string | undefined,
    dependencies: (c.dependency_ids as string[]) ?? [],
    totalMinutes: (c.total_minutes as number) ?? 0,
    checklistProgress: (c.checklist_progress as Card['checklistProgress']) ?? undefined,
    position: (c.position as number) ?? 0,
    createdAt: c.created_at ? new Date(c.created_at as string).getTime() : Date.now(),
    updatedAt: c.updated_at ? new Date(c.updated_at as string).getTime() : Date.now(),
    tags: (c.tags as string[]) ?? [],
    chatHistory: (c.chat_history as string[]) ?? [],
    assignee: (c.assignee as string) ?? null,
    watchers: (c.watchers as string) ?? '',
    votes: (c.votes as number) ?? 0,
    preferredModel: (c.preferred_model as Card['preferredModel']) ?? null,
    recurring: (c.recurring as boolean) ?? false,
    files: (c.files as string[]) ?? [],
  };
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${url}`, options);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({})) as { detail?: string };
    throw new Error(detail.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// --- Query keys ---

export const cardKeys = {
  all: ['cards'] as const,
  byWorkspace: (workspaceId: string) => ['cards', 'workspace', workspaceId] as const,
  archived: (workspaceId: string) => ['cards', 'archived', workspaceId] as const,
  detail: (cardId: string) => ['cards', cardId] as const,
  timeEntries: (cardId: string) => ['cards', cardId, 'time'] as const,
  checklist: (cardId: string) => ['cards', cardId, 'checklist'] as const,
  attachments: (cardId: string) => ['cards', cardId, 'attachments'] as const,
  relations: (cardId: string) => ['cards', cardId, 'relations'] as const,
  history: (cardId: string) => ['cards', cardId, 'history'] as const,
};

// --- Queries ---

export function useCards(workspaceId: string) {
  return useQuery({
    queryKey: cardKeys.byWorkspace(workspaceId),
    queryFn: async () => {
      const raw = await apiFetch<Record<string, unknown>[]>(`/api/workspaces/${workspaceId}/cards`);
      return raw.map(mapRawCard);
    },
    staleTime: 30_000,
    enabled: !!workspaceId,
  });
}

export function useArchivedCards(workspaceId: string) {
  return useQuery({
    queryKey: cardKeys.archived(workspaceId),
    queryFn: async () => {
      const raw = await apiFetch<Record<string, unknown>[]>(`/api/workspaces/${workspaceId}/cards/archived`);
      return raw.map(mapRawCard);
    },
    staleTime: 60_000,
    enabled: !!workspaceId,
  });
}

export function useTimeEntries(cardId: string) {
  return useQuery({
    queryKey: cardKeys.timeEntries(cardId),
    queryFn: async () => {
      const data = await apiFetch<Array<{ id: string; card_id: string; duration_minutes: number; note?: string; logged_at: string }>>(`/api/cards/${cardId}/time`);
      return data.map((e): TimeEntry => ({
        id: e.id,
        cardId: e.card_id,
        durationMinutes: e.duration_minutes,
        note: e.note,
        loggedAt: new Date(e.logged_at).getTime(),
      }));
    },
    staleTime: 30_000,
    enabled: !!cardId,
  });
}

export function useChecklist(cardId: string) {
  return useQuery({
    queryKey: cardKeys.checklist(cardId),
    queryFn: async () => {
      const data = await apiFetch<Array<{ id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string }>>(`/api/cards/${cardId}/checklist`);
      return data.map((i): ChecklistItem => ({
        id: i.id,
        cardId: i.card_id,
        text: i.text,
        completed: i.completed,
        position: i.position,
        createdAt: new Date(i.created_at).getTime(),
      }));
    },
    staleTime: 30_000,
    enabled: !!cardId,
  });
}

export function useAttachments(cardId: string) {
  return useQuery({
    queryKey: cardKeys.attachments(cardId),
    queryFn: async () => {
      const data = await apiFetch<Array<{ id: string; card_id: string; filename: string; file_size: number; mime_type: string; created_at: string }>>(`/api/cards/${cardId}/attachments`);
      return data.map((a): CardAttachment => ({
        id: a.id,
        cardId: a.card_id,
        filename: a.filename,
        fileSize: a.file_size,
        mimeType: a.mime_type,
        createdAt: new Date(a.created_at).getTime(),
      }));
    },
    staleTime: 60_000,
    enabled: !!cardId,
  });
}

export function useRelations(cardId: string) {
  return useQuery({
    queryKey: cardKeys.relations(cardId),
    queryFn: async () => {
      const data = await apiFetch<Array<{
        id: string; source_card_id: string; target_card_id: string; relation_type: string;
        created_at: string; related_card_id: string; related_card_title: string; related_card_status: string;
      }>>(`/api/cards/${cardId}/relations`);
      return data.map((r): CardRelation => ({
        id: r.id,
        sourceCardId: r.source_card_id,
        targetCardId: r.target_card_id,
        relationType: r.relation_type as CardRelationType,
        createdAt: r.created_at,
        relatedCardId: r.related_card_id,
        relatedCardTitle: r.related_card_title,
        relatedCardStatus: r.related_card_status,
      }));
    },
    staleTime: 60_000,
    enabled: !!cardId,
  });
}

export function useCardHistory(cardId: string) {
  return useQuery({
    queryKey: cardKeys.history(cardId),
    queryFn: async () => {
      const data = await apiFetch<Array<{
        id: string; card_id: string; field_changed: string;
        old_value: string | null; new_value: string | null;
        changed_at: string; changed_by: string;
      }>>(`/api/cards/${cardId}/history`);
      return data.map((e): CardHistoryEntry => ({
        id: e.id,
        cardId: e.card_id,
        fieldChanged: e.field_changed,
        oldValue: e.old_value,
        newValue: e.new_value,
        changedAt: e.changed_at,
        changedBy: e.changed_by,
      }));
    },
    staleTime: 60_000,
    enabled: !!cardId,
  });
}

// --- Mutations ---

export function useCreateCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: { workspaceId: string; title: string; description?: string; status?: CardStatus; priority?: number }) => {
      const raw = await apiFetch<Record<string, unknown>>(`/api/workspaces/${data.workspaceId}/cards`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: data.title,
          description: data.description ?? '',
          status: data.status ?? 'backlog',
          priority: data.priority ?? 0,
        }),
      });
      return mapRawCard(raw);
    },
    onSuccess: (card) => {
      useCardStore.getState().upsertCard(card);
      if (card.workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(card.workspaceId) });
      }
    },
  });
}

export function usePatchCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      cardId,
      updates,
    }: {
      cardId: string;
      updates: Record<string, unknown>;
      /** Optional: scopes query invalidation to a single workspace instead of all cards. */
      workspaceId?: string;
    }) => {
      return apiFetch<Record<string, unknown>>(`/api/cards/${cardId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      });
    },
    onMutate: ({ cardId }) => {
      // Snapshot the previous card from the Zustand store so we can roll back on error.
      // Callers (KanbanBoard, FreeBoard, KanbanCard) apply their own optimistic update
      // before calling mutateAsync — this rollback is a safety net for fire-and-forget
      // .mutate() call sites that don't await / try-catch.
      const previousCard = useCardStore.getState().cardsById[cardId];
      return { previousCard };
    },
    onError: (_err, _vars, context) => {
      // Roll back the optimistic store write if we have a previous snapshot.
      // Callers that do their own try/catch rollback will simply overwrite this.
      const previousCard = context?.previousCard;
      if (previousCard) {
        useCardStore.getState().upsertCard(previousCard);
      }
    },
    onSettled: (_data, _err, { cardId, workspaceId }) => {
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
      } else {
        qc.invalidateQueries({ queryKey: cardKeys.all });
      }
      qc.invalidateQueries({ queryKey: cardKeys.detail(cardId) });
    },
  });
}

export function useDeleteCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId }: { cardId: string; workspaceId?: string }) => {
      const res = await fetch(`${API}/api/cards/${cardId}`, { method: 'DELETE' });
      if (!res.ok && res.status !== 404) {
        const detail = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${res.status}`);
      }
    },
    onSuccess: (_data, { cardId, workspaceId }) => {
      useCardStore.getState().deleteCard(cardId);
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
        qc.invalidateQueries({ queryKey: cardKeys.archived(workspaceId) });
      } else {
        qc.invalidateQueries({ queryKey: cardKeys.all });
      }
    },
  });
}

export function useArchiveCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId }: { cardId: string; workspaceId?: string }) => {
      await apiFetch(`/api/cards/${cardId}/archive`, { method: 'POST' });
    },
    onSuccess: (_data, { workspaceId }) => {
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
        qc.invalidateQueries({ queryKey: cardKeys.archived(workspaceId) });
      }
      // Always invalidate all to ensure UI reflects the change immediately
      qc.invalidateQueries({ queryKey: cardKeys.all });
    },
  });
}

export function useRestoreCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId }: { cardId: string; workspaceId?: string }) => {
      const raw = await apiFetch<Record<string, unknown>>(`/api/cards/${cardId}/restore`, { method: 'POST' });
      return mapRawCard(raw);
    },
    onSuccess: (card, { workspaceId }) => {
      // Optimistic: add restored card back to the store immediately
      useCardStore.getState().upsertCard(card);
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
        qc.invalidateQueries({ queryKey: cardKeys.archived(workspaceId) });
      }
    },
  });
}

export function useDuplicateCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId }: { cardId: string; workspaceId?: string }) => {
      const raw = await apiFetch<Record<string, unknown>>(`/api/cards/${cardId}/duplicate`, { method: 'POST' });
      return mapRawCard(raw);
    },
    onSuccess: (card, { workspaceId }) => {
      useCardStore.getState().upsertCard(card);
      if (workspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(workspaceId) });
      }
    },
  });
}

export function useCloneCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, targetWorkspaceId }: { cardId: string; targetWorkspaceId: string; sourceWorkspaceId?: string }) => {
      const raw = await apiFetch<Record<string, unknown>>(`/api/cards/${cardId}/clone-to/${targetWorkspaceId}`, { method: 'POST' });
      return mapRawCard(raw);
    },
    onSuccess: (card, { targetWorkspaceId, sourceWorkspaceId }) => {
      useCardStore.getState().upsertCard(card);
      qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(targetWorkspaceId) });
      if (sourceWorkspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(sourceWorkspaceId) });
      }
    },
  });
}

export function useMoveCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, targetWorkspaceId }: { cardId: string; targetWorkspaceId: string; sourceWorkspaceId?: string }) => {
      const raw = await apiFetch<Record<string, unknown>>(`/api/cards/${cardId}/move-to/${targetWorkspaceId}`, { method: 'POST' });
      return mapRawCard(raw);
    },
    onSuccess: (card, { targetWorkspaceId, sourceWorkspaceId }) => {
      // Remove from source workspace in store, add to target
      if (sourceWorkspaceId) {
        useCardStore.getState().deleteCard(card.id);
      }
      useCardStore.getState().upsertCard(card);
      qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(targetWorkspaceId) });
      if (sourceWorkspaceId) {
        qc.invalidateQueries({ queryKey: cardKeys.byWorkspace(sourceWorkspaceId) });
      }
      // Always invalidate all to catch Main Board and edge cases
      qc.invalidateQueries({ queryKey: cardKeys.all });
    },
  });
}

export function useReorderCards() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (orderedCardIds: string[]) => {
      const res = await fetch(`${API}/api/cards/bulk-reorder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ordered_ids: orderedCardIds }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(detail.detail ?? `HTTP ${res.status}`);
      }
      // 204 No Content — do not parse JSON.
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: cardKeys.all });
    },
  });
}


export function useExecuteCard() {
  return useMutation({
    mutationFn: async (cardId: string) => {
      return apiFetch<{ prompt: string; workspaceName?: string }>(`/api/cards/${cardId}/execute`, { method: 'POST' });
    },
  });
}

export function useVoteCard() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, unvote = false }: { cardId: string; unvote?: boolean }) => {
      return apiFetch<{ votes: number }>(`/api/cards/${cardId}/vote`, {
        method: unvote ? 'DELETE' : 'POST',
      });
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.detail(cardId) });
    },
  });
}

// --- Time entry mutations ---

export function useLogTime() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, durationMinutes, note }: { cardId: string; durationMinutes: number; note?: string }) => {
      const e = await apiFetch<{ id: string; card_id: string; duration_minutes: number; note?: string; logged_at: string }>(
        `/api/cards/${cardId}/time`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ duration_minutes: durationMinutes, note: note ?? null }),
        }
      );
      return { id: e.id, cardId: e.card_id, durationMinutes: e.duration_minutes, note: e.note, loggedAt: new Date(e.logged_at).getTime() } satisfies TimeEntry;
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.timeEntries(cardId) });
    },
  });
}

export function useDeleteTimeEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, entryId }: { cardId: string; entryId: string }) => {
      await fetch(`${API}/api/cards/${cardId}/time/${entryId}`, { method: 'DELETE' });
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.timeEntries(cardId) });
    },
  });
}

// --- Checklist mutations ---

export function useAddChecklistItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, text }: { cardId: string; text: string }) => {
      const i = await apiFetch<{ id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string }>(
        `/api/cards/${cardId}/checklist`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        }
      );
      return { id: i.id, cardId: i.card_id, text: i.text, completed: i.completed, position: i.position, createdAt: new Date(i.created_at).getTime() } satisfies ChecklistItem;
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.checklist(cardId) });
    },
  });
}

export function useUpdateChecklistItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, itemId, updates }: { cardId: string; itemId: string; updates: { text?: string; completed?: boolean } }) => {
      const i = await apiFetch<{ id: string; card_id: string; text: string; completed: boolean; position: number; created_at: string }>(
        `/api/cards/${cardId}/checklist/${itemId}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updates),
        }
      );
      return { id: i.id, cardId: i.card_id, text: i.text, completed: i.completed, position: i.position, createdAt: new Date(i.created_at).getTime() } satisfies ChecklistItem;
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.checklist(cardId) });
    },
  });
}

export function useDeleteChecklistItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, itemId }: { cardId: string; itemId: string }) => {
      await fetch(`${API}/api/cards/${cardId}/checklist/${itemId}`, { method: 'DELETE' });
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.checklist(cardId) });
    },
  });
}

// --- Attachment mutations ---

export function useUploadAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, file }: { cardId: string; file: File }) => {
      const formData = new FormData();
      formData.append('file', file);
      const a = await apiFetch<{ id: string; card_id: string; filename: string; file_size: number; mime_type: string; created_at: string }>(
        `/api/cards/${cardId}/attachments`,
        { method: 'POST', body: formData }
      );
      return { id: a.id, cardId: a.card_id, filename: a.filename, fileSize: a.file_size, mimeType: a.mime_type, createdAt: new Date(a.created_at).getTime() } satisfies CardAttachment;
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.attachments(cardId) });
    },
  });
}

export function useDeleteAttachment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, attachmentId }: { cardId: string; attachmentId: string }) => {
      await fetch(`${API}/api/cards/${cardId}/attachments/${attachmentId}`, { method: 'DELETE' });
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.attachments(cardId) });
    },
  });
}

// --- Relation mutations ---

export function useAddRelation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, targetCardId, relationType }: { cardId: string; targetCardId: string; relationType: string }) => {
      const r = await apiFetch<{
        id: string; source_card_id: string; target_card_id: string; relation_type: string;
        created_at: string; related_card_id: string; related_card_title: string; related_card_status: string;
      }>(`/api/cards/${cardId}/relations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_card_id: targetCardId, relation_type: relationType }),
      });
      return {
        id: r.id, sourceCardId: r.source_card_id, targetCardId: r.target_card_id,
        relationType: r.relation_type as CardRelationType, createdAt: r.created_at,
        relatedCardId: r.related_card_id, relatedCardTitle: r.related_card_title, relatedCardStatus: r.related_card_status,
      } satisfies CardRelation;
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.relations(cardId) });
    },
  });
}

export function useDeleteRelation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ cardId, relationId }: { cardId: string; relationId: string }) => {
      await fetch(`${API}/api/cards/${cardId}/relations/${relationId}`, { method: 'DELETE' });
    },
    onSuccess: (_data, { cardId }) => {
      qc.invalidateQueries({ queryKey: cardKeys.relations(cardId) });
    },
  });
}

// --- Utility ---

export function getAttachmentDownloadUrl(cardId: string, attachmentId: string): string {
  return `${API}/api/cards/${cardId}/attachments/${attachmentId}/download`;
}
