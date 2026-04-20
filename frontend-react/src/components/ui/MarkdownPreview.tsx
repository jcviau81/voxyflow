/**
 * MarkdownPreview — Shared Markdown renderer for cards, wiki, and any preview surface.
 *
 * Features:
 *  • react-markdown v10 + remark-gfm (tables, task lists, strikethrough, autolink)
 *  • react-syntax-highlighter (Prism) for fenced code blocks
 *  • Tailwind Typography (`prose`) for rich h1-h6, bold, italic, blockquotes, links, lists
 *  • Dark/light aware: prose-invert in .dark scope, vscDarkPlus code theme always
 *  • Safe external links (target="_blank" rel="noopener noreferrer")
 *  • Copy button on code blocks
 */

import { useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Copy, Check } from 'lucide-react';
import { cn } from '../../lib/utils';

// ── Copy button for code blocks ──────────────────────────────────────────────

function CopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // clipboard not available
    }
  }, [code]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      title="Copy code"
      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-gray-400 transition-colors hover:bg-white/10 hover:text-gray-200 cursor-pointer"
    >
      {copied ? <Check size={10} /> : <Copy size={10} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface MarkdownPreviewProps {
  /** Markdown source string */
  value: string;
  /** Additional CSS classes applied to the outer wrapper */
  className?: string;
  /** Placeholder shown when value is empty */
  emptyText?: string;
}

/**
 * Render `value` as styled Markdown.
 *
 * Usage:
 * ```tsx
 * <MarkdownPreview value={description} />
 * ```
 */
export function MarkdownPreview({
  value,
  className,
  emptyText = 'No content yet…',
}: MarkdownPreviewProps) {
  if (!value?.trim()) {
    return (
      <p className="text-sm text-muted-foreground italic">{emptyText}</p>
    );
  }

  return (
    <div
      className={cn(
        // Tailwind Typography — requires @tailwindcss/typography plugin
        'prose prose-sm dark:prose-invert max-w-none',
        // Heading font override to match app theme (Geist Variable instead of Pixel)
        '[&_h1]:font-sans [&_h2]:font-sans [&_h3]:font-sans [&_h4]:font-sans [&_h5]:font-sans [&_h6]:font-sans',
        // Prevent overflow for wide content
        '[overflow-wrap:anywhere] [word-break:break-word]',
        '[&_pre]:overflow-x-auto [&_table]:block [&_table]:overflow-x-auto [&_img]:max-w-full',
        // Task list styling (GFM checkboxes)
        '[&_input[type=checkbox]]:mr-1.5 [&_input[type=checkbox]]:cursor-default',
        // Tighten up blockquote border color with theme
        '[&_blockquote]:border-l-border [&_blockquote]:text-muted-foreground',
        // Link colors
        '[&_a]:text-primary [&_a:hover]:underline',
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // ── Code blocks & inline code ──────────────────────────────────────
          code({ className: cls, children, ...props }) {
            const match = /language-(\w+)/.exec(cls ?? '');
            const isBlock = Boolean(cls?.startsWith('language-'));
            const codeString = String(children).replace(/\n$/, '');

            if (isBlock) {
              const lang = match?.[1] ?? 'text';
              return (
                <div className="relative my-3 overflow-hidden rounded-md border border-white/10">
                  {/* Header bar */}
                  <div className="flex items-center justify-between bg-[#1e1e2e] px-3 py-1.5">
                    <span className="font-mono text-[10px] uppercase tracking-wider text-gray-400">
                      {lang}
                    </span>
                    <CopyButton code={codeString} />
                  </div>
                  {/* Syntax-highlighted body */}
                  <SyntaxHighlighter
                    style={vscDarkPlus}
                    language={lang}
                    PreTag="div"
                    customStyle={{
                      margin: 0,
                      borderRadius: 0,
                      fontSize: '0.84em',
                      overflowX: 'auto',
                      background: '#1e1e2e',
                    }}
                    wrapLongLines={false}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                </div>
              );
            }

            // Inline code
            return (
              <code
                className="rounded bg-muted px-1 py-0.5 font-mono text-sm text-foreground"
                {...props}
              >
                {children}
              </code>
            );
          },

          // ── Links — always open in new tab ─────────────────────────────────
          a({ href, children }) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            );
          },

          // ── Tables — add scroll wrapper ────────────────────────────────────
          table({ children }) {
            return (
              <div className="overflow-x-auto">
                <table>{children}</table>
              </div>
            );
          },

          // ── Task list items (GFM) ──────────────────────────────────────────
          input({ type, checked, ...props }) {
            if (type === 'checkbox') {
              return (
                <input
                  type="checkbox"
                  checked={checked}
                  readOnly
                  className="mr-1.5 cursor-default rounded border-border accent-primary"
                  {...props}
                />
              );
            }
            return <input type={type} {...props} />;
          },
        }}
      >
        {value}
      </ReactMarkdown>
    </div>
  );
}
