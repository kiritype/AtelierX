import { describe, expect, it } from 'vitest';
import { cancellable, finished, unfinished } from './lifecycle';

describe('job life cycle', () => {
  it('sorts the shared statuses', () => {
    expect(['queued', 'running', 'cancelling'].every(unfinished)).toBe(true);
    expect(['done', 'failed', 'cancelled', 'interrupted'].every(finished)).toBe(true);
    expect(unfinished('done') || finished('running') || unfinished(undefined)).toBe(false);
    expect(cancellable('running') && !cancellable('cancelling')).toBe(true);
  });
});
