import { useEffect, useRef, useState } from 'react';

export type MenuEntry = { label: string; shortcut?: string; run: () => void; disabled?: boolean } | null;
export type Menu = { label: string; items: MenuEntry[] };

// A desktop-style menu bar: click opens a menu, moving over another title while one is open switches to it.
export default function MenuBar({ menus }: { menus: Menu[] }) {
  const [open, setOpen] = useState<number | null>(null);
  const bar = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open === null) return;
    const close = (e: MouseEvent) => !bar.current?.contains(e.target as Node) && setOpen(null);
    const key = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(null);
    window.addEventListener('mousedown', close);
    window.addEventListener('keydown', key);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('keydown', key);
    };
  }, [open]);

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
              {menu.items.map((item, i) =>
                item === null ? (
                  <div key={i} className="menu-sep" />
                ) : (
                  <button
                    key={i}
                    role="menuitem"
                    disabled={item.disabled}
                    onClick={() => {
                      setOpen(null);
                      item.run();
                    }}
                  >
                    <span className="grow">{item.label}</span>
                    {item.shortcut && <span className="faint">{item.shortcut}</span>}
                  </button>
                ),
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
