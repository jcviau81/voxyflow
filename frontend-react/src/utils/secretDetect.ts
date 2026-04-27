// Heuristic detector for "this pasted text might contain an API key".
// Passive only — caller decides what to do with a match (typically: show a
// non-blocking toast suggesting the user delete the message after Voxy is
// done with the key).
//
// Two-step matching:
//   1. Strip annotated card-id paste prefixes ("Card ID: <uuid>") that the
//      KanbanCard right-click menu produces. Anything inside that prefix is
//      definitively NOT a secret — it's an internal id the user explicitly
//      asked to share.
//   2. On the residue, look for vendor-prefix tokens (high confidence) and
//      bare UUID v4 strings (medium confidence — covers vendors like
//      Pixellab whose keys happen to share UUID v4 format and would be
//      indistinguishable from card ids without the strip step above).

export type SecretMatchKind = 'vendor' | 'jwt' | 'uuid';

export interface SecretMatch {
  matched: boolean;
  kind?: SecretMatchKind;
}

const CARD_ID_PREFIX_RE = /Card ID:\s*[0-9a-fA-F-]{36}/g;

const VENDOR_PREFIX_RES: Array<[RegExp, SecretMatchKind]> = [
  [/\bsk-ant-[A-Za-z0-9_-]{20,}/, 'vendor'],
  [/\bsk-[A-Za-z0-9_-]{20,}/, 'vendor'],
  [/\bghp_[A-Za-z0-9]{20,}/, 'vendor'],
  [/\bgho_[A-Za-z0-9]{20,}/, 'vendor'],
  [/\bgithub_pat_[A-Za-z0-9_]{20,}/, 'vendor'],
  [/\bxox[bpors]-[A-Za-z0-9-]{10,}/, 'vendor'],
  [/\bAIza[0-9A-Za-z_-]{20,}/, 'vendor'],
  [/\bAKIA[0-9A-Z]{16}\b/, 'vendor'],
  [/\bglpat-[A-Za-z0-9_-]{20,}/, 'vendor'],
  [/\bhf_[A-Za-z0-9]{20,}/, 'vendor'],
  [/\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/, 'jwt'],
];

const UUID_RE = /\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b/;

export function looksLikeSecret(text: string): SecretMatch {
  if (!text) return { matched: false };

  const stripped = text.replace(CARD_ID_PREFIX_RE, ' ');

  for (const [re, kind] of VENDOR_PREFIX_RES) {
    if (re.test(stripped)) return { matched: true, kind };
  }

  if (UUID_RE.test(stripped)) return { matched: true, kind: 'uuid' };

  return { matched: false };
}
