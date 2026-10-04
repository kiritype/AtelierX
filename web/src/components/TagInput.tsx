import { useEffect, useRef, useState } from 'react';
import { get } from '../api';

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

  const add = (raw: string) => {
    const tags = raw
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean);
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
              if (e.target.value.includes(',')) add(e.target.value);
              else setText(e.target.value);
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
