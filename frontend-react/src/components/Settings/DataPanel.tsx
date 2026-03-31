/**
 * DataPanel — Data management settings.
 *
 * Mirrors renderDataSection() from frontend/src/components/Settings/SettingsPage.ts
 * (lines 1063–1076).
 *
 * Features:
 *  - Clear all local data (clears localStorage + reloads)
 *  - Export data (future — placeholder)
 */

import { useState } from 'react';
import { Database, Trash2 } from 'lucide-react';

export function DataPanel() {
  const [confirming, setConfirming] = useState(false);

  const handleClear = () => {
    if (confirming) {
      localStorage.clear();
      location.reload();
    } else {
      setConfirming(true);
      // Auto-cancel confirmation after 4s
      setTimeout(() => setConfirming(false), 4000);
    }
  };

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-data">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <Database size={16} />
        Data
      </h3>

      {/* Clear all data */}
      <div className="setting-row flex items-center justify-between gap-4">
        <div className="setting-info space-y-0.5">
          <div className="setting-label text-sm font-medium">Clear All Data</div>
          <div className="setting-description text-xs text-muted-foreground">
            Delete all local data and reload. This cannot be undone.
          </div>
        </div>
        <button
          type="button"
          onClick={handleClear}
          className={`h-8 px-4 text-sm rounded-md border flex items-center gap-1.5 transition-colors ${
            confirming
              ? 'bg-destructive text-destructive-foreground border-destructive hover:bg-destructive/90'
              : 'border-destructive text-destructive hover:bg-destructive/10'
          }`}
        >
          <Trash2 size={14} />
          {confirming ? 'Click again to confirm' : 'Clear All'}
        </button>
      </div>
    </div>
  );
}
