import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { placeTip, splitShortcut } from '../lib/tooltip';

const DELAY = 300;

// The element a pointer or focus is on, with its `title` moved to `data-tip` so the browser's own tooltip stays away.
// An element whose only name was the title keeps it as its accessible name.
function tipTarget(node: EventTarget | null): HTMLElement | null {
  const el = node instanceof Element ? node.closest('[title], [data-tip]') : null;
  if (!(el instanceof HTMLElement)) return null;
  const title = el.getAttribute('title');
  if (title) {
    el.dataset.tip = title;
    el.removeAttribute('title');
    if (!el.getAttribute('aria-label') && !el.textContent?.trim()) el.setAttribute('aria-label', title);
  }
  return el.dataset.tip ? el : null;
}

export default function TooltipLayer() {
  const [shown, setShown] = useState<{ el: HTMLElement; text: string } | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const tip = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let timer: number | undefined;
    let current: HTMLElement | null = null;
    const hide = () => {
      window.clearTimeout(timer);
      current = null;
      setShown(null);
    };
    const show = (el: HTMLElement | null) => {
      if (el === current) return;
      hide();
      if (!el) return;
      current = el;
      timer = window.setTimeout(() => {
        if (current === el && el.isConnected) setShown({ el, text: el.dataset.tip ?? '' });
      }, DELAY);
    };
    const over = (e: PointerEvent) => show(tipTarget(e.target));
    const out = (e: PointerEvent) => {
      if (current && !current.contains(e.relatedTarget as Node | null)) hide();
    };
    const focus = (e: FocusEvent) => {
      const el = e.target instanceof HTMLElement && e.target.matches(':focus-visible') ? tipTarget(e.target) : null;
      if (el) show(el);
    };
    const key = (e: KeyboardEvent) => e.key === 'Escape' && hide();
    document.addEventListener('pointerover', over);
    document.addEventListener('pointerout', out);
    document.addEventListener('focusin', focus);
    document.addEventListener('focusout', hide);
    document.addEventListener('pointerdown', hide, true);
    document.addEventListener('keydown', key);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('blur', hide);
    return () => {
      hide();
      document.removeEventListener('pointerover', over);
      document.removeEventListener('pointerout', out);
      document.removeEventListener('focusin', focus);
      document.removeEventListener('focusout', hide);
      document.removeEventListener('pointerdown', hide, true);
      document.removeEventListener('keydown', key);
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('blur', hide);
    };
  }, []);

  useLayoutEffect(() => {
    if (!shown || !tip.current) return setPos(null);
    const box = tip.current.getBoundingClientRect();
    setPos(placeTip(shown.el.getBoundingClientRect(), box, { width: window.innerWidth, height: window.innerHeight }));
  }, [shown]);

  if (!shown?.text) return null;
  const { label, keys } = splitShortcut(shown.text);
  return (
    <div ref={tip} className="tooltip" role="tooltip" style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden', left: 0, top: 0 }}>
      {label}
      {keys && <kbd>{keys}</kbd>}
    </div>
  );
}
