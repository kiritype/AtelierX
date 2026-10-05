import { describe, expect, it } from 'vitest';
import { compareRows, startText } from './testRuns';

describe('test-set runs', () => {
  it('compares a repeated input turn by turn', () => {
    const left = { set: { inputs: ['안녕', '계속', '계속'] }, turns: [{ input: '안녕', reply: 'a1' }, { input: '계속', reply: 'a2' }, { input: '계속', reply: 'a3' }] };
    const right = { set: { inputs: ['안녕', '계속', '계속'] }, turns: [{ input: '안녕', reply: 'b1' }, { input: '계속', reply: 'b2' }] };
    const rows = compareRows(left, right);
    expect(rows.map((r) => [r.inputs, r.left?.reply, r.right?.reply])).toEqual([
      [['안녕'], 'a1', 'b1'],
      [['계속'], 'a2', 'b2'],
      [['계속'], 'a3', undefined],
    ]);
  });

  it('shows both inputs when the set changed between runs', () => {
    const rows = compareRows({ set: { inputs: ['가'] }, turns: [] }, { set: { inputs: ['나', '다'] }, turns: [] });
    expect(rows.map((r) => r.inputs)).toEqual([['가', '나'], ['다']]);
  });

  it('opens with the start situation, and refuses to run without a start it cannot read', async () => {
    expect(await startText(async () => ({ body: ' {{user}}, 어서 와. \n' }), '시작.md', '민수')).toBe('민수, 어서 와.');
    expect(await startText(async () => ({ body: '' }), null, '민수')).toBeNull();
    await expect(startText(() => Promise.reject(new Error('404')), '지운 파일.md', '민수')).rejects.toThrow('지운 파일.md');
  });
});
