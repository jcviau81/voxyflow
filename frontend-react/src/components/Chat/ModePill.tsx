/**
 * ModePill — Fast (Sonnet) / Deep (Opus) / Analyzer mode toggles.
 *
 * Layer state is persisted to localStorage under 'voxyflow_layer_toggles'.
 * Analyzer toggle is also synced to backend settings (models.analyzer.enabled)
 * so the state survives page reloads and reflects the true backend state.
 *
 * Designed to sit in the chat bottom bar alongside the input.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { Zap, Brain, Search } from 'lucide-react';
import { cn } from '../../lib/utils';
import { eventBus } from '../../utils/eventBus';

const LAYER_STORAGE_KEY = 'voxyflow_layer_toggles';

interface LayerState {
  deep: boolean;
  analyzer: boolean;
}

function getLayerState(): LayerState {
  try {
    const stored = localStorage.getItem(LAYER_STORAGE_KEY);
    if (stored) return JSON.parse(stored) as LayerState;
  } catch { /* ignore */ }
  return { deep: true, analyzer: false };
}

function saveLayerState(state: LayerState): void {
  localStorage.setItem(LAYER_STORAGE_KEY, JSON.stringify(state));
}

/** Persist analyzer enabled state to backend settings (fire-and-forget). */
async function persistAnalyzerToBackend(enabled: boolean): Promise<void> {
  try {
    const res = await fetch('/api/settings');
    if (!res.ok) return;
    const settings = await res.json();
    settings.models = settings.models || {};
    settings.models.analyzer = settings.models.analyzer || {};
    settings.models.analyzer.enabled = enabled;
    await fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    });
  } catch { /* fire-and-forget */ }
}

export function ModePill({ className }: { className?: string }) {
  const [layerState, setLayerStateLocal] = useState<LayerState>(getLayerState);
  const [analyzerRunning, setAnalyzerRunning] = useState(false);
  const initDone = useRef(false);

  // On mount: read analyzer enabled from backend settings → sync to localStorage
  useEffect(() => {
    if (initDone.current) return;
    initDone.current = true;
    fetch('/api/settings')
      .then((r) => (r.ok ? r.json() : null))
      .then((settings) => {
        if (!settings) return;
        const backendEnabled = settings?.models?.analyzer?.enabled ?? false;
        const prev = getLayerState();
        if (prev.analyzer !== backendEnabled) {
          const next = { ...prev, analyzer: backendEnabled };
          saveLayerState(next);
          setLayerStateLocal(next);
        }
      })
      .catch(() => { /* ignore */ });
  }, []);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === LAYER_STORAGE_KEY) {
        setLayerStateLocal(getLayerState());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // Listen to model:status events from the WebSocket (forwarded by ChatProvider via eventBus)
  // so the analyzer button shows a live running indicator when the backend is scanning.
  useEffect(() => {
    return eventBus.on('model:status', (data) => {
      const { model, state } = data as { model: string; state: string };
      if (model === 'analyzer') {
        setAnalyzerRunning(state === 'thinking' || state === 'active');
      }
    });
  }, []);

  const setDeepMode = useCallback((deep: boolean) => {
    const prev = getLayerState();
    const next = { ...prev, deep };
    saveLayerState(next);
    setLayerStateLocal(next);
    if (prev.deep !== deep && window.innerWidth <= 768) {
      window.dispatchEvent(new CustomEvent('mobile:clear-chat'));
    }
  }, []);

  const toggleAnalyzer = useCallback(() => {
    const prev = getLayerState();
    const next = { ...prev, analyzer: !prev.analyzer };
    saveLayerState(next);
    setLayerStateLocal(next);
    persistAnalyzerToBackend(next.analyzer);
  }, []);

  return (
    <div className={cn('flex items-center rounded-full border border-border bg-muted/50 p-0.5 gap-0.5', className)}>
      <button
        className={cn(
          'px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
          !layerState.deep
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'
        )}
        title="Fast mode (Sonnet)"
        onClick={() => setDeepMode(false)}
      >
        <Zap size={13} />
      </button>
      <button
        className={cn(
          'px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
          layerState.deep
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'
        )}
        title="Deep mode (Opus)"
        onClick={() => setDeepMode(true)}
      >
        <Brain size={13} />
      </button>
      <button
        className={cn(
          'px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors relative',
          layerState.analyzer
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'
        )}
        title={analyzerRunning ? 'Analyzer running…' : 'Analyzer (card suggestions)'}
        onClick={toggleAnalyzer}
      >
        <Search size={13} className={analyzerRunning ? 'animate-pulse' : undefined} />
        {analyzerRunning && (
          <span className="absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full bg-green-500 animate-ping" />
        )}
      </button>
    </div>
  );
}
