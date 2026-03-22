/**
 * CodeMirror 6 Editor wrapper for CardDetailModal.
 * Provides markdown editing with syntax highlighting, code block support,
 * and auto-save on blur.
 */
import { EditorState } from '@codemirror/state';
import { EditorView, keymap, placeholder, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view';
import { markdown, markdownLanguage } from '@codemirror/lang-markdown';
import { javascript } from '@codemirror/lang-javascript';
import { python } from '@codemirror/lang-python';
import { oneDark } from '@codemirror/theme-one-dark';
import { defaultKeymap, indentWithTab, history, historyKeymap } from '@codemirror/commands';
import { syntaxHighlighting, defaultHighlightStyle, indentOnInput, bracketMatching, LanguageDescription } from '@codemirror/language';

export interface CodeMirrorEditorOptions {
  initialValue: string;
  onSave: (value: string) => void;
  placeholderText?: string;
}

export class CodeMirrorEditor {
  private view: EditorView | null = null;
  private container: HTMLElement;
  private onSave: (value: string) => void;
  private lastSavedValue: string;

  constructor(options: CodeMirrorEditorOptions) {
    this.container = document.createElement('div');
    this.container.className = 'codemirror-editor-container';
    this.onSave = options.onSave;
    this.lastSavedValue = options.initialValue;
    this.createEditor(options.initialValue, options.placeholderText || '');
  }

  private isDarkTheme(): boolean {
    return document.documentElement.getAttribute('data-theme') !== 'light';
  }

  private getExtensions(placeholderText: string) {
    const extensions = [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      history(),
      indentOnInput(),
      bracketMatching(),
      markdown({
        base: markdownLanguage,
        codeLanguages: [
          LanguageDescription.of({ name: 'javascript', alias: ['js', 'ts', 'typescript'], load: async () => javascript() }),
          LanguageDescription.of({ name: 'python', alias: ['py'], load: async () => python() }),
        ],
      }),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      placeholder(placeholderText),
      EditorView.lineWrapping,
      // Auto-save on blur
      EditorView.domEventHandlers({
        blur: () => {
          this.saveIfChanged();
        },
      }),
    ];

    if (this.isDarkTheme()) {
      extensions.push(oneDark);
    }

    // Custom styling
    extensions.push(EditorView.theme({
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
    }));

    return extensions;
  }

  private createEditor(initialValue: string, placeholderText: string): void {
    const state = EditorState.create({
      doc: initialValue,
      extensions: this.getExtensions(placeholderText),
    });

    this.view = new EditorView({
      state,
      parent: this.container,
    });
  }

  private saveIfChanged(): void {
    if (!this.view) return;
    const currentValue = this.view.state.doc.toString();
    if (currentValue !== this.lastSavedValue) {
      this.lastSavedValue = currentValue;
      this.onSave(currentValue);
    }
  }

  getValue(): string {
    return this.view ? this.view.state.doc.toString() : '';
  }

  setValue(value: string): void {
    if (!this.view) return;
    this.view.dispatch({
      changes: { from: 0, to: this.view.state.doc.length, insert: value },
    });
    this.lastSavedValue = value;
  }

  getElement(): HTMLElement {
    return this.container;
  }

  /** Rebuild the editor with new theme extensions (call on theme change). */
  refreshTheme(): void {
    if (!this.view) return;
    const currentValue = this.view.state.doc.toString();
    const placeholderText = 'Write card description... (Markdown supported)';
    this.view.destroy();
    this.createEditor(currentValue, placeholderText);
    this.lastSavedValue = currentValue;
  }

  destroy(): void {
    this.saveIfChanged();
    if (this.view) {
      this.view.destroy();
      this.view = null;
    }
  }
}
