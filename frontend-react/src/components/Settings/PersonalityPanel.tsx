/**
 * PersonalityPanel — Language, tone, warmth, and custom instructions.
 *
 * Reads/writes personality settings via GET/PUT /api/settings (personality key).
 */

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '../../lib/utils';

// ── Types ──────────────────────────────────────────────────────────────────

interface PersonalitySettings {
  bot_name: string;
  preferred_language: string;
  tone: string;
  warmth: string;
  custom_instructions: string;
  environment_notes: string;
}

interface AppSettings {
  personality?: Partial<PersonalitySettings>;
  [key: string]: unknown;
}

const DEFAULTS: PersonalitySettings = {
  bot_name: 'Voxy',
  preferred_language: 'both',
  tone: 'casual',
  warmth: 'warm',
  custom_instructions: '',
  environment_notes: '',
};

// ── Pill selector ──────────────────────────────────────────────────────────

interface PillGroupProps {
  options: Array<{ value: string; label: string }>;
  value: string;
  onChange: (value: string) => void;
}

function PillGroup({ options, value, onChange }: PillGroupProps) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            'px-3 py-1 text-xs rounded-md border transition-colors',
            'border-border hover:border-primary/50 hover:text-foreground',
            value === opt.value
              ? 'bg-primary/20 text-primary border-primary/40 font-medium'
              : 'bg-transparent text-muted-foreground',
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────────────────────

export function PersonalityPanel() {
  const queryClient = useQueryClient();

  const { data: settings } = useQuery<AppSettings>({
    queryKey: ['settings'],
    queryFn: async () => {
      const res = await fetch('/api/settings');
      return res.json();
    },
  });

  const ps = { ...DEFAULTS, ...settings?.personality };
  const [language, setLanguage] = useState(ps.preferred_language);
  const [tone, setTone] = useState(ps.tone);
  const [warmth, setWarmth] = useState(ps.warmth);
  const [customInstructions, setCustomInstructions] = useState(ps.custom_instructions);
  const [saved, setSaved] = useState(false);

  // Sync from server
  useEffect(() => {
    if (settings?.personality) {
      const p = { ...DEFAULTS, ...settings.personality };
      setLanguage(p.preferred_language);
      setTone(p.tone);
      setWarmth(p.warmth);
      setCustomInstructions(p.custom_instructions);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: async (updates: Partial<PersonalitySettings>) => {
      const current = await (await fetch('/api/settings')).json();
      const merged = {
        ...current,
        personality: { ...current.personality, ...updates },
      };
      await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(merged),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const handleSave = () => {
    saveMutation.mutate({
      preferred_language: language,
      tone,
      warmth,
      custom_instructions: customInstructions,
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Personality</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Configure how Voxy communicates with you.
        </p>
      </div>

      {/* Language */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Response Language</label>
        <PillGroup
          options={[
            { value: 'en', label: 'English' },
            { value: 'fr', label: 'Francais' },
            { value: 'both', label: 'Auto (match user)' },
          ]}
          value={language}
          onChange={setLanguage}
        />
      </div>

      {/* Tone */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Tone</label>
        <PillGroup
          options={[
            { value: 'casual', label: 'Casual' },
            { value: 'balanced', label: 'Balanced' },
            { value: 'formal', label: 'Formal' },
          ]}
          value={tone}
          onChange={setTone}
        />
      </div>

      {/* Warmth */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Warmth</label>
        <PillGroup
          options={[
            { value: 'cold', label: 'Professional' },
            { value: 'warm', label: 'Warm' },
            { value: 'hot', label: 'Expressive' },
          ]}
          value={warmth}
          onChange={setWarmth}
        />
      </div>

      {/* Custom Instructions */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Custom Instructions</label>
        <textarea
          value={customInstructions}
          onChange={(e) => setCustomInstructions(e.target.value)}
          placeholder="Add any custom instructions for Voxy..."
          rows={4}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y"
        />
      </div>

      {/* Save */}
      <button
        type="button"
        onClick={handleSave}
        disabled={saveMutation.isPending}
        className={cn(
          'px-4 py-2 text-sm font-medium rounded-md transition-colors',
          saved
            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
            : 'bg-primary/20 text-primary border border-primary/40 hover:bg-primary/30',
          saveMutation.isPending && 'opacity-50',
        )}
      >
        {saved ? 'Saved!' : saveMutation.isPending ? 'Saving...' : 'Save'}
      </button>
    </div>
  );
}
