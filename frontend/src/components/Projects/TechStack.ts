import { TechDetectResult, TechInfo } from '../../types';
import { createElement } from '../../utils/helpers';
import { API_URL } from '../../utils/constants';

/**
 * TechStack — displays detected technologies as categorized badge chips.
 *
 * Usage:
 *   const ts = new TechStack(parentEl);
 *   ts.detect('/path/to/project');   // fetches from backend
 *   ts.setData(techDetectResult);    // or set directly
 *   ts.destroy();
 */
export class TechStack {
  private container: HTMLElement;
  private data: TechDetectResult | null = null;
  private loading = false;

  constructor(private parentElement: HTMLElement) {
    this.container = createElement('div', {
      className: 'tech-stack',
      'data-testid': 'tech-stack',
    });
    this.parentElement.appendChild(this.container);
    this.render();
  }

  /** Fetch tech detection from the backend API. */
  async detect(projectPath: string): Promise<TechDetectResult | null> {
    if (!projectPath) return null;

    this.loading = true;
    this.render();

    try {
      const url = `${API_URL}/api/tech/detect?project_path=${encodeURIComponent(projectPath)}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const result: TechDetectResult = await resp.json();
      this.data = result;
      this.loading = false;
      this.render();
      return result;
    } catch (err) {
      console.error('[TechStack] detection failed:', err);
      this.loading = false;
      this.render();
      return null;
    }
  }

  /** Set pre-fetched data directly. */
  setData(data: TechDetectResult | null): void {
    this.data = data;
    this.render();
  }

  /** Get current result. */
  getData(): TechDetectResult | null {
    return this.data;
  }

  private render(): void {
    this.container.innerHTML = '';

    if (this.loading) {
      const spinner = createElement('div', { className: 'tech-loading' }, '🔍 Detecting technologies…');
      this.container.appendChild(spinner);
      return;
    }

    if (!this.data || !this.data.technologies || this.data.technologies.length === 0) {
      // Empty state — hide entirely
      this.container.style.display = 'none';
      return;
    }

    this.container.style.display = '';

    // Header
    const heading = createElement('h4', {}, 'Detected Technologies');
    this.container.appendChild(heading);

    // Group techs by category
    const grouped = this.groupByCategory(this.data.technologies);

    // Badges container
    const badges = createElement('div', { className: 'tech-badges' });

    // Render grouped — category order: language, runtime, framework, build, testing, infra, security, ai, lib, config, ci, quality, styling, database, validation
    const categoryOrder = [
      'language', 'runtime', 'framework', 'build', 'testing', 'infra',
      'security', 'ai', 'lib', 'config', 'ci', 'quality', 'styling',
      'database', 'validation',
    ];

    for (const cat of categoryOrder) {
      const techs = grouped.get(cat);
      if (!techs) continue;
      for (const tech of techs) {
        const badge = createElement(
          'span',
          { className: `tech-badge ${tech.category}`, title: tech.source || tech.category },
          `${tech.icon} ${tech.name}${tech.version ? ` ${tech.version}` : ''}`
        );
        badges.appendChild(badge);
      }
    }

    // Render any remaining categories not in order
    for (const [cat, techs] of grouped) {
      if (categoryOrder.includes(cat)) continue;
      for (const tech of techs) {
        const badge = createElement(
          'span',
          { className: `tech-badge ${tech.category}` },
          `${tech.icon} ${tech.name}${tech.version ? ` ${tech.version}` : ''}`
        );
        badges.appendChild(badge);
      }
    }

    this.container.appendChild(badges);

    // File counts summary
    if (this.data.total_files > 0 && this.data.file_counts) {
      const topExts = Object.entries(this.data.file_counts)
        .slice(0, 5)
        .map(([ext, count]) => `${ext}: ${count}`)
        .join(', ');
      const summary = createElement(
        'div',
        { className: 'tech-files' },
        `${this.data.total_files} files (${topExts})`
      );
      this.container.appendChild(summary);
    }
  }

  private groupByCategory(techs: TechInfo[]): Map<string, TechInfo[]> {
    const map = new Map<string, TechInfo[]>();
    for (const tech of techs) {
      const cat = tech.category || 'other';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(tech);
    }
    return map;
  }

  destroy(): void {
    this.container.remove();
  }
}
