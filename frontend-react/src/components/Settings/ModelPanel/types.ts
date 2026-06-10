/**
 * ModelPanel — shared types.
 *
 * ── The `editingSection` contract ──────────────────────────────────────────
 * Only one section of the panel can be in edit mode at a time. The shared
 * `editingSection: string | null` state (owned by the ModelPanel orchestrator
 * in index.tsx) enforces this across every sub-component:
 *
 *   - `endpoint:<id>`        — a provider card (MachinesGrid) is being edited
 *   - `layer:<LayerKey>`     — a layer row (fast/deep/haiku) is being edited
 *   - `worker-class:<id>`    — a worker class is being edited
 *   - `default-worker-model` — the Default Worker section is being edited
 *   - `null`                 — nothing is being edited
 *
 * Edit buttons on other sections are disabled while editingSection is
 * non-null. Save persists then clears it (via saveAll); Cancel just clears.
 */

export type LayerKey = 'fast' | 'deep' | 'haiku';

/** Documented union of the `editingSection` values (see contract above). */
export type EditingSection =
  | `endpoint:${string}`
  | `layer:${LayerKey}`
  | `worker-class:${string}`
  | 'default-worker-model';

/** A named, saved endpoint (a machine or remote server). */
export interface ProviderEndpoint {
  id: string;
  name: string;
  provider_type: string;
  url: string;
  api_key: string;
}

export interface ModelLayerConfig {
  enabled: boolean;
  provider_type: string;
  provider_url: string;
  api_key: string;
  model: string;
  endpoint_id: string;
  context_1m: boolean;
}

/** A named worker class — routes task types to a specific LLM. */
export interface WorkerClass {
  id: string;
  name: string;
  description: string;
  endpoint_id: string;
  provider_type: string;
  model: string;
  intent_patterns: string[];
  // Canonical reasoning-effort: '' (model default) | low | medium | high | max.
  // Mapped per-provider on CLI workers (Claude --effort, Codex model_reasoning_effort).
  effort?: string;
}

export interface ModelsSettings {
  fast: ModelLayerConfig;
  deep: ModelLayerConfig;
  haiku: ModelLayerConfig;

  // Default worker fallback when no worker class matches the dispatched intent.
  // Either a layer alias ("haiku" | "sonnet" | "opus") or a real model id.
  default_worker_model: string;
  // Optional explicit provider override. Empty string = use the layer alias path.
  // Mirrors the WorkerClass shape (endpoint_id + provider_type + model).
  default_worker_provider_type: string;
  default_worker_endpoint_id: string;
  // Reasoning-effort for the default worker (no class match). '' = model default.
  default_worker_effort: string;

  endpoints: ProviderEndpoint[];
  worker_classes: WorkerClass[];
}

export interface AppSettings {
  models?: Partial<ModelsSettings>;
  [key: string]: unknown;
}

export interface ProviderMeta {
  type: string;
  label: string;
  requires_key: boolean;
  local: boolean;
  default_url: string;
}

export interface ModelCapabilities {
  model: string;
  provider: string;
  supports_tools: boolean;
  supports_vision: boolean;
  context_window: number;
  max_output_tokens: number;
}

export interface EndpointStatus {
  id: string;
  name: string;
  provider_type: string;
  url: string;
  reachable: boolean;
}

export interface AvailableData {
  layers: unknown;
  providers: Record<string, { reachable: boolean; label: string }>;
  endpoints: EndpointStatus[];
}

export interface TestResult {
  success: boolean;
  latency_ms?: number;
  reply?: string;
  error?: string;
}
