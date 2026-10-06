import { describe, expect, it } from 'vitest';
import { byGroup, fits, targetNames, visibleFor } from './fragments';

const items = [
  { id: 'q', name: '품질', group: '품질', targets: ['sdxl', 'anima', 'pixai'] },
  { id: 'bg', name: '배경', group: '배경' },
  { id: 'nq', name: 'NAI 품질', group: '품질', targets: ['novelai'] },
  { id: 'loose', name: '기타' },
];

describe('library fragments', () => {
  it('fits a target when written for it or for all', () => {
    expect(fits(items[0], 'anima')).toBe(true);
    expect(fits(items[0], 'novelai')).toBe(false);
    expect(fits(items[1], 'novelai')).toBe(true);
  });

  it('groups in first-seen order with the ungrouped last', () => {
    expect(byGroup(items).map((g) => [g.group, g.items.map((i) => i.id)])).toEqual([
      ['품질', ['q', 'nq']],
      ['배경', ['bg']],
      ['', ['loose']],
    ]);
  });

  it('lists fitting items, keeps chosen ones that do not fit, and counts the rest', () => {
    expect(visibleFor(items, 'novelai', [], false)).toEqual({ shown: [items[1], items[2], items[3]], hidden: 1 });
    expect(visibleFor(items, 'novelai', ['q'], false)).toEqual({ shown: items, hidden: 0 });
    expect(visibleFor(items, 'novelai', [], true).hidden).toBe(0);
  });

  it('names targets', () => {
    expect(targetNames(['sdxl', 'x'], [{ id: 'sdxl', name: 'SDXL·IL' }])).toBe('SDXL·IL, x');
  });
});
