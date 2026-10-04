// Messages between the app and the sandboxed preview frame. The frame has an opaque origin, so the app checks
// `event.source` instead of the origin.

export type GlobalStub = { name: string; stub?: string };

export type ToFrame = {
  type: 'render';
  id: number;
  code: string;
  name: string;
  props: unknown;
  hooks: string[];
  globals: GlobalStub[];
  theme: 'light' | 'dark' | 'inline';
};

export type FromFrame =
  | { type: 'ready' }
  | { type: 'rendered'; id: number }
  | { type: 'error'; id: number; message: string; line: number | null }
  | { type: 'call'; id: number; name: string; args: unknown[] }
  | { type: 'size'; height: number };
