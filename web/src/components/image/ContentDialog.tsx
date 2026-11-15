import { useEffect, useId, useRef, type ReactNode } from 'react';
import { t } from '../../i18n';

/** One keyboard-accessible dialog for content import and dependency preparation. */
export default function ContentDialog({ title, children, onClose, closeLabel, actions }: {
  title: string; children: ReactNode; onClose: () => void; closeLabel?: string; actions?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key !== 'Tab') return;
      const controls = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], summary, [tabindex="0"]') ?? [])].filter(el => !el.hidden && !el.closest('[hidden]'));
      const first = controls[0], last = controls.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) { event.preventDefault(); first.focus(); }
    };
    const dialog = ref.current;
    dialog?.addEventListener('keydown', key);
    return () => { dialog?.removeEventListener('keydown', key); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog wide" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
      <h3 id={titleId}>{title}</h3>{children}<div className="actions"><button onClick={onClose}>{closeLabel ?? t('common.close')}</button>{actions}</div>
    </div>
  </div>;
}
