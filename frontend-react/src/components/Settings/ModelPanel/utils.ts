/**
 * ModelPanel — small shared helpers.
 */

import { generateId } from '@/lib/utils';
import { apiFetch as sharedApiFetch } from '@/lib/apiClient';
import { THINKING_MODELS } from './constants';

export function newId() {
  return generateId();
}

// ── Helpers ────────────────────────────────────────────────────────────────

export function isThinkingModel(model: string): boolean {
  const lower = (model || '').toLowerCase();
  return THINKING_MODELS.some((t) => lower.includes(t.toLowerCase()));
}

export function formatContext(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(0)}M ctx`;
  if (tokens >= 1_000)     return `${(tokens / 1_000).toFixed(0)}k ctx`;
  return `${tokens} ctx`;
}

/** Extract host:port from a full URL */
export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return u.host;
  } catch {
    return url;
  }
}

/** Capitalize first letter of provider type for display */
export function providerLabel(type: string): string {
  const labels: Record<string, string> = {
    ollama: 'Ollama',
    lmstudio: 'LM Studio',
    openai: 'OpenAI-compat',
    cli: 'Claude CLI',
    codex: 'Codex CLI',
    anthropic: 'Anthropic',
    groq: 'Groq',
    mistral: 'Mistral',
    gemini: 'Gemini',
    openrouter: 'OpenRouter',
  };
  return labels[type] || type;
}

export const apiFetch = sharedApiFetch;
