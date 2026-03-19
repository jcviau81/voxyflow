/**
 * Whisper WebWorker — runs Transformers.js ASR pipeline off the main thread.
 *
 * Messages IN:
 *   { type: 'load', modelId: string }        — load/warm the pipeline
 *   { type: 'transcribe', audio: Float32Array, language?: string }
 *
 * Messages OUT:
 *   { type: 'status', status: 'loading' | 'ready' | 'error', message?: string }
 *   { type: 'progress', progress: number }   — model download progress
 *   { type: 'result', text: string }
 *   { type: 'error', message: string }
 */

import { pipeline, env } from '@huggingface/transformers';

// Disable local model caching path (use browser Cache API)
env.allowLocalModels = false;

// Use a loose type to avoid TS2590 "union type too complex" from @huggingface/transformers
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let transcriber: { (audio: Float32Array, options?: Record<string, unknown>): Promise<any> } | null = null;
let currentModelId = '';

async function loadModel(modelId: string): Promise<void> {
  if (transcriber && currentModelId === modelId) {
    self.postMessage({ type: 'status', status: 'ready' });
    return;
  }

  self.postMessage({ type: 'status', status: 'loading', message: `Loading ${modelId}…` });

  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    transcriber = await (pipeline as any)('automatic-speech-recognition', modelId, {
      dtype: 'q8',        // quantized for speed
      device: 'wasm',     // force WASM backend (no WebGPU requirement)
      progress_callback: (progress: Record<string, unknown>) => {
        if (typeof progress.progress === 'number') {
          self.postMessage({ type: 'progress', progress: progress.progress });
        }
      },
    });

    currentModelId = modelId;
    self.postMessage({ type: 'status', status: 'ready' });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    self.postMessage({ type: 'status', status: 'error', message });
    self.postMessage({ type: 'error', message });
  }
}

async function transcribe(audio: Float32Array, language?: string): Promise<void> {
  if (!transcriber) {
    self.postMessage({ type: 'error', message: 'Model not loaded' });
    return;
  }

  try {
    const options: Record<string, unknown> = {
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: false,
    };

    if (language && language !== 'auto') {
      options.language = language;
      options.task = 'transcribe';
    }

    const result = await transcriber(audio, options);

    // result can be { text: string } or array
    const text = Array.isArray(result)
      ? result.map((r) => (r as { text: string }).text).join(' ')
      : (result as { text: string }).text;

    self.postMessage({ type: 'result', text: text.trim() });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    self.postMessage({ type: 'error', message });
  }
}

self.addEventListener('message', (event: MessageEvent) => {
  const { type, modelId, audio, language } = event.data;

  switch (type) {
    case 'load':
      loadModel(modelId as string);
      break;
    case 'transcribe':
      transcribe(audio as Float32Array, language as string | undefined);
      break;
    default:
      console.warn('[WhisperWorker] Unknown message type:', type);
  }
});
