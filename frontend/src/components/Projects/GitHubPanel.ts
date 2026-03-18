/**
 * GitHubPanel — collapsible panel showing GitHub repo info, issues and PRs.
 * Shown in the project chat view when a project has a `github_url` set.
 */

import { createElement } from '../../utils/helpers';
import { API_URL } from '../../utils/constants';

interface RepoInfo {
  name: string;
  full_name: string;
  description: string;
  html_url: string;
  stars: number;
  language: string | null;
  open_issues_count: number;
  default_branch: string;
  pushed_at: string | null;
}

interface Issue {
  number: number;
  title: string;
  html_url: string;
  labels: string[];
  assignee: string | null;
  created_at: string;
}

interface PullRequest {
  number: number;
  title: string;
  html_url: string;
  draft: boolean;
  created_at: string;
  user: string | null;
}

type ActiveTab = 'issues' | 'prs';

/** Parse "https://github.com/owner/repo" or "owner/repo" → { owner, repo } | null */
function parseGithubUrl(url: string): { owner: string; repo: string } | null {
  // Strip trailing slashes and .git
  const cleaned = url.trim().replace(/\.git$/, '').replace(/\/$/, '');

  // Full URL
  const urlMatch = cleaned.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+)$/);
  if (urlMatch) return { owner: urlMatch[1], repo: urlMatch[2] };

  // Short "owner/repo"
  const shortMatch = cleaned.match(/^([^/]+)\/([^/]+)$/);
  if (shortMatch) return { owner: shortMatch[1], repo: shortMatch[2] };

  return null;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export class GitHubPanel {
  private container: HTMLElement;
  private owner: string;
  private repo: string;

  private collapsed = false;
  private activeTab: ActiveTab = 'issues';

  private repoInfo: RepoInfo | null = null;
  private issues: Issue[] = [];
  private pulls: PullRequest[] = [];

  private loadingRepo = false;
  private loadingContent = false;
  private error: string | null = null;

  constructor(parent: HTMLElement, githubUrl: string) {
    this.container = createElement('div', { className: 'github-panel' });

    const parsed = parseGithubUrl(githubUrl);
    if (!parsed) {
      this.owner = '';
      this.repo = '';
      this.container.innerHTML = `<div class="github-panel-error">⚠️ Invalid GitHub URL: ${githubUrl}</div>`;
      parent.appendChild(this.container);
      return;
    }

    this.owner = parsed.owner;
    this.repo = parsed.repo;

    parent.appendChild(this.container);
    this.renderSkeleton();
    void this.fetchAll();
  }

  // ── Fetching ──────────────────────────────────────────────────────────────

  private async fetchAll(): Promise<void> {
    this.loadingRepo = true;
    this.error = null;
    this.renderContent();

    try {
      const base = API_URL || '';
      const repoResp = await fetch(`${base}/api/github/repo/${this.owner}/${this.repo}`);
      if (!repoResp.ok) {
        const body = await repoResp.json().catch(() => ({ detail: repoResp.statusText }));
        throw new Error((body as { detail?: string }).detail || `HTTP ${repoResp.status}`);
      }
      this.repoInfo = await repoResp.json() as RepoInfo;
      this.loadingRepo = false;
      this.renderContent();

      // Parallel load of issues + PRs
      this.loadingContent = true;
      this.renderContent();

      const [issuesResp, pullsResp] = await Promise.allSettled([
        fetch(`${base}/api/github/repo/${this.owner}/${this.repo}/issues`),
        fetch(`${base}/api/github/repo/${this.owner}/${this.repo}/pulls`),
      ]);

      if (issuesResp.status === 'fulfilled' && issuesResp.value.ok) {
        this.issues = await issuesResp.value.json() as Issue[];
      }
      if (pullsResp.status === 'fulfilled' && pullsResp.value.ok) {
        this.pulls = await pullsResp.value.json() as PullRequest[];
      }

      this.loadingContent = false;
    } catch (err) {
      this.loadingRepo = false;
      this.loadingContent = false;
      this.error = err instanceof Error ? err.message : String(err);
    }

    this.renderContent();
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  private renderSkeleton(): void {
    this.container.innerHTML = `
      <div class="github-panel-header github-panel-header--skeleton">
        <span class="github-panel-title-skeleton"></span>
      </div>
      <div class="github-skeleton-body">
        <div class="github-skeleton-line"></div>
        <div class="github-skeleton-line github-skeleton-line--short"></div>
        <div class="github-skeleton-line"></div>
      </div>
    `;
  }

  private renderContent(): void {
    if (this.loadingRepo) {
      this.renderSkeleton();
      return;
    }

    this.container.innerHTML = '';

    // ── Header ──
    const header = createElement('div', { className: 'github-panel-header' });

    const titleWrap = createElement('div', { className: 'github-panel-title-wrap' });
    const octiconSvg = `<svg class="github-octicon" viewBox="0 0 16 16" width="16" height="16" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
        0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13
        -.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66
        .07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15
        -.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0
        1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82
        1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01
        1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
    </svg>`;
    titleWrap.innerHTML = octiconSvg;

    if (this.repoInfo) {
      const repoLink = createElement('a', {
        className: 'github-panel-repo-link',
        href: this.repoInfo.html_url,
        target: '_blank',
        rel: 'noopener noreferrer',
      }, this.repoInfo.full_name);
      titleWrap.appendChild(repoLink);
    } else {
      const repoName = createElement('span', { className: 'github-panel-repo-name' }, `${this.owner}/${this.repo}`);
      titleWrap.appendChild(repoName);
    }

    const headerActions = createElement('div', { className: 'github-panel-header-actions' });

    const refreshBtn = createElement('button', {
      className: 'github-panel-refresh-btn',
      title: 'Refresh',
    }, '↻');
    refreshBtn.addEventListener('click', () => { void this.fetchAll(); });

    const toggleBtn = createElement('button', {
      className: `github-panel-toggle-btn ${this.collapsed ? 'collapsed' : ''}`,
      title: this.collapsed ? 'Expand' : 'Collapse',
    }, this.collapsed ? '▸' : '▾');
    toggleBtn.addEventListener('click', () => {
      this.collapsed = !this.collapsed;
      this.renderContent();
    });

    headerActions.appendChild(refreshBtn);
    headerActions.appendChild(toggleBtn);

    header.appendChild(titleWrap);
    header.appendChild(headerActions);
    this.container.appendChild(header);

    if (this.error) {
      const errEl = createElement('div', { className: 'github-panel-error' }, `⚠️ ${this.error}`);
      this.container.appendChild(errEl);
      return;
    }

    if (this.collapsed) return;

    // ── Stats row ──
    if (this.repoInfo) {
      const statsRow = createElement('div', { className: 'github-panel-stats' });

      if (this.repoInfo.stars > 0) {
        const stars = createElement('span', { className: 'github-stat' }, `⭐ ${this.repoInfo.stars}`);
        statsRow.appendChild(stars);
      }
      if (this.repoInfo.language) {
        const lang = createElement('span', { className: 'github-stat' }, `🔤 ${this.repoInfo.language}`);
        statsRow.appendChild(lang);
      }
      const issuesStat = createElement('span', { className: 'github-stat' }, `🐛 ${this.repoInfo.open_issues_count} issues`);
      statsRow.appendChild(issuesStat);

      const prsStat = createElement('span', { className: 'github-stat' }, `🔀 ${this.pulls.length} PRs`);
      statsRow.appendChild(prsStat);

      if (this.repoInfo.description) {
        const desc = createElement('p', { className: 'github-panel-description' }, this.repoInfo.description);
        this.container.appendChild(statsRow);
        this.container.appendChild(desc);
      } else {
        this.container.appendChild(statsRow);
      }
    }

    // ── Tabs ──
    const tabs = createElement('div', { className: 'github-panel-tabs' });

    const issuesTab = createElement('button', {
      className: `github-panel-tab ${this.activeTab === 'issues' ? 'active' : ''}`,
    }, `🐛 Issues (${this.issues.length})`);
    issuesTab.addEventListener('click', () => {
      this.activeTab = 'issues';
      this.renderContent();
    });

    const prsTab = createElement('button', {
      className: `github-panel-tab ${this.activeTab === 'prs' ? 'active' : ''}`,
    }, `🔀 PRs (${this.pulls.length})`);
    prsTab.addEventListener('click', () => {
      this.activeTab = 'prs';
      this.renderContent();
    });

    tabs.appendChild(issuesTab);
    tabs.appendChild(prsTab);
    this.container.appendChild(tabs);

    // ── Content ──
    const content = createElement('div', { className: 'github-panel-content' });

    if (this.loadingContent) {
      content.innerHTML = `
        <div class="github-skeleton-body">
          <div class="github-skeleton-line"></div>
          <div class="github-skeleton-line github-skeleton-line--short"></div>
          <div class="github-skeleton-line"></div>
        </div>`;
    } else if (this.activeTab === 'issues') {
      if (this.issues.length === 0) {
        content.appendChild(createElement('div', { className: 'github-panel-empty' }, '🎉 No open issues'));
      } else {
        this.issues.forEach((issue) => {
          const item = createElement('div', { className: 'github-issue-item' });

          const link = createElement('a', {
            className: 'github-item-link',
            href: issue.html_url,
            target: '_blank',
            rel: 'noopener noreferrer',
          }, `#${issue.number} ${issue.title}`);

          const meta = createElement('div', { className: 'github-item-meta' });
          if (issue.created_at) {
            meta.appendChild(createElement('span', { className: 'github-item-date' }, relativeTime(issue.created_at)));
          }
          if (issue.assignee) {
            meta.appendChild(createElement('span', { className: 'github-item-assignee' }, `@${issue.assignee}`));
          }

          const labels = createElement('div', { className: 'github-item-labels' });
          issue.labels.forEach((lbl) => {
            labels.appendChild(createElement('span', { className: 'github-label' }, lbl));
          });

          item.appendChild(link);
          item.appendChild(meta);
          if (issue.labels.length > 0) item.appendChild(labels);
          content.appendChild(item);
        });
      }
    } else {
      // PRs tab
      if (this.pulls.length === 0) {
        content.appendChild(createElement('div', { className: 'github-panel-empty' }, '🎉 No open PRs'));
      } else {
        this.pulls.forEach((pr) => {
          const item = createElement('div', { className: 'github-pr-item' });

          const statusBadge = pr.draft
            ? createElement('span', { className: 'github-pr-status github-pr-status--draft' }, 'Draft')
            : createElement('span', { className: 'github-pr-status github-pr-status--open' }, 'Open');

          const link = createElement('a', {
            className: 'github-item-link',
            href: pr.html_url,
            target: '_blank',
            rel: 'noopener noreferrer',
          }, `#${pr.number} ${pr.title}`);

          const meta = createElement('div', { className: 'github-item-meta' });
          if (pr.created_at) {
            meta.appendChild(createElement('span', { className: 'github-item-date' }, relativeTime(pr.created_at)));
          }
          if (pr.user) {
            meta.appendChild(createElement('span', { className: 'github-item-assignee' }, `@${pr.user}`));
          }

          item.appendChild(statusBadge);
          item.appendChild(link);
          item.appendChild(meta);
          content.appendChild(item);
        });
      }
    }

    this.container.appendChild(content);
  }

  destroy(): void {
    this.container.remove();
  }
}
