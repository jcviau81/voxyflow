import { Card, ActivityEntry } from '../../types';
import { appState } from '../../state/AppState';
import { eventBus } from '../../utils/EventBus';
import { EVENTS } from '../../utils/constants';
import { createElement } from '../../utils/helpers';
import { apiClient } from '../../services/ApiClient';

const STATUS_CONFIG: { key: Card['status']; label: string; color: string }[] = [
  { key: 'idea',        label: '💡 Idea',        color: '#a78bfa' },
  { key: 'todo',        label: '📋 Todo',         color: '#60a5fa' },
  { key: 'in-progress', label: '🔨 In Progress',  color: '#fbbf24' },
  { key: 'done',        label: '✅ Done',          color: '#4ade80' },
];

const PRIORITY_CONFIG: { value: number; label: string; color: string }[] = [
  { value: 3, label: '🔴 Critical', color: '#ef4444' },
  { value: 2, label: '🟠 High',     color: '#f97316' },
  { value: 1, label: '🟡 Medium',   color: '#eab308' },
  { value: 0, label: '🟢 Low',      color: '#22c55e' },
];

export class ProjectStats {
  private container: HTMLElement;
  private unsubscribers: (() => void)[] = [];

  // Standup state
  private standupLoading = false;
  private standupSummary: string | null = null;
  private standupGeneratedAt: string | null = null;
  private standupScheduled = false;
  private standupCard: HTMLElement | null = null;

  // Brief state
  private briefLoading = false;
  private briefContent: string | null = null;
  private briefGeneratedAt: string | null = null;

  // Health Check state
  private healthLoading = false;
  private healthData: {
    score: number;
    grade: string;
    summary: string;
    strengths: string[];
    issues: { severity: string; message: string }[];
    recommendations: string[];
    generated_at: string;
  } | null = null;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', { className: 'stats-view' });
    this.render();
    this.setupListeners();
    this._checkStandupSchedule();
  }

  private render(): void {
    this.container.innerHTML = '';

    const projectId = appState.get('currentProjectId');
    if (!projectId) {
      const empty = createElement('div', { className: 'stats-empty' });
      empty.textContent = 'No project selected.';
      this.container.appendChild(empty);
      this.parentElement.appendChild(this.container);
      return;
    }

    const project = appState.getProject(projectId);
    const cards = appState.getCardsByProject(projectId);
    const activities = appState.getActivities(projectId, 50);

    // ── Header ─────────────────────────────────────
    const header = createElement('div', { className: 'stats-header' });
    const title = createElement('h2', { className: 'stats-title' });
    title.textContent = `📊 ${project?.name ?? 'Project'} — Stats`;
    header.appendChild(title);
    this.container.appendChild(header);

    // ── Grid ───────────────────────────────────────
    const grid = createElement('div', { className: 'stats-grid' });

    // 1. Progress ring
    grid.appendChild(this.buildProgressRing(cards));

    // 2. Cards by status
    grid.appendChild(this.buildStatusChart(cards));

    // 3. Cards by priority
    grid.appendChild(this.buildPriorityChart(cards));

    // 4. Cards by agent
    grid.appendChild(this.buildAgentChart(cards));

    // 5. Velocity (last 7 days)
    grid.appendChild(this.buildVelocityCard(activities));

    // 6. Total time logged (placeholder — no time-tracking field yet)
    grid.appendChild(this.buildTimeLoggedCard(cards));

    this.container.appendChild(grid);

    // ── Daily Standup ───────────────────────────────
    const standupSection = this.buildStandupSection();
    this.container.appendChild(standupSection);

    // ── Project Brief ────────────────────────────────
    const briefSection = this._buildBriefSection();
    this.container.appendChild(briefSection);

    // ── Health Check ─────────────────────────────────
    const healthSection = this._buildHealthSection();
    this.container.appendChild(healthSection);

    this.parentElement.appendChild(this.container);
  }

  // ── 1. Progress Ring ────────────────────────────
  private buildProgressRing(cards: Card[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card progress-ring-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Progress';
    card.appendChild(cardTitle);

    const total = cards.length;
    const done = cards.filter(c => c.status === 'done').length;
    const pct = total > 0 ? Math.round((done / total) * 100) : 0;

    const radius = 52;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (pct / 100) * circumference;

    const wrapper = createElement('div', { className: 'progress-ring' });
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('viewBox', '0 0 120 120');
    svg.setAttribute('width', '120');
    svg.setAttribute('height', '120');

    const bg = document.createElementNS(svgNS, 'circle');
    bg.setAttribute('cx', '60');
    bg.setAttribute('cy', '60');
    bg.setAttribute('r', String(radius));
    bg.setAttribute('fill', 'none');
    bg.setAttribute('stroke', 'rgba(255,255,255,0.08)');
    bg.setAttribute('stroke-width', '10');

    const fg = document.createElementNS(svgNS, 'circle');
    fg.setAttribute('cx', '60');
    fg.setAttribute('cy', '60');
    fg.setAttribute('r', String(radius));
    fg.setAttribute('fill', 'none');
    fg.setAttribute('stroke', '#4ade80');
    fg.setAttribute('stroke-width', '10');
    fg.setAttribute('stroke-linecap', 'round');
    fg.setAttribute('stroke-dasharray', String(circumference));
    fg.setAttribute('stroke-dashoffset', String(offset));
    fg.setAttribute('transform', 'rotate(-90 60 60)');
    fg.style.transition = 'stroke-dashoffset 0.6s ease';

    const text = document.createElementNS(svgNS, 'text');
    text.setAttribute('x', '60');
    text.setAttribute('y', '60');
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('fill', '#e8e8ed');
    text.setAttribute('font-size', '20');
    text.setAttribute('font-weight', '700');
    text.textContent = `${pct}%`;

    svg.appendChild(bg);
    svg.appendChild(fg);
    svg.appendChild(text);
    wrapper.appendChild(svg);

    const sub = createElement('div', { className: 'stat-card-sub' });
    sub.textContent = `${done} of ${total} cards done`;

    card.appendChild(wrapper);
    card.appendChild(sub);
    return card;
  }

  // ── 2. Cards by Status ──────────────────────────
  private buildStatusChart(cards: Card[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Cards by Status';
    card.appendChild(cardTitle);

    const total = cards.length || 1;
    const chart = createElement('div', { className: 'bar-chart' });

    for (const cfg of STATUS_CONFIG) {
      const count = cards.filter(c => c.status === cfg.key).length;
      const pct = Math.round((count / total) * 100);
      const row = this.buildBarRow(cfg.label, count, pct, cfg.color);
      chart.appendChild(row);
    }

    card.appendChild(chart);
    return card;
  }

  // ── 3. Cards by Priority ─────────────────────────
  private buildPriorityChart(cards: Card[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Cards by Priority';
    card.appendChild(cardTitle);

    const total = cards.length || 1;
    const chart = createElement('div', { className: 'bar-chart' });

    for (const cfg of PRIORITY_CONFIG) {
      const count = cards.filter(c => c.priority === cfg.value).length;
      const pct = Math.round((count / total) * 100);
      const row = this.buildBarRow(cfg.label, count, pct, cfg.color);
      chart.appendChild(row);
    }

    card.appendChild(chart);
    return card;
  }

  // ── 4. Cards by Agent ────────────────────────────
  private buildAgentChart(cards: Card[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Cards by Agent';
    card.appendChild(cardTitle);

    // Count per agent
    const agentCounts: Record<string, number> = {};
    for (const c of cards) {
      const agent = c.agentType || c.assignedAgent || 'unassigned';
      agentCounts[agent] = (agentCounts[agent] || 0) + 1;
    }

    const sorted = Object.entries(agentCounts).sort((a, b) => b[1] - a[1]);
    const total = cards.length || 1;
    const chart = createElement('div', { className: 'bar-chart' });

    const AGENT_COLORS: Record<string, string> = {
      ember: '#ff6b6b',
      coder: '#60a5fa',
      architect: '#a78bfa',
      researcher: '#34d399',
      designer: '#f472b6',
      writer: '#fb923c',
      qa: '#fbbf24',
      unassigned: '#5c5c6b',
    };

    for (const [agent, count] of sorted) {
      const pct = Math.round((count / total) * 100);
      const color = AGENT_COLORS[agent] || '#9e9ea8';
      const label = agent === 'unassigned' ? '— Unassigned' : `🤖 ${agent.charAt(0).toUpperCase() + agent.slice(1)}`;
      const row = this.buildBarRow(label, count, pct, color);
      chart.appendChild(row);
    }

    if (sorted.length === 0) {
      const empty = createElement('div', { className: 'stat-empty-row' });
      empty.textContent = 'No agents assigned yet.';
      chart.appendChild(empty);
    }

    card.appendChild(chart);
    return card;
  }

  // ── 5. Velocity (cards → done last 7 days) ───────
  private buildVelocityCard(activities: ActivityEntry[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Velocity (last 7 days)';
    card.appendChild(cardTitle);

    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    const doneRecently = activities.filter(
      a => a.type === 'card_moved' &&
           a.message.includes('✅ Done') &&
           a.timestamp >= sevenDaysAgo
    );

    const bigNum = createElement('div', { className: 'stat-big-number' });
    bigNum.textContent = String(doneRecently.length);

    const sub = createElement('div', { className: 'stat-card-sub' });
    sub.textContent = doneRecently.length === 1 ? 'card completed' : 'cards completed';

    card.appendChild(bigNum);
    card.appendChild(sub);

    // Mini daily sparkline — last 7 days
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const days: { label: string; count: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const dayStart = today.getTime() - i * 86400000;
      const dayEnd = dayStart + 86400000;
      const count = doneRecently.filter(a => a.timestamp >= dayStart && a.timestamp < dayEnd).length;
      const d = new Date(dayStart);
      const label = d.toLocaleDateString('en', { weekday: 'short' });
      days.push({ label, count });
    }

    const maxCount = Math.max(...days.map(d => d.count), 1);
    const sparkline = createElement('div', { className: 'sparkline' });
    for (const day of days) {
      const barWrap = createElement('div', { className: 'sparkline-bar-wrap' });
      const bar = createElement('div', { className: 'sparkline-bar' });
      bar.style.height = `${Math.round((day.count / maxCount) * 40)}px`;
      bar.title = `${day.label}: ${day.count}`;
      const lbl = createElement('div', { className: 'sparkline-label' });
      lbl.textContent = day.label.slice(0, 1);
      barWrap.appendChild(bar);
      barWrap.appendChild(lbl);
      sparkline.appendChild(barWrap);
    }
    card.appendChild(sparkline);
    return card;
  }

  // ── 6. Time Logged ───────────────────────────────
  private buildTimeLoggedCard(_cards: Card[]): HTMLElement {
    const card = createElement('div', { className: 'stat-card' });
    const cardTitle = createElement('div', { className: 'stat-card-title' });
    cardTitle.textContent = 'Time Logged';
    card.appendChild(cardTitle);

    // No time-tracking field on Card yet — show placeholder
    const bigNum = createElement('div', { className: 'stat-big-number stat-muted' });
    bigNum.textContent = '—';
    const sub = createElement('div', { className: 'stat-card-sub' });
    sub.textContent = 'Time tracking coming soon';

    card.appendChild(bigNum);
    card.appendChild(sub);
    return card;
  }

  // ── Helper: bar row ──────────────────────────────
  private buildBarRow(label: string, count: number, pct: number, color: string): HTMLElement {
    const row = createElement('div', { className: 'bar' });
    const rowLabel = createElement('div', { className: 'bar-label' });
    rowLabel.textContent = label;
    const rowTrack = createElement('div', { className: 'bar-track' });
    const fill = createElement('div', { className: 'bar-fill' });
    fill.style.width = `${pct}%`;
    fill.style.background = color;
    rowTrack.appendChild(fill);
    const countLabel = createElement('div', { className: 'bar-count' });
    countLabel.textContent = String(count);
    row.appendChild(rowLabel);
    row.appendChild(rowTrack);
    row.appendChild(countLabel);
    return row;
  }

  // ── Daily Standup ────────────────────────────────

  private buildStandupSection(): HTMLElement {
    const section = createElement('div', { className: 'standup-section' });

    const sectionTitle = createElement('h3', { className: 'standup-section-title' });
    sectionTitle.textContent = '📋 Daily Standup';
    section.appendChild(sectionTitle);

    const controls = createElement('div', { className: 'standup-controls' });

    // Generate button
    const genBtn = createElement('button', {
      className: `standup-gen-btn${this.standupLoading ? ' loading' : ''}`,
    });
    genBtn.textContent = this.standupLoading ? '⏳ Generating…' : '✨ Generate Standup';
    genBtn.disabled = this.standupLoading;
    genBtn.addEventListener('click', () => this._generateStandup());
    controls.appendChild(genBtn);

    // Schedule toggle
    const scheduleLabel = createElement('label', { className: 'standup-schedule-label' });
    const scheduleToggle = createElement('input', { type: 'checkbox' }) as HTMLInputElement;
    scheduleToggle.checked = this.standupScheduled;
    scheduleToggle.addEventListener('change', () => this._toggleSchedule(scheduleToggle.checked));
    const scheduleText = createElement('span');
    scheduleText.textContent = '⏰ Schedule daily (09:00)';
    scheduleLabel.appendChild(scheduleToggle);
    scheduleLabel.appendChild(scheduleText);
    controls.appendChild(scheduleLabel);

    section.appendChild(controls);

    // Summary card (shown after generation)
    if (this.standupSummary) {
      const card = this._buildStandupCard(this.standupSummary, this.standupGeneratedAt);
      this.standupCard = card;
      section.appendChild(card);
    }

    return section;
  }

  private _buildStandupCard(summary: string, generatedAt: string | null): HTMLElement {
    const card = createElement('div', { className: 'standup-card' });

    if (generatedAt) {
      const meta = createElement('div', { className: 'standup-card-meta' });
      const date = new Date(generatedAt);
      meta.textContent = `Generated ${date.toLocaleString()}`;
      card.appendChild(meta);
    }

    const content = createElement('div', { className: 'standup-card-content' });
    // Render markdown-ish: bold lines, bullet points via simple parsing
    content.innerHTML = this._renderMarkdown(summary);
    card.appendChild(content);

    const copyBtn = createElement('button', { className: 'standup-copy-btn' });
    copyBtn.textContent = '📋 Copy to Clipboard';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(summary).then(() => {
        copyBtn.textContent = '✅ Copied!';
        setTimeout(() => { copyBtn.textContent = '📋 Copy to Clipboard'; }, 2000);
      });
    });
    card.appendChild(copyBtn);

    return card;
  }

  private _renderMarkdown(text: string): string {
    return text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^(#{1,3})\s+(.+)$/gm, '<h4>$2</h4>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>')
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>');
  }

  private async _generateStandup(): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;

    this.standupLoading = true;
    this._refreshStandupSection();

    try {
      const response = await fetch(`/api/projects/${projectId}/standup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      this.standupSummary = data.summary;
      this.standupGeneratedAt = data.generated_at;
    } catch (err) {
      console.error('[Standup] generation failed:', err);
      this.standupSummary = '⚠️ Failed to generate standup. Please try again.';
      this.standupGeneratedAt = null;
    } finally {
      this.standupLoading = false;
      this._refreshStandupSection();
    }
  }

  private async _checkStandupSchedule(): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;
    try {
      const resp = await fetch(`/api/projects/${projectId}/standup/schedule`);
      if (resp.ok) {
        const data = await resp.json();
        this.standupScheduled = !!(data && data.enabled);
        this._refreshStandupSection();
      }
    } catch {
      // Non-fatal
    }
  }

  private async _toggleSchedule(enabled: boolean): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;
    try {
      await fetch(`/api/projects/${projectId}/standup/schedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, hour: 9, minute: 0 }),
      });
      this.standupScheduled = enabled;
    } catch (err) {
      console.error('[Standup] schedule toggle failed:', err);
    }
  }

  private _refreshStandupSection(): void {
    // Find and replace the standup section in the container
    const existing = this.container.querySelector('.standup-section');
    if (existing) {
      const newSection = this.buildStandupSection();
      existing.replaceWith(newSection);
    }
  }

  private setupListeners(): void {
    // Re-render on any card or project change
    const rerender = () => {
      const old = this.container;
      this.container = createElement('div', { className: 'stats-view' });
      this.render();
      old.replaceWith(this.container);
    };

    this.unsubscribers.push(eventBus.on(EVENTS.CARD_CREATED, rerender));
    this.unsubscribers.push(eventBus.on(EVENTS.CARD_UPDATED, rerender));
    this.unsubscribers.push(eventBus.on(EVENTS.CARD_DELETED, rerender));
    this.unsubscribers.push(eventBus.on(EVENTS.CARD_MOVED, rerender));
    this.unsubscribers.push(eventBus.on(EVENTS.PROJECT_SELECTED, rerender));
    this.unsubscribers.push(eventBus.on(EVENTS.ACTIVITY_ADDED, rerender));
  }

  // ── Project Brief ────────────────────────────────

  private _buildBriefSection(): HTMLElement {
    const section = createElement('div', { className: 'brief-section' });

    const sectionTitle = createElement('h3', { className: 'brief-section-title' });
    sectionTitle.textContent = '📄 Project Brief';
    section.appendChild(sectionTitle);

    const controls = createElement('div', { className: 'brief-controls' });

    const genBtn = createElement('button', {
      className: `brief-gen-btn${this.briefLoading ? ' loading' : ''}`,
    });
    genBtn.disabled = this.briefLoading;

    if (this.briefLoading) {
      genBtn.innerHTML = '⏳ Generating… <span class="brief-loading-note">(Using Deep model — may take 10-15s…)</span>';
    } else {
      genBtn.innerHTML = '✨ Generate Brief <span class="brief-model-note">Opus</span>';
    }

    genBtn.addEventListener('click', () => this._generateBrief());
    controls.appendChild(genBtn);
    section.appendChild(controls);

    if (this.briefContent) {
      const card = this._buildBriefCard(this.briefContent, this.briefGeneratedAt);
      section.appendChild(card);
    }

    return section;
  }

  private _buildBriefCard(brief: string, generatedAt: string | null): HTMLElement {
    const card = createElement('div', { className: 'brief-card' });

    if (generatedAt) {
      const meta = createElement('div', { className: 'brief-card-meta' });
      const date = new Date(generatedAt);
      meta.textContent = `Generated ${date.toLocaleString()} · Deep model (Opus)`;
      card.appendChild(meta);
    }

    const content = createElement('div', { className: 'brief-card-content' });
    content.innerHTML = this._renderMarkdown(brief);
    card.appendChild(content);

    const actions = createElement('div', { className: 'brief-actions' });

    const copyBtn = createElement('button', { className: 'brief-action-btn' });
    copyBtn.textContent = '📋 Copy to Clipboard';
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(brief).then(() => {
        copyBtn.textContent = '✅ Copied!';
        setTimeout(() => { copyBtn.textContent = '📋 Copy to Clipboard'; }, 2000);
      });
    });

    const projectId = appState.get('currentProjectId');
    const project = projectId ? appState.getProject(projectId) : null;
    const filename = `${(project?.name ?? 'project').replace(/\s+/g, '-').toLowerCase()}-brief.md`;

    const downloadBtn = createElement('button', { className: 'brief-action-btn' });
    downloadBtn.textContent = '⬇️ Download .md';
    downloadBtn.addEventListener('click', () => {
      const blob = new Blob([brief], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });

    actions.appendChild(copyBtn);
    actions.appendChild(downloadBtn);
    card.appendChild(actions);

    return card;
  }

  private async _generateBrief(): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;

    this.briefLoading = true;
    this._refreshBriefSection();

    try {
      const response = await fetch(`/api/projects/${projectId}/brief`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      this.briefContent = data.brief;
      this.briefGeneratedAt = data.generated_at;
    } catch (err) {
      console.error('[Brief] generation failed:', err);
      this.briefContent = '⚠️ Failed to generate project brief. Please try again.';
      this.briefGeneratedAt = null;
    } finally {
      this.briefLoading = false;
      this._refreshBriefSection();
    }
  }

  private _refreshBriefSection(): void {
    const existing = this.container.querySelector('.brief-section');
    if (existing) {
      const newSection = this._buildBriefSection();
      existing.replaceWith(newSection);
    }
  }

  // ── Health Check ─────────────────────────────────

  private _buildHealthSection(): HTMLElement {
    const section = createElement('div', { className: 'health-check-section' });

    const sectionTitle = createElement('h3', { className: 'health-check-section-title' });
    sectionTitle.textContent = '🏥 Health Check';
    section.appendChild(sectionTitle);

    const controls = createElement('div', { className: 'health-check-controls' });

    const runBtn = createElement('button', {
      className: `health-run-btn${this.healthLoading ? ' loading' : ''}`,
    });
    runBtn.disabled = this.healthLoading;
    if (this.healthLoading) {
      runBtn.textContent = '⏳ Analysing…';
    } else {
      runBtn.textContent = '🏥 Run Health Check';
    }
    runBtn.addEventListener('click', () => this._runHealthCheck());
    controls.appendChild(runBtn);
    section.appendChild(controls);

    if (this.healthData) {
      const card = this._buildHealthCard(this.healthData);
      section.appendChild(card);
    }

    return section;
  }

  private _buildHealthCard(data: NonNullable<typeof this.healthData>): HTMLElement {
    const card = createElement('div', { className: 'health-card' });

    // Meta
    const meta = createElement('div', { className: 'health-card-meta' });
    const date = new Date(data.generated_at);
    meta.textContent = `Analysed ${date.toLocaleString()}`;
    card.appendChild(meta);

    // Score + Grade row
    const scoreRow = createElement('div', { className: 'health-score-row' });

    const scoreEl = createElement('div', { className: 'health-score' });
    scoreEl.textContent = String(data.score);
    if (data.score > 80) scoreEl.classList.add('health-score--green');
    else if (data.score > 60) scoreEl.classList.add('health-score--yellow');
    else scoreEl.classList.add('health-score--red');

    const gradeEl = createElement('div', { className: 'health-grade' });
    gradeEl.textContent = data.grade;
    gradeEl.classList.add(`health-grade--${data.grade.toLowerCase()}`);

    scoreRow.appendChild(scoreEl);
    scoreRow.appendChild(gradeEl);
    card.appendChild(scoreRow);

    // Summary
    const summaryEl = createElement('p', { className: 'health-summary' });
    summaryEl.textContent = data.summary;
    card.appendChild(summaryEl);

    // Strengths
    if (data.strengths.length > 0) {
      const strengthsEl = createElement('div', { className: 'health-strengths' });
      const strengthsTitle = createElement('div', { className: 'health-list-title' });
      strengthsTitle.textContent = 'Strengths';
      strengthsEl.appendChild(strengthsTitle);
      const ul = createElement('ul', { className: 'health-list' });
      for (const s of data.strengths) {
        const li = createElement('li', { className: 'health-strength-item' });
        li.textContent = `✅ ${s}`;
        ul.appendChild(li);
      }
      strengthsEl.appendChild(ul);
      card.appendChild(strengthsEl);
    }

    // Issues
    if (data.issues.length > 0) {
      const issuesEl = createElement('div', { className: 'health-issues' });
      const issuesTitle = createElement('div', { className: 'health-list-title' });
      issuesTitle.textContent = 'Issues';
      issuesEl.appendChild(issuesTitle);
      const ul = createElement('ul', { className: 'health-list' });
      for (const issue of data.issues) {
        const li = createElement('li', { className: `health-issue-item health-issue-item--${issue.severity}` });
        const icon = issue.severity === 'critical' ? '🔴' : issue.severity === 'warning' ? '🟡' : '🔵';
        li.textContent = `${icon} ${issue.message}`;
        ul.appendChild(li);
      }
      issuesEl.appendChild(ul);
      card.appendChild(issuesEl);
    }

    // Recommendations
    if (data.recommendations.length > 0) {
      const recsEl = createElement('div', { className: 'health-recommendations' });
      const recsTitle = createElement('div', { className: 'health-list-title' });
      recsTitle.textContent = 'Recommendations';
      recsEl.appendChild(recsTitle);
      const ul = createElement('ul', { className: 'health-list' });
      for (const rec of data.recommendations) {
        const li = createElement('li', { className: 'health-rec-item' });
        li.textContent = `💡 ${rec}`;
        ul.appendChild(li);
      }
      recsEl.appendChild(ul);
      card.appendChild(recsEl);
    }

    // No issues = all clear message
    if (data.issues.length === 0) {
      const allClear = createElement('div', { className: 'health-all-clear' });
      allClear.textContent = '✅ No issues detected — project looks healthy!';
      card.appendChild(allClear);
    }

    return card;
  }

  private async _runHealthCheck(): Promise<void> {
    const projectId = appState.get('currentProjectId');
    if (!projectId) return;

    this.healthLoading = true;
    this._refreshHealthSection();

    try {
      const response = await fetch(`/api/projects/${projectId}/health`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      this.healthData = await response.json();
    } catch (err) {
      console.error('[HealthCheck] failed:', err);
      this.healthData = {
        score: 0,
        grade: 'F',
        summary: '⚠️ Failed to run health check. Please try again.',
        strengths: [],
        issues: [],
        recommendations: [],
        generated_at: new Date().toISOString(),
      };
    } finally {
      this.healthLoading = false;
      this._refreshHealthSection();
    }
  }

  private _refreshHealthSection(): void {
    const existing = this.container.querySelector('.health-check-section');
    if (existing) {
      const newSection = this._buildHealthSection();
      existing.replaceWith(newSection);
    }
  }

  update(): void {
    // Reset standup state when project changes
    this.standupSummary = null;
    this.standupGeneratedAt = null;
    this.standupScheduled = false;
    this.standupLoading = false;
    // Reset brief state
    this.briefContent = null;
    this.briefGeneratedAt = null;
    this.briefLoading = false;
    // Reset health check state
    this.healthData = null;
    this.healthLoading = false;
    const old = this.container;
    this.container = createElement('div', { className: 'stats-view' });
    this.render();
    old.replaceWith(this.container);
    this._checkStandupSchedule();
  }

  destroy(): void {
    this.unsubscribers.forEach(u => u());
    this.unsubscribers = [];
    this.container.remove();
  }
}
