import { describe, expect, it } from 'vitest';
import { compose, diffLines, hunks } from './diff';

const before = ['---', 'kind: character', '---', '# 성격', '조용하다.', '', '# 말투', '반말을 쓴다.', ''].join('\n');
const after = ['---', 'kind: character', '---', '# 성격', '조용하고 차분하다.', '', '# 말투', '반말을 쓴다.', '', '# 버릇', '머리를 넘긴다.', ''].join('\n');

describe('hunks of a whole-file proposal', () => {
  it('finds each changed run and rebuilds either side', () => {
    const ops = diffLines(before.split('\n'), after.split('\n'));
    const list = hunks(ops);
    expect(list).toHaveLength(2);
    expect(compose(ops, list, new Set([0, 1]))).toBe(after);
    expect(compose(ops, list, new Set())).toBe(before);
  });

  it('adopts only the chosen hunks', () => {
    const ops = diffLines(before.split('\n'), after.split('\n'));
    const list = hunks(ops);
    const second = compose(ops, list, new Set([1]));
    expect(second).toContain('조용하다.');
    expect(second).toContain('# 버릇');
    expect(second).not.toContain('차분하다');
  });

  it('keeps identical text identical', () => {
    const ops = diffLines(before.split('\n'), before.split('\n'));
    expect(hunks(ops)).toEqual([]);
    expect(compose(ops, [], new Set())).toBe(before);
  });
});
