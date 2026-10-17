import { describe, expect, it } from 'vitest';
import { bulkCloseKeys, nextActiveKey, openQueueKey } from './tabActions';

describe('tab actions', () => {
  it('finds the open queue even when it was opened from a character', () => {
    expect(openQueueKey([{ type: 'image', view: 'gallery' }, { type: 'image', view: 'queue', characterId: 'C001' }])).toBe('image:queue:C001:');
    expect(openQueueKey([{ type: 'image', view: 'gallery' }])).toBeNull();
  });
  it('excludes pinned tabs from bulk close', () => {
    expect(bulkCloseKeys(['a', 'b', 'c', 'd'], 'b', ['a', 'c'], 'others')).toEqual(['d']);
    expect(bulkCloseKeys(['a', 'b', 'c', 'd'], 'b', ['c'], 'right')).toEqual(['d']);
  });

  it('selects the tab at the closed active tab position, or the previous last tab', () => {
    expect(nextActiveKey(['a', 'b', 'c', 'd'], new Set(['b', 'c']), 'b')).toBe('d');
    expect(nextActiveKey(['a', 'b'], new Set(['b']), 'b')).toBe('a');
    expect(nextActiveKey(['a'], new Set(['a']), 'a')).toBeNull();
  });
});
