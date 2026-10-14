import { describe, expect, it, vi } from 'vitest';
import { beginStartupUpdateCheck, updateResultKey } from './updateNotice';

describe('startup update notice helpers', () => {
  it('shares an active check across screen unmounts', async () => {
    let resolve!: (value: { current: string; latest: string; newer: boolean }) => void;
    const check = vi.fn(() => new Promise<{ current: string; latest: string; newer: boolean }>((done) => { resolve = done; }));
    const first = beginStartupUpdateCheck(check);
    const second = beginStartupUpdateCheck(check);
    expect(first).toBe(second);
    expect(check).toHaveBeenCalledTimes(0);
    await Promise.resolve();
    expect(check).toHaveBeenCalledTimes(1);
    resolve({ current: '8.8.0', latest: '8.8.1', newer: true });
    await expect(second).resolves.toEqual({ current: '8.8.0', latest: '8.8.1', newer: true });
  });

  it('keys successful update notices by their outcome and versions', () => {
    expect(updateResultKey({ state: 'ok', from: '8.8.0', version: '8.8.1' })).toBe('ok:8.8.1:8.8.0');
  });
});
