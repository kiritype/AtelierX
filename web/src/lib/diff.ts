// Line diff and hunks: snapshot comparison, and adopting part of an agent's whole-file proposal (11-agent).

export type DiffOp = { op: ' ' | '-' | '+'; text: string };
// A run of changed lines; `from`..`to` (exclusive) index the ops of `diffLines`.
export type Hunk = { id: number; from: number; to: number };

// LCS over the lines between the common head and tail, good enough for prose files of a few thousand lines.
export function diffLines(a: string[], b: string[]): DiffOp[] {
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
  const x = a.slice(head, a.length - tail);
  const y = b.slice(head, b.length - tail);
  const n = x.length;
  const m = y.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out: DiffOp[] = a.slice(0, head).map((text) => ({ op: ' ', text }));
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) (out.push({ op: ' ', text: x[i] }), i++, j++);
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push({ op: '-', text: x[i++] });
    else out.push({ op: '+', text: y[j++] });
  }
  while (i < n) out.push({ op: '-', text: x[i++] });
  while (j < m) out.push({ op: '+', text: y[j++] });
  for (const text of a.slice(a.length - tail)) out.push({ op: ' ', text });
  return out;
}

export function hunks(ops: DiffOp[]): Hunk[] {
  const out: Hunk[] = [];
  let k = 0;
  while (k < ops.length) {
    if (ops[k].op === ' ') {
      k++;
      continue;
    }
    const from = k;
    while (k < ops.length && ops[k].op !== ' ') k++;
    out.push({ id: out.length, from, to: k });
  }
  return out;
}

// The text with the adopted hunks taking the new lines and the others keeping the old ones.
export function compose(ops: DiffOp[], list: Hunk[], adopted: Set<number>): string {
  const lines: string[] = [];
  let k = 0;
  for (const hunk of list) {
    for (; k < hunk.from; k++) lines.push(ops[k].text);
    const keep = adopted.has(hunk.id) ? '+' : '-';
    for (; k < hunk.to; k++) if (ops[k].op === keep) lines.push(ops[k].text);
  }
  for (; k < ops.length; k++) lines.push(ops[k].text);
  return lines.join('\n');
}
