import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { javascript } from '@codemirror/lang-javascript';
import { markdown } from '@codemirror/lang-markdown';
import { defaultHighlightStyle, HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { Annotation, EditorState, Transaction } from '@codemirror/state';
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { tags } from '@lezer/highlight';
import { useEffect, useRef } from 'react';

const external = Annotation.define<boolean>();

const base = {
  '&': { backgroundColor: 'var(--panel)', color: 'var(--text)' },
  '.cm-content': { padding: '14px 0', caretColor: 'var(--text)' },
  '.cm-gutters': { backgroundColor: 'var(--panel)', color: 'var(--text-3)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'transparent' },
  '.cm-line': { padding: '0 20px' },
};

// Prose (prompts, lorebook, characters, notes) reads like a document; JSX keeps a fixed-width font.
const proseTheme = EditorView.theme({
  ...base,
  '&': { ...base['&'], fontSize: 'var(--editor-size)' },
  '.cm-content': { ...base['.cm-content'], fontFamily: 'var(--sans)', lineHeight: '1.6', maxWidth: '920px' },
  '.cm-gutters': { ...base['.cm-gutters'], fontFamily: 'var(--mono)', fontSize: '12px' },
});
const codeTheme = EditorView.theme({
  ...base,
  '&': { ...base['&'], fontSize: '13px' },
  '.cm-content': { ...base['.cm-content'], fontFamily: 'var(--mono)' },
});

// Headings stand out by size and weight instead of the default underline; the `#` marks stay visible.
const markdownStyle = HighlightStyle.define([
  { tag: tags.heading1, fontSize: '1.4em', fontWeight: '700' },
  { tag: tags.heading2, fontSize: '1.2em', fontWeight: '700' },
  { tag: [tags.heading3, tags.heading4, tags.heading5, tags.heading6], fontWeight: '700' },
  { tag: tags.processingInstruction, color: 'var(--accent)' },
  { tag: tags.strong, fontWeight: '700' },
  { tag: tags.emphasis, fontStyle: 'italic' },
  { tag: tags.link, color: 'var(--accent)' },
  { tag: tags.url, color: 'var(--text-3)' },
  { tag: tags.quote, color: 'var(--text-2)' },
  { tag: tags.monospace, fontFamily: 'var(--mono)', fontSize: '0.92em' },
  { tag: tags.contentSeparator, color: 'var(--text-3)' },
]);

// The editor owns its text; the parent gets changes through onChange and replaces the text only when `doc` changes
// identity from outside (reload from disk).
export default function CodeEditor({
  value,
  language,
  onChange,
  onSave,
  onAttach,
}: {
  value: string;
  language: 'markdown' | 'jsx';
  onChange: (value: string) => void;
  onSave?: () => void;
  // Ctrl+L: the selected lines (1-based, inclusive) and text, for the agent panel.
  onAttach?: (selection: { from: number; to: number; text: string }) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const handlers = useRef({ onChange, onSave, onAttach });
  handlers.current = { onChange, onSave, onAttach };

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        history(),
        keymap.of([
          { key: 'Mod-s', run: () => (handlers.current.onSave?.(), true) },
          {
            key: 'Mod-l',
            run: (editor) => {
              if (!handlers.current.onAttach) return false;
              const range = editor.state.selection.main;
              const first = editor.state.doc.lineAt(range.from);
              const last = editor.state.doc.lineAt(range.empty ? range.to : Math.max(range.from, range.to - 1));
              const text = range.empty ? first.text : editor.state.sliceDoc(range.from, range.to);
              handlers.current.onAttach({ from: first.number, to: last.number, text });
              return true;
            },
          },
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.lineWrapping,
        ...(language === 'jsx'
          ? [syntaxHighlighting(defaultHighlightStyle), javascript({ jsx: true }), codeTheme]
          : [syntaxHighlighting(markdownStyle), markdown(), proseTheme]),
        EditorView.updateListener.of((update) => {
          // Text put in from outside (the loaded file, a reload) is not an edit of the user's.
          if (update.docChanged && !update.transactions.some((tr) => tr.annotation(external))) {
            handlers.current.onChange(update.state.doc.toString());
          }
        }),
      ],
    });
    view.current = new EditorView({ state, parent: host.current! });
    return () => view.current?.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  useEffect(() => {
    const current = view.current;
    if (current && current.state.doc.toString() !== value) {
      // Not an edit and not undoable: Ctrl+Z right after opening must not empty the document.
      current.dispatch({
        changes: { from: 0, to: current.state.doc.length, insert: value },
        annotations: [external.of(true), Transaction.addToHistory.of(false)],
      });
    }
  }, [value]);

  return <div className="cm-host" ref={host} />;
}
