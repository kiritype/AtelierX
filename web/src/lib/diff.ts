// Line diff and hunks: snapshot comparison, and adopting part of an agent's whole-file proposal (11-agent).

export type DiffOp = { op: ' ' | '-' | '+'; text: string };
// A run of changed lines; `from`..`to` (exclusive) index the ops of `diffLines`.
export type Hunk = { id: number; from: number; to: number };

// Past this many changed lines the shortest edit is not worth its memory: the rest shows as one replaced block.
export const DIFF_EDIT_LIMIT = 2000;

// Myers' O((N+M)D) diff over the lines between the common head and tail, so time and memory follow the size of the
// change, not the product of the line counts. A change wider than `limit` lines still diffs correctly, only coarser.
export function diffLines(a: string[], b: string[], limit = DIFF_EDIT_LIMIT): DiffOp[] {
  let head = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  let tail = 0;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
  const x = a.slice(head, a.length - tail);
  const y = b.slice(head, b.length - tail);
  const out: DiffOp[] = a.slice(0, head).map((text) => ({ op: ' ', text }));
  out.push(...middle(x, y, limit));
  for (const text of a.slice(a.length - tail)) out.push({ op: ' ', text });
  return out;
}

function middle(x: string[], y: string[], limit: number): DiffOp[] {
  const n = x.length;
  const m = y.length;
  const replaced = (): DiffOp[] => [...x.map((text) => ({ op: '-' as const, text })), ...y.map((text) => ({ op: '+' as const, text }))];
  if (!n || !m) return replaced();
  // Lines as numbers, so the search compares integers.
  const ids = new Map<string, number>();
  const id = (line: string) => ids.get(line) ?? (ids.set(line, ids.size), ids.size - 1);
  const xs = Int32Array.from(x, id);
  const ys = Int32Array.from(y, id);
  const max = Math.min(n + m, limit);
  const v = new Int32Array(2 * max + 3);
  const at = max + 1;
  // trace[d] holds the furthest x on diagonals -d..d after d edits, for walking back.
  const trace: Int32Array[] = [];
  let found = -1;
  for (let d = 0; d <= max && found < 0; d++) {
    for (let k = -d; k <= d; k += 2) {
      let i = k === -d || (k !== d && v[at + k - 1] < v[at + k + 1]) ? v[at + k + 1] : v[at + k - 1] + 1;
      let j = i - k;
      while (i < n && j < m && xs[i] === ys[j]) (i++, j++);
      v[at + k] = i;
      if (i >= n && j >= m) found = d;
    }
    trace.push(v.slice(at - d, at + d + 1));
  }
  if (found < 0) return replaced();
  const rev: DiffOp[] = [];
  let i = n;
  let j = m;
  for (let d = found; d > 0; d--) {
    const prev = trace[d - 1];
    const k = i - j;
    const down = k === -d || (k !== d && prev[k - 1 + d - 1] < prev[k + 1 + d - 1]);
    const pk = down ? k + 1 : k - 1;
    const pi = prev[pk + d - 1];
    const pj = pi - pk;
    // The equal run that followed this edit, then the edit itself: a line of y added, or a line of x removed.
    for (const si = down ? pi : pi + 1; i > si; ) (i--, j--, rev.push({ op: ' ', text: x[i] }));
    rev.push(down ? { op: '+', text: y[pj] } : { op: '-', text: x[pi] });
    i = pi;
    j = pj;
  }
  while (i > 0) (i--, rev.push({ op: ' ', text: x[i] }));
  return rev.reverse();
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
