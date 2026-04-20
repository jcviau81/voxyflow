/**
 * PersonalityPanel — Names, language, tone, warmth, and custom instructions.
 *
 * Reads/writes personality settings via GET/PUT /api/settings (personality key).
 */

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { cn } from '../../lib/utils';
import { authFetch } from '../../lib/authClient';

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
  user_name?: string;
  assistant_name?: string;
  [key: string]: unknown;
}

const DEFAULTS: PersonalitySettings = {
  bot_name: 'Voxy',
  preferred_language: 'auto',
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

async function fetchFile(filename: string): Promise<string> {
  const res = await fetch(`/api/settings/personality/files/${filename}`);
  const data = await res.json() as { content: string };
  return data.content ?? '';
}

async function saveFile(filename: string, content: string): Promise<void> {
  await authFetch(`/api/settings/personality/files/${filename}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
}

async function resetFile(filename: string): Promise<string> {
  await authFetch(`/api/settings/personality/files/${filename}/reset`, { method: 'POST' });
  return fetchFile(filename);
}

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
  const [userName, setUserName] = useState('');
  const [botName, setBotName] = useState(ps.bot_name);
  const [language, setLanguage] = useState(ps.preferred_language);
  const [tone, setTone] = useState(ps.tone);
  const [warmth, setWarmth] = useState(ps.warmth);
  const [customInstructions, setCustomInstructions] = useState(ps.custom_instructions);
  const [saved, setSaved] = useState(false);

  // File editors
  const [userMd, setUserMd] = useState('');
  const [identityMd, setIdentityMd] = useState('');
  const [fileSaved, setFileSaved] = useState<string | null>(null);
  const [fileSection, setFileSection] = useState<'user' | 'identity' | null>(null);

  // Sync from server
  useEffect(() => {
    if (settings) {
      const p = { ...DEFAULTS, ...settings.personality };
      setUserName(settings.user_name ?? '');
      setBotName(p.bot_name);
      setLanguage(p.preferred_language);
      setTone(p.tone);
      setWarmth(p.warmth);
      setCustomInstructions(p.custom_instructions);
    }
  }, [settings]);

  // Load file contents when section opens
  useEffect(() => {
    if (fileSection === 'user' && !userMd) {
      void fetchFile('USER.md').then(setUserMd);
    } else if (fileSection === 'identity' && !identityMd) {
      void fetchFile('IDENTITY.md').then(setIdentityMd);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileSection]);

  async function handleFileSave(filename: string, content: string) {
    await saveFile(filename, content);
    setFileSaved(filename);
    setTimeout(() => setFileSaved(null), 2000);
  }

  async function handleFileReset(filename: string, setter: (c: string) => void) {
    const content = await resetFile(filename);
    setter(content);
    setFileSaved(filename + '_reset');
    setTimeout(() => setFileSaved(null), 2000);
  }

  const saveMutation = useMutation({
    mutationFn: async (updates: { personality: Partial<PersonalitySettings>; user_name: string; assistant_name: string }) => {
      const current = await (await fetch('/api/settings')).json();
      const merged = {
        ...current,
        user_name: updates.user_name,
        assistant_name: updates.assistant_name,
        personality: { ...current.personality, ...updates.personality },
      };
      await authFetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(merged),
      });
      return merged;
    },
    onSuccess: (merged) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      // Sync to localStorage so MessageBubble picks up the new names immediately
      try {
        const stored = JSON.parse(localStorage.getItem('voxyflow_settings') || '{}');
        stored.user_name = merged.user_name;
        stored.assistant_name = merged.assistant_name;
        if (!stored.personality) stored.personality = {};
        stored.personality.bot_name = merged.personality?.bot_name;
        localStorage.setItem('voxyflow_settings', JSON.stringify(stored));
      } catch { /* ignore */ }
    },
  });

  const handleSave = () => {
    saveMutation.mutate({
      personality: {
        bot_name: botName,
        preferred_language: language,
        tone,
        warmth,
        custom_instructions: customInstructions,
      },
      user_name: userName,
      assistant_name: botName,
    });
  };

  return (
    <div className="settings-panel-content p-6 space-y-6">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Personality</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Configure names and how your assistant communicates with you.
        </p>
      </div>

      {/* Names */}
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Your name</label>
          <input
            type="text"
            value={userName}
            onChange={(e) => setUserName(e.target.value)}
            placeholder="What should I call you?"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Assistant name</label>
          <input
            type="text"
            value={botName}
            onChange={(e) => setBotName(e.target.value)}
            placeholder="Voxy"
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
      </div>

      {/* Language */}
      <div className="space-y-2">
        <label className="text-xs font-medium text-muted-foreground">Preferred Response Language</label>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
        >
          <option value="auto">Auto — match the user's language</option>
          <option value="en">English</option>
          <option value="fr">Français</option>
          <option value="es">Español</option>
          <option value="de">Deutsch</option>
          <option value="it">Italiano</option>
          <option value="pt">Português</option>
          <option value="nl">Nederlands</option>
          <option value="ja">日本語</option>
          <option value="zh">中文</option>
          <option value="ko">한국어</option>
          <option value="ar">العربية</option>
        </select>
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
          placeholder="Add any custom instructions for your assistant..."
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

      {/* ── File editors ──────────────────────────────────────────────── */}
      <div className="border-t border-border pt-5 space-y-3">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Profile Files</p>

        {/* USER.md */}
        <div className="rounded-md border border-border overflow-hidden">
          <button
            type="button"
            onClick={() => setFileSection(fileSection === 'user' ? null : 'user')}
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-accent/50 transition-colors"
          >
            <span>📋 USER.md — Your profile</span>
            <span className="text-muted-foreground text-xs">{fileSection === 'user' ? '▲' : '▼'}</span>
          </button>
          {fileSection === 'user' && (
            <div className="p-3 space-y-2 border-t border-border bg-muted/20">
              <p className="text-xs text-muted-foreground">Describes you to the assistant. Editable — the assistant may also update this over time.</p>
              <textarea
                value={userMd}
                onChange={(e) => setUserMd(e.target.value)}
                rows={10}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void handleFileSave('USER.md', userMd)}
                  className={cn(
                    'px-3 py-1.5 text-xs font-medium rounded-md border transition-colors',
                    fileSaved === 'USER.md'
                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                      : 'bg-primary/20 text-primary border-primary/40 hover:bg-primary/30'
                  )}
                >
                  {fileSaved === 'USER.md' ? 'Saved!' : 'Save'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleFileReset('USER.md', setUserMd)}
                  className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >
                  {fileSaved === 'USER.md_reset' ? 'Reset!' : 'Reset to default'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* IDENTITY.md */}
        <div className="rounded-md border border-border overflow-hidden">
          <button
            type="button"
            onClick={() => setFileSection(fileSection === 'identity' ? null : 'identity')}
            className="w-full flex items-center justify-between px-4 py-2.5 text-sm font-medium hover:bg-accent/50 transition-colors"
          >
            <span>🤖 IDENTITY.md — Assistant identity</span>
            <span className="text-muted-foreground text-xs">{fileSection === 'identity' ? '▲' : '▼'}</span>
          </button>
          {fileSection === 'identity' && (
            <div className="p-3 space-y-2 border-t border-border bg-muted/20">
              <p className="text-xs text-muted-foreground">Defines your assistant's name, emoji, and vibe. Name field is synced with the assistant name above.</p>
              <textarea
                value={identityMd}
                onChange={(e) => setIdentityMd(e.target.value)}
                rows={8}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-y"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void handleFileSave('IDENTITY.md', identityMd)}
                  className={cn(
                    'px-3 py-1.5 text-xs font-medium rounded-md border transition-colors',
                    fileSaved === 'IDENTITY.md'
                      ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                      : 'bg-primary/20 text-primary border-primary/40 hover:bg-primary/30'
                  )}
                >
                  {fileSaved === 'IDENTITY.md' ? 'Saved!' : 'Save'}
                </button>
                <button
                  type="button"
                  onClick={() => void handleFileReset('IDENTITY.md', setIdentityMd)}
                  className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                >
                  {fileSaved === 'IDENTITY.md_reset' ? 'Reset!' : 'Reset to default'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
