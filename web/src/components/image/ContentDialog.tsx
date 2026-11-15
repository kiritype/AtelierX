import './contentDialog.css';
import { useEffect, useId, useLayoutEffect, useRef, type ReactNode } from 'react';
import { t } from '../../i18n';

/** One keyboard-accessible dialog for content import and dependency preparation. */
export default function ContentDialog({ title, children, onClose, closeLabel, actions }: {
  title: string; children: ReactNode; onClose: () => void; closeLabel?: string; actions?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const returnFocus = useRef(document.activeElement as HTMLElement | null);
  const close = useRef(onClose); close.current = onClose;
  useLayoutEffect(() => {
    if (ref.current && !ref.current.contains(document.activeElement)) ref.current.focus();
  }, [children]);
  useEffect(() => {
    const previous = returnFocus.current;
    ref.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close.current(); }
      if (event.key !== 'Tab') return;
      const controls = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href], summary, [tabindex="0"]') ?? [])].filter(el => { const collapsed = el.closest('details:not([open])'); return !el.hidden && !el.closest('[hidden]') && (!collapsed || el.tagName === 'SUMMARY' && el.parentElement === collapsed); });
      const first = controls[0], last = controls.at(-1);
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !ref.current?.contains(document.activeElement) || document.activeElement === ref.current)) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !ref.current?.contains(document.activeElement) || document.activeElement === ref.current)) { event.preventDefault(); first.focus(); }
    };
    const dialog = ref.current;
    document.addEventListener('keydown', key);
    const observer = new MutationObserver(() => { if (document.activeElement === document.body) ref.current?.focus(); });
    if (dialog) observer.observe(dialog, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled'] });
    return () => { observer.disconnect(); document.removeEventListener('keydown', key); if (previous?.isConnected) previous.focus(); };
  }, []);
  return <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <div className="dialog wide content-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
      <h3 id={titleId}>{title}</h3>{children}<div className="actions"><button onClick={onClose}>{closeLabel ?? t('common.close')}</button>{actions}</div>
    </div>
  </div>;
}
