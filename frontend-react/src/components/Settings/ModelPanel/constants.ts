/**
 * ModelPanel — shared constants (defaults, provider sets, static model lists).
 */

import type { LayerKey, ModelLayerConfig, ModelsSettings, WorkerClass } from './types';

export const THINKING_MODELS = ['claude-sonnet-4', 'claude-opus-4', 'deepseek-r', 'qwq', 'o1', 'o3'];

export const DEFAULT_LAYER: ModelLayerConfig = {
  enabled: true,
  provider_type: 'cli',
  provider_url: '',
  api_key: '',
  model: '',
  endpoint_id: '',
  context_1m: false,
};

export const DEFAULT_WORKER_CLASSES: WorkerClass[] = [
  {
    id: '00000000-0000-0000-0000-000000000006',
    name: 'Architecture',
    description: 'System design, structural decisions, cross-cutting architecture',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-opus-4-7',
    effort: 'max',
    intent_patterns: ['architect', 'architecture', 'system_design', 'structural', 'redesign'],
  },
  {
    id: '00000000-0000-0000-0000-000000000005',
    name: 'Complex Coding',
    description: 'Multi-file changes, major refactors, complex features',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-opus-4-7',
    effort: 'high',
    intent_patterns: ['multi_file', 'multifile', 'major_refactor', 'complex_implement', 'complex_feature', 'large_refactor'],
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    name: 'Coding',
    description: 'Code writing, debugging, refactoring, code review',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-sonnet-4-6',
    effort: 'high',
    intent_patterns: ['debug', 'refactor', 'implement', 'unit test', 'fix bug', 'code review', 'write code'],
  },
  {
    id: '00000000-0000-0000-0000-000000000003',
    name: 'Research',
    description: 'Deep research, analysis, multi-step investigation',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-opus-4-7',
    effort: 'high',
    intent_patterns: ['research', 'investigate', 'analyze', 'compare alternatives', 'feasibility', 'fact check'],
  },
  {
    id: '00000000-0000-0000-0000-000000000004',
    name: 'Creative',
    description: 'Writing, brainstorming, ideation, narrative',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-sonnet-4-6',
    effort: 'medium',
    intent_patterns: ['brainstorm', 'brainstorming', 'creative writing', 'story', 'narrative', 'ideation'],
  },
  {
    id: '00000000-0000-0000-0000-000000000001',
    name: 'Quick',
    description: 'Fast, lightweight tasks — summaries, simple Q&A, formatting',
    endpoint_id: '',
    provider_type: 'cli',
    model: 'claude-haiku-4-5-20251001',
    effort: 'low',
    intent_patterns: ['summarize', 'summarization', 'tldr', 'reformat', 'rephrase'],
  },
];

export const DEFAULT_MODELS: ModelsSettings = {
  fast: { ...DEFAULT_LAYER, model: 'claude-sonnet-4' },
  deep: { ...DEFAULT_LAYER, model: 'claude-opus-4' },
  haiku: { ...DEFAULT_LAYER, provider_type: '', model: '' },

  default_worker_model: 'sonnet',
  default_worker_provider_type: '',
  default_worker_endpoint_id: '',
  default_worker_effort: '',
  endpoints: [],
  worker_classes: DEFAULT_WORKER_CLASSES,
};

export const LAYER_META: Record<LayerKey, { label: string; icon: string; placeholder: string; showEnabled: boolean; description?: string }> = {
  fast: { label: 'Fast', icon: '⚡', placeholder: 'claude-sonnet-4', showEnabled: false },
  deep: { label: 'Deep', icon: '🧠', placeholder: 'claude-opus-4',  showEnabled: true  },
  haiku: {
    label: 'Utility',
    icon: '🪶',
    placeholder: 'mirror Fast layer',
    showEnabled: false,
    description: 'Summarizes long chats and extracts memories. Leave empty to mirror Fast.',
  },
};

export const NO_URL_PROVIDERS = new Set(['cli', 'codex', 'anthropic']);
export const NO_KEY_PROVIDERS = new Set(['cli', 'codex', 'ollama', 'lmstudio']);
export const LISTABLE_PROVIDERS = new Set(['ollama', 'openai', 'groq', 'mistral', 'lmstudio', 'gemini', 'anthropic', 'cli', 'codex', 'openrouter']);
export const LOCAL_PROVIDER_TYPES = new Set(['ollama', 'lmstudio']);

// Static fallback model lists for cloud providers (shown when API listing is unavailable)
export const STATIC_MODELS: Record<string, string[]> = {
  // Aliases only — the Claude CLI resolves opus/sonnet/haiku to the latest
  // model (opus → Opus 4.8 today), so no hardcoded version names. Transient
  // placeholder / error fallback; the live list (incl. real claude-* ids when
  // an Anthropic key is configured) comes from /api/models/list?provider_type=cli.
  cli: ['opus', 'sonnet', 'haiku'],
  codex: ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.3-codex', 'gpt-5.2'],
  anthropic: ['claude-haiku-4-5-20251001', 'claude-sonnet-4-6', 'claude-opus-4-7', 'claude-opus-4-6', 'claude-sonnet-4-5', 'claude-opus-4-5'],
  groq: [
    'llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'llama-3.1-8b-instant',
    'mixtral-8x7b-32768', 'gemma2-9b-it', 'gemma-7b-it',
  ],
  mistral: [
    'mistral-large-latest', 'mistral-medium-latest', 'mistral-small-latest',
    'open-mixtral-8x22b', 'open-mistral-7b', 'codestral-latest',
  ],
  openai: [
    'gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-4',
    'gpt-3.5-turbo', 'o1', 'o1-mini', 'o3-mini',
  ],
  gemini: [
    'gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-1.5-pro',
    'gemini-1.5-flash', 'gemini-1.5-flash-8b',
  ],
  openrouter: [
    'openai/gpt-4o', 'openai/gpt-4o-mini', 'anthropic/claude-opus-4-6',
    'anthropic/claude-sonnet-4-6', 'anthropic/claude-haiku-4-5',
    'google/gemini-2.0-flash', 'meta-llama/llama-3.3-70b-instruct',
    'mistralai/mistral-large', 'deepseek/deepseek-chat', 'qwen/qwen-2.5-72b-instruct',
  ],
};

export const CLOUD_PROVIDER_TYPES = new Set(['anthropic', 'groq', 'mistral', 'gemini', 'openrouter', 'openai']);
export const CLOUD_DEFAULT_URLS: Record<string, string> = {
  anthropic: 'https://api.anthropic.com',
  groq: 'https://api.groq.com/openai/v1',
  mistral: 'https://api.mistral.ai/v1',
  gemini: 'https://generativelanguage.googleapis.com/v1beta/openai',
  openrouter: 'https://openrouter.ai/api/v1',
  openai: 'https://api.openai.com/v1',
};

export const EMPTY_WORKER_CLASS: WorkerClass = {
  id: '',
  name: '',
  description: '',
  endpoint_id: '',
  provider_type: 'cli',
  model: '',
  intent_patterns: [],
  effort: '',
};

// Canonical reasoning-effort options shared by the worker-class editor and the
// default-worker selector. '' = model/CLI default (no flag emitted). Mapped
// per-provider on CLI workers (Claude --effort; Codex model_reasoning_effort,
// where max clamps to high).
export const EFFORT_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Default (model)' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'max', label: 'Max' },
];

// Legacy short aliases that resolve to a layer at runtime (Fast/Deep/Utility).
// Kept as a synthetic source so users can still pick "use whatever the Fast
// layer is configured for" without committing to a specific provider.
export const LAYER_ALIAS_OPTIONS: { value: string; label: string }[] = [
  { value: 'sonnet', label: 'Layer alias: Sonnet (uses Fast layer)' },
  { value: 'haiku',  label: 'Layer alias: Haiku (uses Utility layer)' },
  { value: 'opus',   label: 'Layer alias: Opus (uses Deep layer)' },
];

export const LAYER_ALIAS_VALUES = new Set(LAYER_ALIAS_OPTIONS.map(o => o.value));
