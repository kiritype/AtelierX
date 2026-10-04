import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { javascript } from '@codemirror/lang-javascript';
import { markdown } from '@codemirror/lang-markdown';
import { defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers } from '@codemirror/view';
import { useEffect, useRef } from 'react';

const theme = EditorView.theme({
  '&': { fontSize: '13px', backgroundColor: 'var(--panel)', color: 'var(--text)' },
  '.cm-content': { fontFamily: 'var(--mono)', padding: '12px 0', caretColor: 'var(--text)' },
  '.cm-gutters': { backgroundColor: 'var(--panel)', color: 'var(--text-3)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'transparent' },
  '.cm-line': { padding: '0 16px' },
});

// The editor owns its text; the parent gets changes through onChange and replaces the text only when `doc` changes
// identity from outside (reload from disk).
export default function CodeEditor({
  value,
  language,
  onChange,
  onSave,
}: {
  value: string;
  language: 'markdown' | 'jsx';
  onChange: (value: string) => void;
  onSave?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const handlers = useRef({ onChange, onSave });
  handlers.current = { onChange, onSave };

  useEffect(() => {
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        history(),
        keymap.of([
          { key: 'Mod-s', run: () => (handlers.current.onSave?.(), true) },
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.lineWrapping,
        syntaxHighlighting(defaultHighlightStyle),
        language === 'jsx' ? javascript({ jsx: true }) : markdown(),
        theme,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) handlers.current.onChange(update.state.doc.toString());
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
      current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: value } });
    }
  }, [value]);

  return <div className="cm-host" ref={host} />;
}
