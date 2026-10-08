import { describe, expect, it } from 'vitest';
import { allOutfits, columnState, outfitColumns, rowState, selectionState, setColumn, setOutfit, setRow, type CharacterRef } from './outfitColumns';

const chars: CharacterRef[] = [
  { id: 'C001', has_design: true, outfits: [{ id: 'o01', name: '교복', code: '002' }, { id: 'o02', name: '평상복', code: '001' }] },
  { id: 'C002', has_design: true, outfits: [{ id: 'o01', name: '평상복', code: '001' }, { id: 'o02', name: '교복', code: '002' }, { id: 'o03', name: '수영복' }] },
  { id: 'C003', has_design: true, outfits: [{ id: 'a', name: '잠옷' }, { id: 'b', name: '평상복', code: '10' }] },
  { id: 'C004', has_design: true, outfits: [{ id: 'x', name: '잠옷' }, { id: 'y', name: '사복', code: '001' }] },
  { id: 'C005', has_design: false, outfits: [] },
];

describe('outfit columns', () => {
  it('groups by code in ascending order, then by a shared name, and leaves the rest to the other outfits', () => {
    const { columns, others } = outfitColumns(chars);
    expect(columns.map((c) => [c.key, c.name])).toEqual([
      ['code:001', '평상복'],
      ['code:002', '교복'],
      ['code:10', '평상복'],
      ['name:잠옷', '잠옷'],
    ]);
    expect(columns[0].members).toEqual({ C001: 'o02', C002: 'o01', C004: 'y' });
    expect(columns[3].members).toEqual({ C003: 'a', C004: 'x' });
    expect(others).toEqual({ C002: [{ id: 'o03', name: '수영복' }] });
  });

  it('selects all, a row, a column and single cells', () => {
    const { columns } = outfitColumns(chars);
    let s = allOutfits(chars);
    expect(selectionState(s, chars)).toBe('all');
    expect(s.C005).toBeUndefined();
    s = setColumn(s, columns[1], false);
    expect(columnState(s, columns[1])).toBe('none');
    expect(rowState(s, chars[0])).toBe('some');
    expect(selectionState(s, chars)).toBe('some');
    s = setRow(s, chars[0], false);
    expect(s.C001).toBeUndefined();
    s = setOutfit({}, 'C002', 'o03', true);
    expect(s).toEqual({ C002: ['o03'] });
    expect(selectionState({}, chars)).toBe('none');
  });
});
