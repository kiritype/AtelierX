import { describe, expect, it } from 'vitest';
import { picked, spansOf } from './designSource';

describe('design sources', () => {
  it('keeps hand edits and chosen ranges, not whole-text conversions', () => {
    expect(picked({ prompt: ['blazer'] })).toBe(true);
    expect(picked({ prompt: [], negative: [] })).toBe(false);
    expect(picked({ prompt: ['x'], source: { spans: [{ text: 'a', by: 'auto' }] } })).toBe(false);
    expect(picked({ prompt: ['x'], source: { spans: [{ text: 'a', by: 'auto' }, { text: 'b', by: 'pick' }] } })).toBe(true);
    expect(picked({ prompt: ['x'], source: { section: 'appearance', hash: 'h' } })).toBe(false);
    expect(picked(undefined)).toBe(false);
  });

  it('reads the pieces of new sources only', () => {
    expect(spansOf({ source: { spans: [{ text: 'a', by: 'pick' }] } })).toEqual([{ text: 'a', by: 'pick' }]);
    expect(spansOf({ source: { section: 'outfit', heading: '교복' } })).toEqual([]);
  });
});
