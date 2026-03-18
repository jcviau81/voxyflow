/**
 * CodeReviewService — thin client for the /api/code/review endpoint.
 *
 * Also provides:
 * - looksLikeCode()       : lightweight regex check for paste detection
 * - detectLanguageFromCode(): rough heuristic language detection
 * - renderResult()        : builds an HTML element for inline display
 * - formatResultAsMarkdown(): serialises result to markdown (for chat bubbles)
 */

import { createElement } from '../utils/helpers';

export interface CodeIssue {
  line: number | null;
  severity: 'error' | 'warning' | 'info';
  message: string;
}

export interface CodeReviewResult {
  review: string;
  issues: CodeIssue[];
  suggestions: string[];
}

/** Regex patterns that suggest the text is code. */
const CODE_PATTERNS = [
  /^\s*(import |from .+ import )/m,           // Python / JS imports
  /^\s*(function |const |let |var )\w+/m,      // JS/TS functions/vars
  /^\s*(class |def |interface |type )\w+/m,   // OOP keywords
  /^\s*(public|private|protected) .+\(/m,     // Java/C# methods
  /[{};]\s*$/m,                                // C-style braces/semicolons
  /^\s*#include\s*</m,                         // C/C++ includes
  /^\s*(fn |pub |use |mod )\w+/m,             // Rust
  /^\s*(func |package )\w+/m,                  // Go
  /=>\s*{/,                                    // Arrow functions
  /\$\w+\s*=/,                                 // PHP/shell variables
];

/** Severity → icon map */
const SEVERITY_ICONS: Record<string, string> = {
  error: '🔴',
  warning: '🟡',
  info: '🔵',
};

class CodeReviewService {
  private readonly endpoint = '/api/code/review';

  /**
   * Returns true if the given text looks like a code snippet.
   * Intentionally lenient — false positives are fine, false negatives are not.
   */
  looksLikeCode(text: string): boolean {
    return CODE_PATTERNS.some((re) => re.test(text));
  }

  /**
   * Rough language detection from code content.
   * Returns a string like "python", "typescript", "javascript", etc.
   */
  detectLanguageFromCode(code: string): string {
    if (/^\s*(import |from .+ import |def |class |elif |print\()/m.test(code)) return 'python';
    if (/^\s*(fn |pub |use |let mut |impl )/m.test(code)) return 'rust';
    if (/^\s*(package |func |import ")/m.test(code)) return 'go';
    if (/^\s*#include\s*</m.test(code)) return 'cpp';
    if (/^\s*(interface |type .+ = |as \w+|: \w+\[\])/m.test(code)) return 'typescript';
    if (/^\s*(function |const |let |var |=>)/m.test(code)) return 'javascript';
    if (/^\s*(public|private|protected) .+(class |void |int |String)/m.test(code)) return 'java';
    if (/^\s*\$\w+\s*=/m.test(code)) return 'php';
    if (/^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE)/im.test(code)) return 'sql';
    if (/^\s*<[a-z]+/m.test(code)) return 'html';
    return 'unknown';
  }

  /** Call the backend review endpoint. Throws on HTTP error. */
  async review(code: string, language = 'unknown', context = ''): Promise<CodeReviewResult> {
    const res = await fetch(this.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, language, context }),
    });

    if (!res.ok) {
      throw new Error(`Code review request failed: ${res.status} ${res.statusText}`);
    }

    return res.json() as Promise<CodeReviewResult>;
  }

  /**
   * Build an inline HTML element displaying the review result.
   * Designed to be inserted right after a <pre> block.
   */
  renderResult(result: CodeReviewResult): HTMLElement {
    const container = createElement('div', { className: 'code-review-result' });

    // Header
    const header = createElement('div', { className: 'code-review-result-header' });
    header.textContent = '🔍 AI Code Review';

    // Close button
    const closeBtn = createElement('button', {
      className: 'code-review-result-close',
      type: 'button',
      title: 'Dismiss review',
    }, '✕');
    closeBtn.addEventListener('click', () => container.remove());
    header.appendChild(closeBtn);

    // Overall review
    const reviewEl = createElement('p', { className: 'code-review-summary' });
    reviewEl.textContent = result.review;

    container.appendChild(header);
    container.appendChild(reviewEl);

    // Issues list
    if (result.issues.length > 0) {
      const issuesHeader = createElement('div', { className: 'code-review-section-title' });
      issuesHeader.textContent = `Issues (${result.issues.length})`;
      container.appendChild(issuesHeader);

      const issuesList = createElement('ul', { className: 'code-review-issues' });
      result.issues.forEach((issue) => {
        const li = createElement('li', {
          className: `code-review-issue code-review-issue-${issue.severity}`,
        });
        const icon = SEVERITY_ICONS[issue.severity] || '⚪';
        const lineTag = issue.line ? ` (line ${issue.line})` : '';
        li.textContent = `${icon} ${issue.message}${lineTag}`;
        issuesList.appendChild(li);
      });
      container.appendChild(issuesList);
    } else {
      const noIssues = createElement('p', { className: 'code-review-no-issues' });
      noIssues.textContent = '✅ No significant issues found.';
      container.appendChild(noIssues);
    }

    // Suggestions list
    if (result.suggestions.length > 0) {
      const sugHeader = createElement('div', { className: 'code-review-section-title' });
      sugHeader.textContent = 'Suggestions';
      container.appendChild(sugHeader);

      const sugList = createElement('ul', { className: 'code-review-suggestions' });
      result.suggestions.forEach((sug) => {
        const li = createElement('li', { className: 'code-review-suggestion' });
        li.textContent = `💡 ${sug}`;
        sugList.appendChild(li);
      });
      container.appendChild(sugList);
    }

    return container;
  }

  /**
   * Serialise a review result as a markdown string for chat bubble display.
   * Used when the review is triggered from the paste banner.
   */
  formatResultAsMarkdown(result: CodeReviewResult): string {
    const lines: string[] = ['### 🔍 AI Code Review', '', result.review];

    if (result.issues.length > 0) {
      lines.push('', '**Issues:**');
      result.issues.forEach((issue) => {
        const icon = SEVERITY_ICONS[issue.severity] || '⚪';
        const lineTag = issue.line ? ` *(line ${issue.line})*` : '';
        lines.push(`- ${icon} ${issue.message}${lineTag}`);
      });
    } else {
      lines.push('', '✅ No significant issues found.');
    }

    if (result.suggestions.length > 0) {
      lines.push('', '**Suggestions:**');
      result.suggestions.forEach((sug) => lines.push(`- 💡 ${sug}`));
    }

    return lines.join('\n');
  }
}

export const codeReviewService = new CodeReviewService();
