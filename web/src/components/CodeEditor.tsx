import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { javascript } from '@codemirror/lang-javascript';
import { markdown } from '@codemirror/lang-markdown';
import { defaultHighlightStyle, HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { Annotation, EditorState, Transaction } from '@codemirror/state';
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { tags } from '@lezer/highlight';
import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n';
import { ContextMenu, type MenuItem } from './ui';

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
  menu,
}: {
  value: string;
  language: 'markdown' | 'jsx';
  onChange: (value: string) => void;
  onSave?: () => void;
  // Ctrl+L: the selected lines (1-based, inclusive) and text, for the agent panel.
  onAttach?: (selection: { from: number; to: number; text: string }) => void;
  // More entries for the right-click menu (and Alt+P), for the selected text (#150).
  menu?: (selection: { text: string }) => MenuItem[];
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const handlers = useRef({ onChange, onSave, onAttach, menu });
  handlers.current = { onChange, onSave, onAttach, menu };
  const [opened, setOpened] = useState<{ x: number; y: number; text: string } | null>(null);

  function selection(editor: EditorView) {
    const range = editor.state.selection.main;
    const first = editor.state.doc.lineAt(range.from);
    const last = editor.state.doc.lineAt(range.empty ? range.to : Math.max(range.from, range.to - 1));
    const text = range.empty ? first.text : editor.state.sliceDoc(range.from, range.to);
    return { from: first.number, to: last.number, text, selected: editor.state.sliceDoc(range.from, range.to) };
  }
  function attach(editor: EditorView) {
    if (!handlers.current.onAttach) return false;
    const { from, to, text } = selection(editor);
    handlers.current.onAttach({ from, to, text });
    return true;
  }
  function openMenu(x: number, y: number) {
    const editor = view.current;
    if (!editor) return false;
    setOpened({ x, y, text: selection(editor).selected });
    return true;
  }
  function menuItems(text: string): MenuItem[] {
    const editor = view.current!;
    const range = editor.state.selection.main;
    const items: MenuItem[] = [
      {
        label: t('editor.menu.cut'),
        hint: 'Ctrl+X',
        disabled: range.empty,
        run: () => {
          void navigator.clipboard.writeText(text);
          editor.dispatch({ changes: { from: range.from, to: range.to, insert: '' } });
        },
      },
      { label: t('editor.menu.copy'), hint: 'Ctrl+C', disabled: range.empty, run: () => void navigator.clipboard.writeText(text) },
    ];
    if (handlers.current.onAttach) items.push({ label: t('editor.menu.attach'), hint: 'Ctrl+L', run: () => attach(editor) });
    const more = handlers.current.menu?.({ text }) ?? [];
    return more.length ? [...items, null, ...more] : items;
  }

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        history(),
        keymap.of([
          { key: 'Mod-s', run: () => (handlers.current.onSave?.(), true) },
          { key: 'Mod-l', run: (editor) => attach(editor) },
          {
            // The same menu as a right click, at the cursor.
            key: 'Alt-p',
            run: (editor) => {
              if (!handlers.current.menu) return false;
              const at = editor.coordsAtPos(editor.state.selection.main.head);
              return openMenu(at?.left ?? 100, (at?.bottom ?? 100) + 2);
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

  return (
    <>
      <div
        className="cm-host"
        ref={host}
        onContextMenu={(e) => {
          if (!handlers.current.menu && !handlers.current.onAttach) return;
          e.preventDefault();
          openMenu(e.clientX, e.clientY);
        }}
      />
      {opened && (
        <ContextMenu
          x={opened.x}
          y={opened.y}
          items={menuItems(opened.text)}
          onClose={() => {
            setOpened(null);
            view.current?.focus();
          }}
        />
      )}
    </>
  );
}
