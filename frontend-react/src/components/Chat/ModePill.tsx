/**
 * ModePill — Fast (Sonnet) / Deep (Opus) / Analyzer mode toggles.
 *
 * Layer state is persisted to localStorage under 'voxyflow_layer_toggles'.
 * Designed to sit in the chat bottom bar alongside the input.
 */

import { useState, useCallback, useEffect } from 'react';
import { cn } from '../../lib/utils';

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

export function ModePill({ className }: { className?: string }) {
  const [layerState, setLayerStateLocal] = useState<LayerState>(getLayerState);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === LAYER_STORAGE_KEY) {
        setLayerStateLocal(getLayerState());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
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
        ⚡
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
        🧠
      </button>
      <button
        className={cn(
          'px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
          layerState.analyzer
            ? 'bg-background text-foreground shadow-sm'
            : 'text-muted-foreground hover:text-foreground'
        )}
        title="Analyzer (card suggestions)"
        onClick={toggleAnalyzer}
      >
        🔍
      </button>
    </div>
  );
}
