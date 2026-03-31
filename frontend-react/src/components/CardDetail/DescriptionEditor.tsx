/**
 * DescriptionEditor — CodeMirror 6 markdown editor for card descriptions.
 * Port of the vanilla CodeMirrorEditor class.
 *
 * Uses @uiw/react-codemirror for React integration.
 * Features: markdown syntax highlighting, JS/Python code block support,
 * line numbers, dark/light theme sync, auto-save on blur.
 */

import { useCallback, useMemo } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { EditorView } from '@codemirror/view';
import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { tags } from '@lezer/highlight';
import { LanguageDescription } from '@codemirror/language';
import { useThemeStore } from '../../stores/useThemeStore';

// ── Theme built from CSS variables ───────────────────────────────────────────
// Applied in both modes so the editor always matches the app surface colors.

const baseTheme = EditorView.theme({
  '&': {
    minHeight: '300px',
    maxHeight: '100%',
    fontSize: '14px',
    flex: '1',
    backgroundColor: 'hsl(var(--card))',
    color: 'hsl(var(--card-foreground))',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
  },
  '.cm-content': {
    minHeight: '280px',
    padding: '8px 0',
    caretColor: 'hsl(var(--foreground))',
  },
  '.cm-cursor': {
    borderLeftColor: 'hsl(var(--foreground))',
  },
  '.cm-gutters': {
    backgroundColor: 'hsl(var(--card))',
    color: 'hsl(var(--muted-foreground))',
    borderRight: '1px solid hsl(var(--border))',
  },
  '.cm-activeLineGutter': {
    backgroundColor: 'hsl(var(--accent))',
  },
  '.cm-activeLine': {
    backgroundColor: 'hsl(var(--accent) / 0.5)',
  },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground': {
    backgroundColor: 'hsl(var(--accent))',
  },
  '.cm-selectionMatch': {
    backgroundColor: 'hsl(var(--accent) / 0.4)',
  },
  '&.cm-focused': {
    outline: 'none',
  },
  '.cm-line': {
    color: 'hsl(var(--foreground))',
  },
});

// ── Syntax highlighting that works in both light and dark ────────────────────

const darkHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: tags.heading,         color: '#e5c07b', fontWeight: 'bold' },
    { tag: tags.strong,          fontWeight: 'bold' },
    { tag: tags.emphasis,        fontStyle: 'italic' },
    { tag: tags.strikethrough,   textDecoration: 'line-through' },
    { tag: tags.link,            color: '#61afef' },
    { tag: tags.url,             color: '#56b6c2' },
    { tag: tags.monospace,       color: '#98c379', fontFamily: 'monospace' },
    { tag: tags.keyword,         color: '#c678dd' },
    { tag: tags.string,          color: '#98c379' },
    { tag: tags.comment,         color: '#7d8799', fontStyle: 'italic' },
    { tag: tags.number,          color: '#d19a66' },
    { tag: tags.operator,        color: '#56b6c2' },
    { tag: tags.className,       color: '#e5c07b' },
    { tag: tags.definition(tags.variableName), color: '#e06c75' },
  ])
);

const lightHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: tags.heading,         color: '#a626a4', fontWeight: 'bold' },
    { tag: tags.strong,          fontWeight: 'bold' },
    { tag: tags.emphasis,        fontStyle: 'italic' },
    { tag: tags.strikethrough,   textDecoration: 'line-through' },
    { tag: tags.link,            color: '#4078f2' },
    { tag: tags.url,             color: '#0184bc' },
    { tag: tags.monospace,       color: '#50a14f', fontFamily: 'monospace' },
    { tag: tags.keyword,         color: '#a626a4' },
    { tag: tags.string,          color: '#50a14f' },
    { tag: tags.comment,         color: '#9d9d9d', fontStyle: 'italic' },
    { tag: tags.number,          color: '#986801' },
    { tag: tags.operator,        color: '#0184bc' },
    { tag: tags.className,       color: '#c18401' },
    { tag: tags.definition(tags.variableName), color: '#e45649' },
  ])
);

// ── Component ────────────────────────────────────────────────────────────────

interface Props {
  cardId: string;
  value: string;
  onChange: (value: string) => void;
}

export function DescriptionEditor({ cardId: _cardId, value, onChange }: Props) {
  const theme = useThemeStore((s) => s.theme);

  const extensions = useMemo(
    () => [
      markdown({
        base: markdownLanguage,
        codeLanguages: [
          LanguageDescription.of({
            name: 'javascript',
            alias: ['js', 'ts', 'typescript'],
            load: async () => javascript(),
          }),
          LanguageDescription.of({
            name: 'python',
            alias: ['py'],
            load: async () => python(),
          }),
        ],
      }),
      EditorView.lineWrapping,
      baseTheme,
      theme === 'dark' ? darkHighlight : lightHighlight,
    ],
    [theme],
  );

  const handleChange = useCallback(
    (val: string) => {
      onChange(val);
    },
    [onChange],
  );

  return (
    <div className="flex h-full flex-col [&_.cm-editor]:flex-1">
      <CodeMirror
        value={value}
        onChange={handleChange}
        extensions={extensions}
        theme="none"
        placeholder="Write card description… (Markdown supported)"
        basicSetup={{
          lineNumbers: true,
          highlightActiveLine: true,
          highlightActiveLineGutter: true,
          history: true,
          bracketMatching: true,
          indentOnInput: true,
          foldGutter: false,
        }}
      />
    </div>
  );
}
