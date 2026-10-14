import { describe, expect, it } from 'vitest';
import { validRender, validReply } from './protocol';

describe('preview message validation', () => {
  const render = { type: 'render', id: 1, code: 'function Test() { return null; }', name: 'Test', props: {}, hooks: ['useState'], globals: [{ name: 'notify' }], theme: 'light' };
  it('accepts valid render and rejects invalid inputs', () => {
    expect(validRender(render)).toBe(true);
    for (const value of [null, [], {}, { ...render, hooks: null }, { ...render, globals: [null] }, { ...render, name: 'not an identifier' }, { ...render, id: -1 }]) expect(validRender(value)).toBe(false);
  });
  it('accepts known replies and rejects malformed callbacks and dimensions', () => {
    expect(validReply({ type: 'ready' })).toBe(true);
    expect(validReply({ type: 'rendered', id: 1 })).toBe(true);
    expect(validReply({ type: 'call', id: 1, name: 'notify', args: [] })).toBe(true);
    for (const value of [null, { type: 'size', height: NaN }, { type: 'call', id: 1, name: 'notify', args: 'bad' }, { type: 'error', id: 1, message: 'error', line: 'bad' }]) expect(validReply(value)).toBe(false);
  });
});
