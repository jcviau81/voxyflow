/**
 * ProjectForm — React port of frontend/src/components/Projects/ProjectForm.ts
 *
 * Handles create and edit modes with:
 *   - Template picker (create mode only)
 *   - Name, description fields (validated via react-hook-form + zod)
 *   - Emoji selector, color palette
 *   - GitHub repo connect/create
 *   - Local path + tech stack detect
 *   - Inherit Main Context toggle (edit, non-system)
 *   - Status select (edit mode)
 */

import { useState, useEffect, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { cn } from '../../lib/utils';
import {
  useCreateProject,
  useUpdateProject,
  useProjectTemplates,
  useArchiveProject,
  useCreateProjectFromTemplate,
} from '../../hooks/api/useProjects';
import type { Project, GitHubRepoInfo, ProjectTemplate, TechDetectResult } from '../../types';

// ─── Constants ────────────────────────────────────────────────────────────────

const PROJECT_EMOJIS = ['🎮', '🎙', '🌐', '📱', '🔧', '🎨', '📊', '🚀', '💡', '🔥', '📁', '🎯', '🛠️', '🧪', '📦', '🌟'];
const DEFAULT_EMOJI = '📁';

const COLOR_PALETTE = [
  '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4',
  '#feca57', '#ff9ff3', '#54a0ff', '#c47eff',
];

// ─── Schema ───────────────────────────────────────────────────────────────────

const schema = z.object({
  name: z.string().min(1, 'Project name is required').max(100, 'Max 100 characters'),
  description: z.string().max(500, 'Max 500 characters').optional(),
});

type FormValues = z.infer<typeof schema>;

// ─── Props ────────────────────────────────────────────────────────────────────

interface ProjectFormProps {
  mode: 'create' | 'edit';
  project?: Project;
  prefillTitle?: string;
  onClose: () => void;
}

// ─── GitHub status variants ───────────────────────────────────────────────────

type GitHubStatus =
  | { type: 'idle' }
  | { type: 'loading' }
  | { type: 'connected'; info: GitHubRepoInfo }
  | { type: 'error'; message: string }
  | { type: 'create-offer'; repoName: string };

// ─── Component ────────────────────────────────────────────────────────────────

export function ProjectForm({ mode, project, prefillTitle, onClose }: ProjectFormProps) {
  // ── Form ──────────────────────────────────────────────────────────────────
  const {
    register,
    handleSubmit,
    formState: { errors },
    getValues,
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: project?.name ?? prefillTitle ?? '',
      description: project?.description ?? '',
    },
  });

  // ── Selectors ─────────────────────────────────────────────────────────────
  const [selectedEmoji, setSelectedEmoji] = useState(project?.emoji ?? DEFAULT_EMOJI);
  const [selectedColor, setSelectedColor] = useState(project?.color ?? '');
  const [selectedStatus, setSelectedStatus] = useState<'active' | 'archived'>(
    project?.archived ? 'archived' : 'active'
  );
  const [inheritMainContext, setInheritMainContext] = useState(
    project?.inheritMainContext !== false
  );

  // ── Templates ─────────────────────────────────────────────────────────────
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);
  const { data: templates = [] } = useProjectTemplates();

  // ── GitHub ─────────────────────────────────────────────────────────────────
  const [githubInput, setGithubInput] = useState(project?.githubRepo ?? '');
  const [githubStatus, setGithubStatus] = useState<GitHubStatus>(() => {
    if (project?.githubRepo && project?.githubUrl) {
      return {
        type: 'connected',
        info: {
          valid: true,
          full_name: project.githubRepo,
          description: '',
          default_branch: project.githubBranch ?? 'main',
          language: project.githubLanguage ?? null,
          stars: 0,
          private: false,
          html_url: project.githubUrl,
          clone_url: '',
          updated_at: '',
        },
      };
    }
    return { type: 'idle' };
  });
  const [githubSetupOk, setGithubSetupOk] = useState(true);

  // ── Local path / tech stack ─────────────────────────────────────────────────
  const [localPath, setLocalPath] = useState(project?.localPath ?? '');
  const [techStack, setTechStack] = useState<TechDetectResult | null>(project?.techStack ?? null);
  const [detecting, setDetecting] = useState(false);

  // ── Mutations ──────────────────────────────────────────────────────────────
  const createProject = useCreateProject();
  const updateProject = useUpdateProject();
  const archiveProject = useArchiveProject();
  const createFromTemplate = useCreateProjectFromTemplate();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const nameRef = useRef<HTMLInputElement | null>(null);

  // ── Focus name on mount ────────────────────────────────────────────────────
  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // ── Check GitHub setup ─────────────────────────────────────────────────────
  useEffect(() => {
    fetch('/api/github/status')
      .then((r) => r.json())
      .then((d: { gh_authenticated: boolean }) => setGithubSetupOk(d.gh_authenticated))
      .catch(() => { /* silent */ });
  }, []);

  // ── Template selection ─────────────────────────────────────────────────────
  function selectTemplate(tpl: ProjectTemplate | null) {
    setSelectedTemplateId(tpl?.id ?? null);
    if (tpl) {
      setSelectedEmoji(tpl.emoji);
      setSelectedColor(tpl.color);
    }
  }

  // ── GitHub helpers ─────────────────────────────────────────────────────────
  function parseGitHubInput(input: string): { owner: string; repo: string } | null {
    let value = input.trim().replace(/\.git$/, '');
    const urlMatch = value.match(/github\.com\/([^/]+)\/([^/]+)/);
    if (urlMatch) return { owner: urlMatch[1], repo: urlMatch[2] };
    const shortMatch = value.match(/^([a-zA-Z0-9_.-]+)\/([a-zA-Z0-9_.-]+)$/);
    if (shortMatch) return { owner: shortMatch[1], repo: shortMatch[2] };
    return null;
  }

  function formatTimeAgo(isoDate: string): string {
    try {
      const diff = Date.now() - new Date(isoDate).getTime();
      const minutes = Math.floor(diff / 60000);
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      return `${Math.floor(hours / 24)}d ago`;
    } catch {
      return '';
    }
  }

  async function handleGitHubConnect() {
    const parsed = parseGitHubInput(githubInput);
    if (!parsed) {
      setGithubStatus({ type: 'error', message: 'Invalid format. Use owner/repo or full GitHub URL' });
      return;
    }
    setGithubStatus({ type: 'loading' });
    try {
      const res = await fetch(`/api/github/validate/${parsed.owner}/${parsed.repo}`);
      if (!res.ok) {
        if (res.status === 404) {
          setGithubStatus({ type: 'create-offer', repoName: parsed.repo });
        } else {
          const err = await res.json().catch(() => ({ detail: 'Repository not found' })) as { detail?: string };
          setGithubStatus({ type: 'error', message: err.detail ?? 'Repository not found' });
        }
        return;
      }
      const info = await res.json() as GitHubRepoInfo;
      setGithubStatus({ type: 'connected', info });
    } catch {
      setGithubStatus({ type: 'error', message: 'Failed to connect to GitHub API. Check Settings → GitHub.' });
    }
  }

  async function handleGitHubCreate(repoName: string) {
    setGithubStatus({ type: 'loading' });
    try {
      const description = getValues('description') ?? '';
      const res = await fetch('/api/github/create-repo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: repoName, description, private: true }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to create repository' })) as { detail?: string };
        setGithubStatus({ type: 'error', message: err.detail ?? 'Failed to create repository' });
        return;
      }
      const info = await res.json() as GitHubRepoInfo;
      setGithubStatus({ type: 'connected', info });
    } catch {
      setGithubStatus({ type: 'error', message: 'Failed to create repository. Check Settings → GitHub.' });
    }
  }

  // ── Tech stack detect ──────────────────────────────────────────────────────
  async function handleTechDetect() {
    const path = localPath.trim();
    if (!path) return;
    setDetecting(true);
    try {
      const res = await fetch('/api/tech/detect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) return;
      const data = await res.json() as TechDetectResult;
      setTechStack(data);
    } catch {
      // silent
    } finally {
      setDetecting(false);
    }
  }

  // ── Submit ─────────────────────────────────────────────────────────────────
  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    const githubConnected = githubStatus.type === 'connected' ? githubStatus.info : null;
    try {
    if (mode === 'create') {
      if (selectedTemplateId) {
        await createFromTemplate.mutateAsync({
          templateId: selectedTemplateId,
          data: {
            title: values.name,
            description: values.description,
            emoji: selectedEmoji,
            color: selectedColor || undefined,
          },
        });
      } else {
        await createProject.mutateAsync({
          name: values.name,
          description: values.description,
          emoji: selectedEmoji,
          color: selectedColor || undefined,
          localPath: localPath || undefined,
          githubRepo: githubConnected?.full_name,
          githubUrl: githubConnected?.html_url,
          githubBranch: githubConnected?.default_branch,
          githubLanguage: githubConnected?.language ?? undefined,
        } as Parameters<typeof createProject.mutateAsync>[0]);
      }
    } else if (project) {
      await updateProject.mutateAsync({
        id: project.id,
        updates: {
          name: values.name,
          description: values.description,
          emoji: selectedEmoji,
          color: selectedColor || undefined,
          localPath: localPath || undefined,
          githubRepo: githubConnected?.full_name,
          githubUrl: githubConnected?.html_url,
          githubBranch: githubConnected?.default_branch,
          githubLanguage: githubConnected?.language ?? undefined,
          inheritMainContext: project.isSystem ? undefined : inheritMainContext,
          ...(selectedStatus === 'archived' && !project.archived ? {} : {}),
        },
      });
      // Handle status change separately
      if (selectedStatus === 'archived' && !project.archived) {
        await archiveProject.mutateAsync({ id: project.id });
      } else if (selectedStatus === 'active' && project.archived) {
        await archiveProject.mutateAsync({ id: project.id, restore: true });
      }
    }
    onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'An error occurred');
    }
  }

  async function handleArchiveToggle() {
    if (!project) return;
    await archiveProject.mutateAsync({ id: project.id, restore: project.archived });
    onClose();
  }

  const isPending = createProject.isPending || updateProject.isPending || createFromTemplate.isPending;

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="project-form-wrapper fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        className="project-form relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto p-6"
        data-testid="project-form"
      >
        <h2 className="text-xl font-semibold text-foreground mb-5">
          {mode === 'create' ? 'Create Project' : 'Edit Project'}
        </h2>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">

          {/* ── Template picker (create only) ── */}
          {mode === 'create' && (
            <div className="template-section">
              <div className="text-sm font-medium text-muted-foreground mb-2">✨ Start from a template</div>
              <div className="template-track flex gap-2 overflow-x-auto pb-2">
                <button
                  type="button"
                  onClick={() => selectTemplate(null)}
                  className={cn(
                    'template-card flex-shrink-0 flex flex-col items-center gap-1 p-3 rounded-lg border text-center w-24 transition-colors',
                    selectedTemplateId === null
                      ? 'border-primary bg-primary/10 text-primary'
                      : 'border-border hover:border-primary/50 text-muted-foreground hover:text-foreground'
                  )}
                >
                  <span className="text-xl">🚫</span>
                  <span className="text-xs font-medium">Blank</span>
                  <span className="text-[10px] opacity-70">Start from scratch</span>
                </button>
                {templates.map((tpl) => (
                  <button
                    key={tpl.id}
                    type="button"
                    onClick={() => selectTemplate(tpl as ProjectTemplate)}
                    style={{ '--tpl-color': tpl.color } as React.CSSProperties}
                    className={cn(
                      'template-card flex-shrink-0 flex flex-col items-center gap-1 p-3 rounded-lg border text-center w-24 transition-colors',
                      selectedTemplateId === tpl.id
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:border-primary/50 text-muted-foreground hover:text-foreground'
                    )}
                  >
                    <span className="text-xl">{tpl.emoji}</span>
                    <span className="text-xs font-medium truncate w-full">{tpl.name}</span>
                    <span className="text-[10px] opacity-70 line-clamp-2">{tpl.description}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* ── Name ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">Project Name *</label>
            <input
              {...register('name')}
              ref={(el) => {
                (register('name') as { ref: (el: HTMLInputElement | null) => void }).ref(el);
                nameRef.current = el;
              }}
              type="text"
              placeholder="My Awesome Project"
              maxLength={100}
              data-testid="project-name-input"
              className={cn(
                'form-input w-full px-3 py-2 rounded-md border bg-background text-foreground text-sm',
                'placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50',
                errors.name ? 'border-destructive' : 'border-border'
              )}
            />
            {errors.name && (
              <p className="form-error text-xs text-destructive" data-testid="project-name-error">
                {errors.name.message}
              </p>
            )}
          </div>

          {/* ── Description ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">Description</label>
            <textarea
              {...register('description')}
              placeholder="What's this project about?"
              maxLength={500}
              rows={3}
              data-testid="project-description-input"
              className={cn(
                'form-textarea w-full px-3 py-2 rounded-md border bg-background text-foreground text-sm resize-none',
                'placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50',
                errors.description ? 'border-destructive' : 'border-border'
              )}
            />
            {errors.description && (
              <p className="form-error text-xs text-destructive">{errors.description.message}</p>
            )}
          </div>

          {/* ── Emoji selector ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">Emoji</label>
            <div className="emoji-selector flex flex-wrap gap-1">
              {PROJECT_EMOJIS.map((emoji) => (
                <button
                  key={emoji}
                  type="button"
                  data-testid={`emoji-option-${emoji}`}
                  onClick={() => setSelectedEmoji(emoji)}
                  className={cn(
                    'emoji-option w-9 h-9 rounded-md text-lg flex items-center justify-center border transition-colors',
                    selectedEmoji === emoji
                      ? 'border-primary bg-primary/10'
                      : 'border-transparent hover:border-border hover:bg-accent'
                  )}
                >
                  {emoji}
                </button>
              ))}
            </div>
          </div>

          {/* ── Color palette ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">Color</label>
            <div className="color-palette flex gap-2 flex-wrap">
              {COLOR_PALETTE.map((color) => (
                <button
                  key={color}
                  type="button"
                  data-testid={`color-option-${color.replace('#', '')}`}
                  data-color={color}
                  onClick={() => setSelectedColor(color)}
                  style={{ background: color }}
                  className={cn(
                    'color-option w-8 h-8 rounded-full border-2 transition-transform',
                    selectedColor === color
                      ? 'border-foreground scale-110'
                      : 'border-transparent hover:scale-105'
                  )}
                />
              ))}
              {selectedColor && (
                <button
                  type="button"
                  onClick={() => setSelectedColor('')}
                  className="w-8 h-8 rounded-full border-2 border-border flex items-center justify-center text-muted-foreground hover:text-foreground text-xs"
                  title="Clear color"
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          {/* ── GitHub repo ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">🔗 GitHub Repository</label>
            {!githubSetupOk && (
              <div className="text-xs text-yellow-500">
                ⚠️ GitHub not configured.{' '}
                <button
                  type="button"
                  className="underline text-primary"
                  onClick={() => { onClose(); window.location.href = '/settings'; }}
                >
                  Go to Settings → GitHub
                </button>{' '}
                to connect.
              </div>
            )}
            <div className="github-input-row flex gap-2">
              <input
                type="text"
                value={githubInput}
                onChange={(e) => setGithubInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void handleGitHubConnect(); } }}
                placeholder="owner/repo or https://github.com/owner/repo"
                data-testid="project-github-input"
                className="form-input flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              <button
                type="button"
                data-testid="github-connect-btn"
                onClick={() => void handleGitHubConnect()}
                className="btn-secondary px-3 py-2 rounded-md border border-border text-sm hover:bg-accent transition-colors"
              >
                Connect
              </button>
            </div>

            {/* GitHub status */}
            <div className="github-status mt-1" data-testid="github-status">
              {githubStatus.type === 'loading' && (
                <span className="text-xs text-muted-foreground">⏳ Validating...</span>
              )}
              {githubStatus.type === 'error' && (
                <span className="text-xs text-destructive">❌ {githubStatus.message}</span>
              )}
              {githubStatus.type === 'create-offer' && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">Repository not found.</span>
                  <button
                    type="button"
                    data-testid="github-create-btn"
                    onClick={() => void handleGitHubCreate(githubStatus.repoName)}
                    className="btn-secondary px-2 py-1 rounded border border-border hover:bg-accent"
                  >
                    Create on GitHub (private)
                  </button>
                </div>
              )}
              {githubStatus.type === 'connected' && (() => {
                const { info } = githubStatus;
                const meta = [
                  info.language,
                  info.default_branch,
                  `⭐ ${info.stars}`,
                  info.updated_at ? `Updated ${formatTimeAgo(info.updated_at)}` : '',
                ].filter(Boolean).join(' · ');
                return (
                  <div className="github-status-connected flex items-start gap-2 p-2 rounded-md bg-green-500/10 border border-green-500/30">
                    <span>✅</span>
                    <div className="text-xs">
                      <div className="font-medium text-foreground">{info.full_name}</div>
                      {meta && <div className="text-muted-foreground">{meta}</div>}
                      {info.html_url && (
                        <a
                          href={info.html_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline"
                        >
                          Open on GitHub ↗
                        </a>
                      )}
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>

          {/* ── Local path ── */}
          <div className="form-group space-y-1">
            <label className="text-sm font-medium text-foreground">📂 Local Path</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={localPath}
                onChange={(e) => setLocalPath(e.target.value)}
                placeholder="~/projects/my-app"
                data-testid="project-localpath-input"
                className="form-input flex-1 px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
              <button
                type="button"
                data-testid="tech-detect-btn"
                onClick={() => void handleTechDetect()}
                disabled={detecting || !localPath.trim()}
                className="btn-secondary px-3 py-2 rounded-md border border-border text-sm hover:bg-accent transition-colors disabled:opacity-50"
              >
                {detecting ? '⏳' : 'Detect'}
              </button>
            </div>

            {/* Tech stack display */}
            {techStack && techStack.technologies.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-1">
                {techStack.technologies.slice(0, 6).map((tech) => (
                  <span
                    key={tech.name}
                    className="project-tech-badge px-2 py-0.5 rounded text-xs bg-accent text-accent-foreground border border-border"
                  >
                    {tech.icon ? `${tech.icon} ` : ''}{tech.name}
                  </span>
                ))}
                {techStack.technologies.length > 6 && (
                  <span className="project-tech-badge px-2 py-0.5 rounded text-xs bg-accent text-muted-foreground border border-border">
                    +{techStack.technologies.length - 6}
                  </span>
                )}
              </div>
            )}
          </div>

          {/* ── Inherit Main Context (edit, non-system) ── */}
          {mode === 'edit' && !project?.isSystem && (
            <div className="form-group space-y-1">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="inherit-main-context"
                  checked={inheritMainContext}
                  onChange={(e) => setInheritMainContext(e.target.checked)}
                  data-testid="inherit-main-context-toggle"
                  className="setting-checkbox w-4 h-4 rounded border-border accent-primary"
                />
                <label
                  htmlFor="inherit-main-context"
                  className="text-sm text-foreground cursor-pointer"
                >
                  Include Main Board context
                </label>
              </div>
              <p className="text-xs text-muted-foreground ml-6">
                When enabled, AI responses also use knowledge from the Main Board.
              </p>
            </div>
          )}

          {/* ── Status (edit only) ── */}
          {mode === 'edit' && (
            <div className="form-group space-y-1">
              <label className="text-sm font-medium text-foreground">Status</label>
              <select
                value={selectedStatus}
                onChange={(e) => setSelectedStatus(e.target.value as 'active' | 'archived')}
                data-testid="project-status-select"
                className="form-input w-full px-3 py-2 rounded-md border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </select>
            </div>
          )}

          {/* ── Submit error ── */}
          {submitError && (
            <p className="text-sm text-destructive bg-destructive/10 border border-destructive/30 rounded-md px-3 py-2">
              {submitError}
            </p>
          )}

          {/* ── Actions ── */}
          <div className="form-actions flex items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={isPending}
              data-testid="project-form-submit"
              className="btn-primary px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {isPending
                ? 'Saving…'
                : mode === 'create'
                ? 'Create Project'
                : 'Save Changes'}
            </button>
            <button
              type="button"
              onClick={onClose}
              data-testid="project-form-cancel"
              className="btn-ghost px-4 py-2 rounded-md border border-border text-sm hover:bg-accent transition-colors"
            >
              Cancel
            </button>
            {mode === 'edit' && project && (
              <button
                type="button"
                onClick={() => void handleArchiveToggle()}
                data-testid="project-form-archive"
                className="btn-danger ml-auto px-4 py-2 rounded-md border border-destructive/50 text-destructive text-sm hover:bg-destructive/10 transition-colors"
              >
                {project.archived ? 'Unarchive' : 'Archive'}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
