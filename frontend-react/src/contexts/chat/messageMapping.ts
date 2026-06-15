import { generateId } from '../../lib/utils';
import type { Message } from '../../types';

// ---------------------------------------------------------------------------
// Backend message → Message conversion (pure functions, no React)
// ---------------------------------------------------------------------------

/** Shape of a message returned by GET /api/sessions/{id} */
export interface BackendMessage {
  id?: string;
  role: string;
  content: string;
  timestamp?: string;
  model?: string;
  type?: string;
}

/**
 * Convert a list of backend session messages to local Message objects.
 *
 * Used by both `loadHistory` and the ws:connected truncated-message recovery
 * path — only the scoping fields differ between call sites (loadHistory knows
 * workspaceId/cardId; recovery only knows the sessionId), so they are passed
 * as options.
 */
export function convertBackendMessages(
  backendMessages: BackendMessage[],
  opts: { workspaceId?: string; cardId?: string; sessionId?: string } = {},
): Message[] {
  return backendMessages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .filter((m) => m.type !== 'enrichment' && m.type !== 'worker_result')
    .map((m) => ({
      // Prefer the server-assigned id so the manual delete endpoint
      // can target this message; fall back for ancient sessions
      // where backfill hasn't run yet.
      id: m.id || generateId(),
      role: m.role as 'user' | 'assistant',
      content: m.content || '',
      timestamp: m.timestamp ? new Date(m.timestamp).getTime() : Date.now(),
      workspaceId: opts.workspaceId,
      cardId: opts.cardId,
      sessionId: opts.sessionId,
      streaming: false,
      model: m.model,
    }));
}

/** Shape of the message payload in a chat:message:new broadcast */
export interface BroadcastChatMessage {
  role?: 'user' | 'assistant';
  content?: string;
  timestamp?: number; // seconds since epoch
  model?: string;
}

/**
 * Convert a chat:message:new broadcast payload (cross-device live sync) to a
 * local Message. Intentionally different from `convertBackendMessages`:
 * timestamps arrive as seconds (time.time()), there is never a server id, and
 * the workspaceId must be derived from the sessionId by the caller.
 *
 * Returns null when the payload is not a valid user/assistant message.
 */
export function convertBroadcastMessage(
  message: BroadcastChatMessage | undefined,
  opts: { sessionId?: string; workspaceId: string },
): Message | null {
  if (!message || !message.role || typeof message.content !== 'string') return null;
  if (message.role !== 'user' && message.role !== 'assistant') return null;

  // Timestamp from backend is seconds (time.time()) — convert to ms.
  const tsMs = typeof message.timestamp === 'number'
    ? Math.round(message.timestamp * 1000)
    : Date.now();

  return {
    id: generateId(),
    role: message.role,
    content: message.content,
    timestamp: tsMs,
    sessionId: opts.sessionId,
    workspaceId: opts.workspaceId,
    streaming: false,
    model: message.model,
  };
}
