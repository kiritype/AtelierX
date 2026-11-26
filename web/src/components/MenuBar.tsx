import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject } from 'react';
import { Icon } from './icons';

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

function MenuItems({ items, done }: { items: MenuEntry[]; done: () => void }) {
  return (
    <>
      {items.map((item, i) =>
        item === null ? (
          <div key={i} className="menu-sep" />
        ) : 'heading' in item ? (
          <div key={i} className="menu-heading" role="presentation">
            {item.heading}
          </div>
        ) : (
          <button
            key={i}
            role="menuitem"
            disabled={item.disabled}
            onClick={() => {
              done();
              item.run();
            }}
          >
            <span className="grow">{item.label}</span>
            {item.shortcut && <span className="faint">{item.shortcut}</span>}
          </button>
        ),
      )}
    </>
  );
}

// A button that opens a menu below it, right-aligned (for toolbars).
export function MenuButton({ label, items, className }: { label: ReactNode; items: MenuEntry[]; className?: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const focusLast = useRef(false);
  const dismiss = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) trigger.current?.focus();
  };
  useDismiss(root, open, dismiss);
  useEffect(() => {
    if (!open) return;
    const buttons = enabledButtons(root.current);
    buttons.at(focusLast.current ? -1 : 0)?.focus();
    focusLast.current = false;
  }, [open]);

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const { key } = event;
    if (!open) {
      if (key === 'ArrowDown' || key === 'ArrowUp') {
        event.preventDefault();
        focusLast.current = key === 'ArrowUp';
        setOpen(true);
      }
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) return;
    event.preventDefault();
    const buttons = enabledButtons(root.current);
    if (!buttons.length) return;
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next = 0;
    if (key === 'ArrowDown') next = (current + 1) % buttons.length;
    if (key === 'ArrowUp') next = current <= 0 ? buttons.length - 1 : current - 1;
    if (key === 'End') next = buttons.length - 1;
    buttons[next].focus();
  };

  return (
    <div className="menu-root" ref={root} onKeyDown={onKeyDown} onBlur={event => {
      if (open && !event.currentTarget.contains(event.relatedTarget)) dismiss();
    }}>
      <button type="button" ref={trigger} className={['menu-button', className, open ? 'on' : ''].filter(Boolean).join(' ')} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        {label} <Icon name="menu" size={14} />
      </button>
      {open && (
        <div className="menu-drop right" role="menu">
          <MenuItems items={items} done={() => dismiss(true)} />
        </div>
      )}
    </div>
  );
}

function enabledButtons(root: HTMLDivElement | null) {
  return Array.from(root?.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)') ?? []);
}

// A desktop-style menu bar: click opens a menu, moving over another title while one is open switches to it.
export default function MenuBar({ menus }: { menus: Menu[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  useDismiss(bar, open !== null, () => setOpen(null));

  return (
    <div className="menubar" ref={bar}>
      {menus.map((menu, n) => (
        <div key={menu.label} className="menu-root">
          <button
            className={`menu-title${open === n ? ' on' : ''}`}
            onClick={() => setOpen(open === n ? null : n)}
            onMouseEnter={() => open !== null && setOpen(n)}
          >
            {menu.label}
          </button>
          {open === n && (
            <div className="menu-drop" role="menu">
              <MenuItems items={menu.items} done={() => setOpen(null)} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
