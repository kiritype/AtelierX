// App tooltips (#81): the browser's own `title` tooltip waits about a second and is easy to miss, so the tooltip
// layer takes over every `title` in the app. These helpers are the parts without the DOM events.

// "잠금 (Ctrl+Shift+L)" → the label and the shortcut shown apart.
export function splitShortcut(text: string): { label: string; keys: string | null } {
  const m = /^(.*?)\s*\(((?:Ctrl|Shift|Alt|Cmd|F\d+)[^()]*)\)$/.exec(text);
  return m ? { label: m[1], keys: m[2] } : { label: text, keys: null };
}

export type Box = { left: number; top: number; right: number; bottom: number };

// Below the element, centred and kept inside the window; above it when there is no room below.
export function placeTip(anchor: Box, size: { width: number; height: number }, view: { width: number; height: number }, gap = 6, margin = 8) {
  const centre = (anchor.left + anchor.right) / 2;
  const left = Math.min(Math.max(centre - size.width / 2, margin), Math.max(margin, view.width - size.width - margin));
  const below = anchor.bottom + gap;
  const top = below + size.height <= view.height - margin ? below : Math.max(margin, anchor.top - gap - size.height);
  return { left, top };
}
