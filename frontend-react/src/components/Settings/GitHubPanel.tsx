/**
 * GitHubPanel — GitHub integration settings.
 *
 * Mirrors renderGitHubSection() + checkGitHubStatus() + saveGitHubToken()
 * from frontend/src/components/Settings/SettingsPage.ts (lines 708–1608).
 *
 * Features:
 *  - Auto-check GitHub status on mount (gh CLI + PAT)
 *  - Save Personal Access Token (POST /api/github/token)
 *  - Test connection button
 */

import { useState, useEffect, useRef } from 'react';
import { GitBranch, CheckCircle, XCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { useToastStore } from '../../stores/useToastStore';

// ── Types ──────────────────────────────────────────────────────────────────

interface GitHubStatus {
  gh_installed: boolean;
  gh_authenticated: boolean;
  token_configured: boolean;
  username?: string;
  method?: 'pat' | 'gh_cli';
}

type CheckState = 'idle' | 'loading' | 'ok' | 'warning' | 'error';

// ── Sub-components ─────────────────────────────────────────────────────────

function StatusBadge({ state, label }: { state: CheckState; label: string }) {
  if (state === 'loading') {
    return (
      <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Loader2 size={14} className="animate-spin" />
        {label}
      </span>
    );
  }
  if (state === 'ok') {
    return (
      <span className="flex items-center gap-1.5 text-sm text-green-500">
        <CheckCircle size={14} />
        {label}
      </span>
    );
  }
  if (state === 'warning') {
    return (
      <span className="flex items-center gap-1.5 text-sm text-yellow-500">
        <AlertTriangle size={14} />
        {label}
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-sm text-destructive">
      <XCircle size={14} />
      {label}
    </span>
  );
}

// ── GitHubPanel ────────────────────────────────────────────────────────────

export function GitHubPanel() {
  const { showToast } = useToastStore();

  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [connectionState, setConnectionState] = useState<CheckState>('loading');
  const [connectionLabel, setConnectionLabel] = useState('Checking GitHub status…');
  const [cliState, setCliState] = useState<CheckState>('loading');
  const [cliLabel, setCliLabel] = useState('Checking…');
  const [testState, setTestState] = useState<CheckState>('idle');
  const [testLabel, setTestLabel] = useState('');
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const tokenRef = useRef<HTMLInputElement>(null);

  const checkStatus = async (showResult: boolean) => {
    try {
      const response = await fetch('/api/github/status');
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data: GitHubStatus = await response.json();
      setStatus(data);

      // Connection banner
      if (data.gh_authenticated) {
        const via = data.method === 'pat' ? 'Personal Access Token' : 'GitHub CLI';
        setConnectionState('ok');
        setConnectionLabel(`Connected as @${data.username ?? 'unknown'} via ${via}`);
      } else if (data.token_configured) {
        setConnectionState('warning');
        setConnectionLabel('Token configured but authentication failed');
      } else {
        setConnectionState('error');
        setConnectionLabel('Not connected — configure below');
      }

      // CLI badge
      if (!data.gh_installed) {
        setCliState('error');
        setCliLabel('Not installed');
      } else if (data.gh_authenticated && data.method === 'gh_cli') {
        setCliState('ok');
        setCliLabel(`Authenticated as @${data.username}`);
      } else {
        setCliState('warning');
        setCliLabel('Installed but not authenticated');
      }

      if (showResult) {
        if (data.gh_authenticated) {
          setTestState('ok');
          setTestLabel('Connection successful!');
          showToast(`GitHub connected as @${data.username}`, 'success', 3000);
        } else {
          setTestState('error');
          setTestLabel('Not authenticated');
          showToast('GitHub not connected', 'error', 3000);
        }
      }
    } catch (e) {
      setConnectionState('error');
      setConnectionLabel('Failed to check status');
      setCliState('error');
      setCliLabel('Unknown');
      if (showResult) {
        setTestState('error');
        setTestLabel('Connection check failed');
        showToast('Failed to check GitHub status', 'error', 3000);
      }
    }
  };

  // Auto-check on mount
  useEffect(() => {
    checkStatus(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTest = async () => {
    setTesting(true);
    setTestState('loading');
    setTestLabel('Testing…');
    await checkStatus(true);
    setTesting(false);
  };

  const handleSaveToken = async () => {
    const token = tokenRef.current?.value.trim() ?? '';
    if (!token) {
      showToast('Enter a token first', 'error', 2000);
      return;
    }
    if (!token.startsWith('ghp_') && !token.startsWith('github_pat_')) {
      showToast('Token must start with ghp_ or github_pat_', 'error', 3000);
      return;
    }

    setSaving(true);
    try {
      const response = await fetch('/api/github/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token }),
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Save failed' }));
        throw new Error(err.detail ?? 'Save failed');
      }
      if (tokenRef.current) tokenRef.current.value = '';
      showToast('Token saved! Testing connection…', 'success', 2000);
      setTimeout(() => checkStatus(true), 500);
    } catch (e) {
      showToast(`Failed to save token: ${e}`, 'error', 4000);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-panel-content p-6 space-y-6" data-testid="settings-github">
      <h3 className="flex items-center gap-2 text-base font-semibold">
        <GitBranch size={16} />
        GitHub Integration
      </h3>

      {/* Connection status banner */}
      <div className="rounded-md border border-border bg-muted/30 px-4 py-3">
        <StatusBadge state={connectionState} label={connectionLabel} />
      </div>

      {/* Option 1: GitHub CLI */}
      <div className="setting-row flex items-center justify-between gap-4">
        <div className="setting-info space-y-0.5">
          <div className="setting-label text-sm font-medium">GitHub CLI (gh)</div>
          <div className="setting-description text-xs text-muted-foreground">
            Recommended: uses your existing gh authentication
          </div>
        </div>
        <StatusBadge state={cliState} label={cliLabel} />
      </div>

      {/* Option 2: Personal Access Token */}
      <div className="space-y-2">
        <div className="setting-info space-y-0.5">
          <div className="setting-label text-sm font-medium">Personal Access Token (alternative)</div>
          <div className="setting-description text-xs text-muted-foreground">
            Create at{' '}
            <a
              href="https://github.com/settings/tokens"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-foreground"
            >
              github.com/settings/tokens
            </a>
          </div>
        </div>
        <div className="flex gap-2">
          <input
            ref={tokenRef}
            type="password"
            className="setting-input flex-1 h-8 px-3 text-sm rounded-md border border-input bg-background"
            placeholder="ghp_…"
          />
          <button
            type="button"
            onClick={handleSaveToken}
            disabled={saving}
            className="btn-secondary h-8 px-3 text-sm rounded-md border border-border hover:bg-accent disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : 'Save Token'}
          </button>
        </div>
      </div>

      {/* Test connection */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleTest}
          disabled={testing}
          data-testid="github-test-btn"
          className="btn-primary h-8 px-4 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 flex items-center gap-1.5"
        >
          {testing && <Loader2 size={14} className="animate-spin" />}
          Test Connection
        </button>
        {testState !== 'idle' && <StatusBadge state={testState} label={testLabel} />}
      </div>

      {/* Repository info if connected */}
      {status?.gh_authenticated && (
        <div className="text-xs text-muted-foreground">
          Authenticated as <strong>@{status.username}</strong> via{' '}
          {status.method === 'pat' ? 'Personal Access Token' : 'GitHub CLI'}
        </div>
      )}
    </div>
  );
}
