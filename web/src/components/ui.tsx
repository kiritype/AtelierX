import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { t } from '../i18n';

export function Dialog({
  title,
  children,
  onClose,
  actions,
  closeLabel,
  className,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  actions?: React.ReactNode;
  // Dialogs that only show something say "close" instead of "cancel".
  closeLabel?: string;
  className?: string;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={className ? `dialog ${className}` : 'dialog'}>
        <h3>{title}</h3>
        {children}
        <div className="actions">
          <button onClick={onClose}>{closeLabel ?? t('common.cancel')}</button>
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

// An entry runs something, or opens a submenu of its own entries (#150); `hint` shows its key on the right.
export type MenuItem = { label: string; run?: () => void; danger?: boolean; disabled?: boolean; hint?: string; items?: MenuItem[] } | null;

export function ContextMenu({ x, y, items, onClose }: { x: number; y: number; items: MenuItem[]; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    const escape = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('mousedown', close);
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', escape);
    };
  }, [onClose]);
  return (
    <div ref={ref}>
      <MenuList x={x} y={y} items={items} onClose={onClose} />
    </div>
  );
}

function MenuList({ x, y, from, items, onClose }: { x: number; y: number; from?: number; items: MenuItem[]; onClose: () => void }) {
  const [open, setOpen] = useState<{ index: number; x: number; y: number; from: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  // Kept inside the window: a menu opened near the right or bottom edge moves back in.
  const [place, setPlace] = useState({ left: x, top: y });
  useEffect(() => {
    const box = ref.current?.getBoundingClientRect();
    if (!box) return;
    // A submenu with no room on the right opens on the left of its parent.
    const left = x + box.width > window.innerWidth - 4 && from !== undefined ? from - box.width + 2 : x;
    setPlace({ left: Math.max(4, Math.min(left, window.innerWidth - box.width - 4)), top: Math.max(4, Math.min(y, window.innerHeight - box.height - 4)) });
  }, [x, y, from]);
  const sub = open !== null ? items[open.index] : null;
  return (
    <>
      <div className="ctx" ref={ref} style={place} role="menu">
        {items.map((item, i) =>
          item ? (
            <button
              key={i}
              role="menuitem"
              disabled={item.disabled}
              className={`${item.danger ? 'danger' : ''}${open?.index === i ? ' open' : ''}`}
              onMouseEnter={(e) => {
                const box = e.currentTarget.getBoundingClientRect();
                setOpen(item.items ? { index: i, x: box.right - 2, y: box.top - 4, from: box.left } : null);
              }}
              onClick={(e) => {
                if (item.items) {
                  const box = e.currentTarget.getBoundingClientRect();
                  setOpen({ index: i, x: box.right - 2, y: box.top - 4, from: box.left });
                  return;
                }
                onClose();
                item.run?.();
              }}
            >
              <span className="grow">{item.label}</span>
              {item.hint && <span className="ctx-hint">{item.hint}</span>}
              {item.items && <span className="ctx-hint">▸</span>}
            </button>
          ) : (
            <hr key={i} style={{ border: 0, borderTop: '1px solid var(--border)', margin: '4px 0' }} />
          ),
        )}
      </div>
      {sub?.items && open && <MenuList key={open.index} x={open.x} y={open.y} from={open.from} items={sub.items} onClose={onClose} />}
    </>
  );
}

export function formatBytes(n: number) {
  return `${n.toLocaleString()} B`;
}

// Keeps one broken tab or screen from blanking the whole window.
// Shown while a screen's code is read for the first time (#83).
export function Loading() {
  return <div className="empty">{t('common.loading')}</div>;
}

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
