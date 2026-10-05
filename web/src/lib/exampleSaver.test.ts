import { afterEach, describe, expect, it, vi } from 'vitest';
import { createSaver } from './exampleSaver';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

type Key = { jsx: string; name: string };
const basic: Key = { jsx: 'J001', name: 'basic' };

// A disk and a screen wired the way the JSX tab uses the saver: the screen takes an answer only when it is clean.
function harness(gateFor: (text: string) => Promise<void> | undefined = () => undefined) {
  const disk: Record<string, string> = {};
  const screen = { shown: '', dirty: false };
  const saver = createSaver<Key>(
    async (key, text) => {
      await gateFor(text);
      disk[`${key.jsx}/${key.name}`] = text;
      return text;
    },
    { onChange: (dirty) => (screen.dirty = dirty) },
  );
  const type = (text: string, key = basic) => {
    screen.shown = text;
    saver.edit(key, text);
  };
  const flush = async () => {
    const { saved, clean } = await saver.flush();
    if (clean && saved !== undefined) screen.shown = saved as string;
  };
  return { disk, screen, saver, type, flush };
}

// Let the write that flush() queued actually start.
const started = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.useRealTimers();
});

describe('example autosave', () => {
  it('keeps an edit made while the previous save was on its way', async () => {
    const gate = deferred();
    const h = harness((text) => (text === 'A' ? gate.promise : undefined));
    h.type('A');
    const first = h.flush();
    await started();
    h.type('AB');
    gate.resolve();
    await first;
    expect(h.screen).toEqual({ shown: 'AB', dirty: true });
    await h.flush();
    expect(h.disk['J001/basic']).toBe('AB');
    expect(h.screen).toEqual({ shown: 'AB', dirty: false });
  });

  it('never lets an older write finish after a newer one', async () => {
    // The first write is slow. The second flush waits for it, so disk, screen and state all end on the newest text.
    const slow = deferred();
    const h = harness((text) => (text === 'old' ? slow.promise : undefined));
    h.type('old');
    const first = h.flush();
    await started();
    h.type('new');
    const second = h.flush();
    slow.resolve();
    await Promise.all([first, second]);
    expect(h.disk['J001/basic']).toBe('new');
    expect(h.screen).toEqual({ shown: 'new', dirty: false });
  });

  it('writes each edit under the key it was typed for', async () => {
    const h = harness();
    h.type('<A />');
    await h.flush();
    h.type('<A x="1" />', { jsx: 'J001', name: 'late' });
    await h.flush();
    expect(h.disk).toEqual({ 'J001/basic': '<A />', 'J001/late': '<A x="1" />' });
  });

  it('saves on its own after a pause, also when the preview tab is gone', async () => {
    vi.useFakeTimers();
    const h = harness();
    h.type('<A />');
    expect(h.screen.dirty).toBe(true);
    await vi.advanceTimersByTimeAsync(700);
    expect(h.disk['J001/basic']).toBe('<A />');
    expect(h.screen.dirty).toBe(false);
  });

  it('keeps the edit pending when a write fails', async () => {
    const saver = createSaver<Key>(async () => {
      throw new Error('offline');
    });
    saver.edit(basic, '<A />');
    await expect(saver.flush()).rejects.toThrow('offline');
    expect(saver.dirty).toBe(true);
  });

  it('forgets the edits of a deleted example and writes nothing after a discard', async () => {
    vi.useFakeTimers();
    const h = harness();
    h.type('<A />');
    h.saver.drop((key) => key.name === 'other');
    expect(h.saver.dirty).toBe(true);
    h.saver.drop((key) => key.name === 'basic');
    expect(h.screen.dirty).toBe(false);
    h.type('<B />');
    h.saver.dispose();
    await vi.advanceTimersByTimeAsync(1000);
    expect(h.disk).toEqual({});
  });
});
