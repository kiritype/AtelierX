// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';
import { saveStartupUpdate, shouldReportUpdateResult, startupUpdateState, takeStartupUpdateNotice, UPDATE_CHECK_INTERVAL } from './updateNotice';

describe('update notice browser preferences', () => {
  it('limits automatic checks to once per day while retaining an available version for the badge', () => {
    const storage = window.localStorage;
    storage.clear();
    const now = 10_000_000;
    expect(startupUpdateState(storage, now).shouldCheck).toBe(true);
    expect(saveStartupUpdate(storage, { current: '0.4.0', latest: '0.4.1', newer: true }, now)).toEqual({ available: true, shouldNotify: true });
    expect(takeStartupUpdateNotice(storage)).toEqual({ current: '0.4.0', latest: '0.4.1', newer: true });
    expect(startupUpdateState(storage, now + UPDATE_CHECK_INTERVAL - 1)).toEqual({ shouldCheck: false, availableVersion: '0.4.1', pendingNotice: false });
    expect(saveStartupUpdate(storage, { current: '0.4.0', latest: '0.4.1', newer: true }, now + UPDATE_CHECK_INTERVAL)).toEqual({ available: true, shouldNotify: false });
    expect(saveStartupUpdate(storage, { current: '0.4.1', latest: '0.4.1', newer: false }, now + UPDATE_CHECK_INTERVAL * 2)).toEqual({ available: false, shouldNotify: false });
    expect(startupUpdateState(storage, now + UPDATE_CHECK_INTERVAL * 2).availableVersion).toBeNull();
  });

  it('reports an update result only once, keyed by its outcome and version', () => {
    const storage = window.localStorage;
    storage.clear();
    const result = { state: 'ok' as const, from: '0.4.0', version: '0.4.1' };
    expect(shouldReportUpdateResult(storage, result)).toBe(true);
    expect(shouldReportUpdateResult(storage, result)).toBe(false);
    expect(shouldReportUpdateResult(storage, { ...result, version: '0.4.2' })).toBe(true);
  });

  it('uses memory to suppress repeated notices when browser storage cannot be accessed', () => {
    const blocked = {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
      removeItem: () => { throw new Error('blocked'); },
    } as unknown as Storage;
    const result = { state: 'ok' as const, from: '0.4.0', version: '0.4.1' };
    expect(shouldReportUpdateResult(blocked, result)).toBe(true);
    expect(shouldReportUpdateResult(blocked, result)).toBe(false);
  });
});
