/**
 * TopBar — React port of frontend/src/components/Navigation/TopBar.ts
 *
 * Contains:
 *   - Mobile hamburger button (toggles sidebar)
 *   - Project name (emoji + name, or 'Main')
 *   - Mode pill: Fast (Sonnet) / Deep (Opus) / Analyzer toggles
 *   - Voice buttons: auto-send (STT) and auto-play (TTS)
 *
 * Layer state is persisted to localStorage under 'voxyflow_layer_toggles'.
 * Voice settings are persisted under 'voxyflow_settings' and synced to backend.
 */

import { useState, useCallback, useEffect } from 'react';
import { Menu } from 'lucide-react';
import { cn } from '../../lib/utils';
import { useProjectStore } from '../../stores/useProjectStore';

const LAYER_STORAGE_KEY = 'voxyflow_layer_toggles';
const SETTINGS_STORAGE_KEY = 'voxyflow_settings';

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

function getVoiceSetting(key: string, defaultVal: boolean): boolean {
  try {
    const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (stored) {
      const settings = JSON.parse(stored) as Record<string, Record<string, boolean>>;
      return settings?.voice?.[key] ?? defaultVal;
    }
  } catch { /* ignore */ }
  return defaultVal;
}

function setVoiceSetting(key: string, value: boolean): void {
  try {
    const stored = localStorage.getItem(SETTINGS_STORAGE_KEY);
    const settings: Record<string, Record<string, boolean>> = stored
      ? (JSON.parse(stored) as Record<string, Record<string, boolean>>)
      : {};
    if (!settings.voice) settings.voice = {};
    settings.voice[key] = value;
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    // Fire-and-forget sync to backend
    fetch('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }).catch(() => { /* ignore */ });
  } catch { /* ignore */ }
}

interface TopBarProps {
  onMenuClick: () => void;
}

export function TopBar({ onMenuClick }: TopBarProps) {
  const currentProjectId = useProjectStore((s) => s.currentProjectId);
  const getProject = useProjectStore((s) => s.getProject);

  const project = currentProjectId ? getProject(currentProjectId) : undefined;
  const projectName = project
    ? `${project.emoji ? project.emoji + ' ' : ''}${project.name}`
    : 'Main';

  // Layer state (mode pill)
  const [layerState, setLayerStateLocal] = useState<LayerState>(getLayerState);

  // Voice settings
  const [autoPlay, setAutoPlayLocal] = useState(() => getVoiceSetting('tts_auto_play', false));
  const [autoSend, setAutoSendLocal] = useState(() => getVoiceSetting('stt_auto_send', false));

  // Keep layer state in sync when localStorage changes from another tab
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === LAYER_STORAGE_KEY) {
        setLayerStateLocal(getLayerState());
      }
      if (e.key === SETTINGS_STORAGE_KEY) {
        setAutoPlayLocal(getVoiceSetting('tts_auto_play', false));
        setAutoSendLocal(getVoiceSetting('stt_auto_send', false));
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
    // On mobile, switching modes resets the session to avoid stale model state
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

  const toggleAutoPlay = useCallback(() => {
    const newVal = !getVoiceSetting('tts_auto_play', false);
    setVoiceSetting('tts_auto_play', newVal);
    setAutoPlayLocal(newVal);
    // Stop TTS if turning off; TTS stop is a side-effect handled externally via event
    if (!newVal) {
      window.dispatchEvent(new CustomEvent('tts:stop'));
    }
  }, []);

  const toggleAutoSend = useCallback(() => {
    const newVal = !getVoiceSetting('stt_auto_send', false);
    setVoiceSetting('stt_auto_send', newVal);
    setAutoSendLocal(newVal);
  }, []);

  return (
    <header className="top-bar flex items-center gap-2 px-3 h-12 border-b border-border bg-background shrink-0">
      {/* Mobile hamburger */}
      <button
        className="top-bar-menu-btn p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
        onClick={onMenuClick}
        aria-label="Toggle sidebar"
      >
        <Menu className="w-5 h-5" />
      </button>

      {/* Project name */}
      <span className="top-bar-project-name text-sm font-medium truncate max-w-[160px]">
        {projectName}
      </span>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Mode pill: Fast / Deep / Analyzer */}
      <div className="top-bar-mode-pill flex items-center rounded-full border border-border bg-muted/50 p-0.5 gap-0.5">
        <button
          className={cn(
            'top-bar-mode-btn px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
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
            'top-bar-mode-btn px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
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
            'top-bar-mode-btn px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
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

      {/* Auto-send voice button */}
      <button
        className={cn(
          'top-bar-voice-btn p-1.5 rounded transition-colors text-sm',
          autoSend
            ? 'bg-primary/20 text-primary'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'
        )}
        title="Auto-send voice"
        onClick={toggleAutoSend}
      >
        📤
      </button>

      {/* Auto-play responses button */}
      <button
        className={cn(
          'top-bar-voice-btn p-1.5 rounded transition-colors text-sm',
          autoPlay
            ? 'bg-primary/20 text-primary'
            : 'text-muted-foreground hover:text-foreground hover:bg-muted'
        )}
        title="Auto-play responses"
        onClick={toggleAutoPlay}
      >
        🔊
      </button>
    </header>
  );
}
