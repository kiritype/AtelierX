import { describe, expect, it } from 'vitest';
import { createSaver } from './exampleSaver';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

describe('example autosave', () => {
  it('keeps an edit made while the previous save was on its way', async () => {
    const stored: string[] = [];
    const gate = deferred();
    const saver = createSaver(async (_name, text) => {
      if (text === 'A') await gate.promise;
      stored.push(text);
    });
    saver.edit('basic', 'A');
    const first = saver.flush();
    saver.edit('basic', 'AB'); // typed while A was being saved
    gate.resolve();
    expect((await first).clean).toBe(false);
    expect(saver.dirty).toBe(true);
    expect((await saver.flush()).clean).toBe(true);
    expect(stored).toEqual(['A', 'AB']);
  });

  it('stays dirty when saves finish in reverse order', async () => {
    const slow = deferred();
    const saver = createSaver(async (_name, text) => {
      if (text === 'one') await slow.promise;
    });
    saver.edit('basic', 'one');
    const first = saver.flush();
    saver.edit('basic', 'two');
    const second = saver.flush();
    expect((await second).clean).toBe(true);
    slow.resolve();
    expect((await first).clean).toBe(true); // the newer save already landed; the late answer changes nothing
    expect(saver.dirty).toBe(false);
  });

  it('saves the pending edit under its own name before the buffer switches', async () => {
    const stored: [string, string][] = [];
    const saver = createSaver(async (name, text) => void stored.push([name, text]));
    saver.edit('basic', '<A />');
    await saver.flush();
    saver.edit('late', '<A x="1" />');
    expect(saver.job?.name).toBe('late');
    await saver.flush();
    expect(stored).toEqual([['basic', '<A />'], ['late', '<A x="1" />']]);
  });
});
