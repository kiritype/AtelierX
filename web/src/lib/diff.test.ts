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

// The shortest edit keeps as many lines as the longest common subsequence.
function lcs(a: string[], b: string[]) {
  const dp = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  return dp[0][0];
}

function random(seed: number) {
  let s = seed;
  return () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
}

describe('line diff', () => {
  it('finds a shortest edit that rebuilds both sides', () => {
    const r = random(7);
    for (let round = 0; round < 300; round++) {
      const a = Array.from({ length: Math.floor(r() * 30) }, () => 'abcde'[Math.floor(r() * 5)]);
      const b = Array.from({ length: Math.floor(r() * 30) }, () => 'abcde'[Math.floor(r() * 5)]);
      const ops = diffLines(a, b);
      expect(ops.filter((o) => o.op !== '+').map((o) => o.text)).toEqual(a);
      expect(ops.filter((o) => o.op !== '-').map((o) => o.text)).toEqual(b);
      expect(ops.filter((o) => o.op === ' ')).toHaveLength(lcs(a, b));
    }
  });

  it('shows a change wider than the limit as one replaced block', () => {
    const a = ['same', ...Array.from({ length: 50 }, (_, i) => `old ${i}`), 'end'];
    const b = ['same', ...Array.from({ length: 50 }, (_, i) => `new ${i}`), 'end'];
    const ops = diffLines(a, b, 10);
    expect(hunks(ops)).toHaveLength(1);
    expect(ops.filter((o) => o.op !== '+').map((o) => o.text)).toEqual(a);
    expect(ops.filter((o) => o.op !== '-').map((o) => o.text)).toEqual(b);
  });

  it('handles thousands of lines quickly', () => {
    const a = Array.from({ length: 5000 }, (_, i) => `line ${i}`);
    const b = a.map((line, i) => (i % 7 === 3 ? `${line} edited` : line));
    const wide = Array.from({ length: 5000 }, (_, i) => `other ${i}`);
    const started = performance.now();
    const ops = diffLines(a, b);
    const rewritten = diffLines(a, wide);
    expect(performance.now() - started).toBeLessThan(3000);
    expect(hunks(ops)).toHaveLength(714);
    expect(compose(ops, hunks(ops), new Set(hunks(ops).map((h) => h.id)))).toBe(b.join('\n'));
    expect(compose(rewritten, hunks(rewritten), new Set())).toBe(a.join('\n'));
  });
});
