import { useEffect, useRef, type ReactNode } from 'react';
import './GalleryDetailFrame.css';

// Shared image-and-details modal for the gallery and single-generation results.
export default function GalleryDetailFrame({ imageUrl, label, close, children, imageOverlay }: {
  imageUrl: string;
  label: string;
  close: () => void;
  children: ReactNode;
  imageOverlay?: ReactNode;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      } else if (event.key === 'Tab' && dialog.current) {
        const focusable = [...dialog.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        )];
        if (!focusable.length) { event.preventDefault(); dialog.current.focus(); return; }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current || !dialog.current.contains(document.activeElement))) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current || !dialog.current.contains(document.activeElement))) {
          event.preventDefault(); first.focus();
        }
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => { window.removeEventListener('keydown', onKey, true); previous?.focus(); };
  }, []);

  return <div className="overlay" onMouseDown={event => event.target === event.currentTarget && closeRef.current()}>
    <div ref={dialog} className="gallery-detail gallery-detail-frame" role="dialog" aria-modal="true" aria-label={label} tabIndex={-1}>
      <div className="gallery-detail-image"><img src={imageUrl} alt="" />{imageOverlay}</div>
      <div className="gallery-detail-side col pad">{children}</div>
    </div>
  </div>;
}
