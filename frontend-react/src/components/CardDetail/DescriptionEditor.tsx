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
import { oneDark } from '@codemirror/theme-one-dark';
import { EditorView } from '@codemirror/view';
import { LanguageDescription } from '@codemirror/language';
import { useThemeStore } from '../../stores/useThemeStore';

// ── Custom styling ───────────────────────────────────────────────────────────

const customTheme = EditorView.theme({
  '&': {
    minHeight: '300px',
    maxHeight: '100%',
    fontSize: '14px',
    flex: '1',
  },
  '.cm-scroller': {
    overflow: 'auto',
    fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
  },
  '.cm-content': {
    minHeight: '280px',
    padding: '8px 0',
  },
  '.cm-gutters': {
    borderRight: '1px solid var(--color-border, #333)',
    backgroundColor: 'transparent',
  },
  '&.cm-focused': {
    outline: 'none',
  },
});

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
      customTheme,
      ...(theme === 'dark' ? [oneDark] : []),
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
