import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from 'react';
import { Icon } from './icons';
import { t } from '../i18n';

// null draws a line; a heading names the group of items below it (not clickable).
export type MenuAction = { label: string; shortcut?: string; run: () => void; disabled?: boolean };
export type MenuEntry = MenuAction | { heading: string } | null;
export type Menu = { label: string; items: MenuEntry[] };

// Closes an open menu on a click outside `root` or on Escape.
function useDismiss(root: RefObject<HTMLElement | null>, isOpen: boolean, close: (restoreFocus?: boolean) => void) {
  useEffect(() => {
    if (!isOpen) return;
    const outside = (e: MouseEvent) => !root.current?.contains(e.target as Node) && close();
    const key = (e: KeyboardEvent) => e.key === 'Escape' && close(true);
    window.addEventListener('mousedown', outside);
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener('mousedown', outside);
      window.removeEventListener('keydown', key);
    };
  }, [root, isOpen, close]);
}

function menuItems(root: HTMLElement | null) {
  return Array.from(root?.querySelectorAll<HTMLButtonElement>('.menu-drop button:not(:disabled)') ?? []);
}

function moveItem(event: ReactKeyboardEvent, root: HTMLElement | null) {
  const { key } = event;
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) return;
  event.preventDefault();
  const buttons = menuItems(root);
  if (!buttons.length) return;
  const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
  let next = 0;
  if (key === 'ArrowDown') next = (current + 1) % buttons.length;
  if (key === 'ArrowUp') next = current <= 0 ? buttons.length - 1 : current - 1;
  if (key === 'End') next = buttons.length - 1;
  buttons[next].focus();
}

function MenuPopup({ id, labelledBy, items, done, last, right }: {
  id: string; labelledBy: string; items: MenuEntry[]; done: () => void; last: boolean; right?: boolean;
}) {
  const popup = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = popup.current;
    if (!element) return;
    const fit = () => {
      element.style.removeProperty('translate');
      const { left, right, top } = element.getBoundingClientRect();
      const shift = Math.max(8 - left, Math.min(0, window.innerWidth - 8 - right));
      element.style.translate = `${shift}px`;
      element.style.maxHeight = `${Math.max(0, window.innerHeight - top - 8)}px`;
    };
    fit();
    const buttons = element.querySelectorAll<HTMLButtonElement>('button:not(:disabled)');
    buttons[last ? buttons.length - 1 : 0]?.focus();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [last]);

  return (
    <div ref={popup} id={id} aria-labelledby={labelledBy} className={`menu-drop${right ? ' right' : ''}`} role="menu">
      {items.map((item, i) =>
        item === null ? (
          <div key={i} className="menu-sep" role="separator" />
        ) : 'heading' in item ? (
          <div key={i} className="menu-heading" role="presentation">
            {item.heading}
          </div>
        ) : (
          <button
            key={i}
            type="button"
            role="menuitem"
            tabIndex={-1}
            disabled={item.disabled}
            onClick={() => {
              done();
              item.run();
            }}
          >
            <span className="grow">{item.label}</span>
            {item.shortcut && <span className="menu-shortcut faint">{item.shortcut}</span>}
          </button>
        ),
      )}
    </div>
  );
}

// A button that opens a menu below it, right-aligned (for toolbars).
export function MenuButton({ label, items, className }: { label: ReactNode; items: MenuEntry[]; className?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const focusLast = useRef(false);
  const dismiss = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus();
  };
  useDismiss(root, open, dismiss);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const { key } = event;
    if (open && key === 'Escape') {
      event.stopPropagation();
      dismiss(true);
      return;
    }
    if (!open) {
      if (key === 'ArrowDown' || key === 'ArrowUp') {
        event.preventDefault();
        focusLast.current = key === 'ArrowUp';
        setOpen(true);
      }
      return;
    }
    moveItem(event, root.current);
  };

  return (
    <div className="menu-root" ref={root} onKeyDown={onKeyDown} onBlur={event => {
      if (open && !event.currentTarget.contains(event.relatedTarget)) dismiss();
    }}>
      <button
        type="button" id={`${id}-trigger`} ref={trigger} tabIndex={open ? -1 : 0}
        className={['menu-button', className, open ? 'on' : ''].filter(Boolean).join(' ')}
        aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
        onClick={() => { focusLast.current = false; setOpen(!open); }}
      >
        {label} <Icon name="menu" size={14} />
      </button>
      {open && <MenuPopup id={id} labelledBy={`${id}-trigger`} items={items} last={focusLast.current} done={() => dismiss(true)} right />}
    </div>
  );
}

// A desktop-style menu bar: click opens a menu, moving over another title while one is open switches to it.
export default function MenuBar({ menus }: { menus: Menu[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const [active, setActive] = useState(0);
  const id = useId();
  const bar = useRef<HTMLDivElement>(null);
  const triggers = useRef<(HTMLButtonElement | null)[]>([]);
  const focusLast = useRef(false);

  const dismiss = (restoreFocus = false) => {
    setOpen(null);
    if (restoreFocus && open !== null) triggers.current[open]?.focus();
  };
  useDismiss(bar, open !== null, dismiss);

  const show = (index: number, last = false) => {
    focusLast.current = last;
    setActive(index);
    setOpen(index);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const { key } = event;
    if (open !== null && key === 'Escape') {
      event.stopPropagation();
      dismiss(true);
    } else if (key === 'ArrowRight' || key === 'ArrowLeft') {
      event.preventDefault();
      const step = key === 'ArrowRight' ? 1 : -1;
      const next = ((open ?? active) + step + menus.length) % menus.length;
      triggers.current[next]?.focus();
      if (open !== null) show(next);
    } else if (open !== null) {
      moveItem(event, bar.current);
    } else if (key === 'ArrowDown' || key === 'ArrowUp') {
      event.preventDefault();
      show(active, key === 'ArrowUp');
    } else if (key === 'Home' || key === 'End') {
      event.preventDefault();
      triggers.current[key === 'Home' ? 0 : menus.length - 1]?.focus();
    }
  };

  return (
    <div className="menubar" ref={bar} role="menubar" aria-label={t('menu.bar')} onKeyDown={onKeyDown} onBlur={event => {
      if (open !== null && !event.currentTarget.contains(event.relatedTarget)) dismiss();
    }}>
      {menus.map((menu, n) => (
        <div key={menu.label} className="menu-root" role="none">
          <button
            type="button" id={`${id}-${n}-trigger`} ref={element => { triggers.current[n] = element; }}
            role="menuitem" tabIndex={open === null && active === n ? 0 : -1}
            aria-haspopup="menu" aria-expanded={open === n} aria-controls={open === n ? `${id}-${n}` : undefined}
            className={`menu-title${open === n ? ' on' : ''}`}
            onFocus={() => setActive(n)}
            onClick={() => open === n ? dismiss() : show(n)}
            onMouseEnter={() => { if (open !== null && open !== n) show(n); }}
          >
            {menu.label}
          </button>
          {open === n && <MenuPopup id={`${id}-${n}`} labelledBy={`${id}-${n}-trigger`} items={menu.items} last={focusLast.current} done={() => dismiss(true)} />}
        </div>
      ))}
    </div>
  );
}
