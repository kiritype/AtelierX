import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { t } from '../i18n';

export function Dialog({
  title,
  children,
  onClose,
  actions,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  actions?: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog">
        <h3>{title}</h3>
        {children}
        <div className="actions">
          <button onClick={onClose}>{t('common.cancel')}</button>
          {actions}
        </div>
      </div>
    </div>
  );
}

export function ChipsInput({
  values,
  onChange,
  placeholder,
  accent,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  accent?: (value: string) => boolean;
}) {
  const [draft, setDraft] = useState('');
  function commit() {
    const value = draft.trim();
    if (value && !values.some((v) => v.toLowerCase() === value.toLowerCase())) onChange([...values, value]);
    setDraft('');
  }
  return (
    <div className="chips-input">
      {values.map((value) => (
        <span key={value} className={`chip${accent?.(value) ? ' accent' : ''}`}>
          {value}
          <button onClick={() => onChange(values.filter((v) => v !== value))} aria-label={t('common.remove')}>
            ×
          </button>
        </span>
      ))}
      <input
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit();
          } else if (e.key === 'Backspace' && !draft && values.length) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={commit}
      />
    </div>
  );
}

export type MenuItem = { label: string; run: () => void; danger?: boolean } | null;

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    window.addEventListener('mousedown', close);
    return () => window.removeEventListener('mousedown', close);
  }, [onClose]);
  return (
    <div className="ctx" ref={ref} style={{ left: x, top: y }}>
      {items.map((item, i) =>
        item ? (
          <button
            key={i}
            className={item.danger ? 'danger' : undefined}
            onClick={() => {
              onClose();
              item.run();
            }}
          >
            {item.label}
          </button>
        ) : (
          <hr key={i} style={{ border: 0, borderTop: '1px solid var(--border)', margin: '4px 0' }} />
        ),
      )}
    </div>
  );
}

export function formatBytes(n: number) {
  return `${n.toLocaleString()} B`;
}

// Keeps one broken tab or screen from blanking the whole window.
export class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty">
        <p className="error-text">{t('common.crashed', { name: this.props.label ?? '' })}</p>
        <pre className="mono faint" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
          {String(this.state.error.message)}
        </pre>
        <button onClick={() => this.setState({ error: null })}>{t('common.retry')}</button>
      </div>
    );
  }
}
