import { useEffect, useRef, useState } from 'react';
import { get } from '../api';
import { bracketOpen, pasteInto, splitPrompt } from '../lib/tags';

type Suggestion = { tag: string; category: string; count: number; alias?: string };

// Image prompt tags as chips with dictionary autocomplete (data/tags/*.csv). Enter or comma adds a tag;
// the saved spelling is what the user picked or typed (spaces are kept).
export default function TagInput({
  values,
  onChange,
  placeholder,
  disabled,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [text, setText] = useState('');
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const query = text.trim();
    if (query.length < 2) {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const result = await get<{ tags: Suggestion[] }>(`/api/image/tags/complete?q=${encodeURIComponent(query)}`);
        setSuggestions(result.tags.slice(0, 10));
        setIndex(0);
      } catch {
        setSuggestions([]);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [text]);

  // Commas and line breaks outside brackets separate tags: a weighted group "(a, b:1.2)" stays one (#148).
  const add = (raw: string) => {
    const tags = splitPrompt(raw);
    if (tags.length) onChange([...values, ...tags.filter((x) => !values.includes(x))]);
    setText('');
    setSuggestions([]);
  };

  return (
    <div className={`chips-input tag-input${disabled ? ' disabled' : ''}`} onClick={() => input.current?.focus()}>
      {values.map((tag, n) => (
        <span key={`${tag}-${n}`} className="chip">
          {tag}
          {!disabled && (
            <button className="x" onClick={() => onChange(values.filter((_, i) => i !== n))}>
              ×
            </button>
          )}
        </span>
      ))}
      {!disabled && (
        <span className="tag-entry">
          <input
            ref={input}
            value={text}
            placeholder={values.length ? '' : placeholder}
            onChange={(e) => {
              // A comma ends the tag unless a bracket is still open (typing "(upper body, straight-on:1.4)").
              if (e.target.value.includes(',') && !bracketOpen(e.target.value)) add(e.target.value);
              else setText(e.target.value);
            }}
            onPaste={(e) => {
              // A one-line input turns pasted line breaks into spaces; take the clipboard text as it is.
              // What is pasted replaces the selection (or goes in at the caret), as a plain paste would.
              const pasted = e.clipboardData.getData('text');
              if (!/[,\n]/.test(pasted)) return;
              e.preventDefault();
              const { selectionStart, selectionEnd } = e.currentTarget;
              add(pasteInto(text, selectionStart ?? text.length, selectionEnd ?? text.length, pasted));
            }}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return;
              if (e.key === 'ArrowDown' && suggestions.length) {
                e.preventDefault();
                setIndex((i) => Math.min(i + 1, suggestions.length - 1));
              } else if (e.key === 'ArrowUp' && suggestions.length) {
                e.preventDefault();
                setIndex((i) => Math.max(i - 1, 0));
              } else if (e.key === 'Enter') {
                e.preventDefault();
                // Enter takes the highlighted suggestion; Shift+Enter (or a comma) keeps exactly what was typed.
                add(suggestions[index] && !e.shiftKey ? suggestions[index].tag : text);
              } else if (e.key === 'Tab' && suggestions[index]) {
                e.preventDefault();
                add(suggestions[index].tag);
              } else if (e.key === 'Escape') {
                setSuggestions([]);
              } else if (e.key === 'Backspace' && !text && values.length) {
                onChange(values.slice(0, -1));
              }
            }}
            onBlur={() => setTimeout(() => setSuggestions([]), 150)}
          />
          {suggestions.length > 0 && (
            <div className="tag-suggest">
              {suggestions.map((s, n) => (
                <div key={s.tag} className={`tag-option${n === index ? ' on' : ''}`} onMouseDown={(e) => (e.preventDefault(), add(s.tag))}>
                  <span className={`cat-${s.category}`}>{s.tag}</span>
                  {s.alias && <span className="faint"> ← {s.alias}</span>}
                  <span className="grow" />
                  <span className="faint">{s.count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          )}
        </span>
      )}
    </div>
  );
}
