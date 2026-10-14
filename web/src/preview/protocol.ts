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

const IDENTIFIER = /^[\p{L}_$][\p{L}\p{N}_$]*$/u;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const id = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;

export function validRender(value: unknown): value is ToFrame {
  if (!record(value)) return false;
  return value.type === 'render' && id(value.id) && typeof value.code === 'string'
    && typeof value.name === 'string' && IDENTIFIER.test(value.name)
    && Array.isArray(value.hooks) && value.hooks.every((h) => typeof h === 'string' && IDENTIFIER.test(h))
    && Array.isArray(value.globals) && value.globals.every((g) => record(g)
      && typeof g.name === 'string' && IDENTIFIER.test(g.name) && (g.stub === undefined || typeof g.stub === 'string'))
    && ['light', 'dark', 'inline'].includes(String(value.theme));
}

export function validReply(value: unknown): value is FromFrame {
  if (!record(value)) return false;
  if (value.type === 'ready') return true;
  if (value.type === 'size') return typeof value.height === 'number' && Number.isFinite(value.height) && value.height >= 0;
  if (!id(value.id)) return false;
  if (value.type === 'rendered') return true;
  if (value.type === 'error') return typeof value.message === 'string'
    && (value.line === null || (Number.isSafeInteger(value.line) && Number(value.line) > 0));
  return value.type === 'call' && typeof value.name === 'string' && Array.isArray(value.args);
}
