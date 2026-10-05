import { describe, expect, it } from 'vitest';
import { bulkCloseKeys, nextActiveKey, tracksFormChanges } from './tabActions';

describe('tab actions', () => {
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

describe('form changes', () => {
  it('ignores run screens, item tabs and app settings (whose forms report themselves), tracks the library', () => {
    expect(tracksFormChanges({ type: 'item' })).toBe(false);
    expect(tracksFormChanges({ type: 'image', view: 'generate' })).toBe(false);
    expect(tracksFormChanges({ type: 'image', view: 'tools' })).toBe(false);
    expect(tracksFormChanges({ type: 'image', view: 'library' })).toBe(true);
    expect(tracksFormChanges({ type: 'settings' })).toBe(false);
    expect(tracksFormChanges({ type: 'work-settings' })).toBe(true);
  });
});
