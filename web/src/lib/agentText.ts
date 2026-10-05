// An agent answer split into prose and file proposals (`<<<file path="…">>>` … `<<<end>>>`, 11-agent), the same way
// the server reads it: `n` counts distinct paths in order of first appearance, and a later block for the same path
// replaces an earlier one (`superseded`). A block without its end line is still being written, or was cut off.

export type AnswerSegment =
  | { kind: 'text'; text: string }
  | { kind: 'file'; path: string; text: string; closed: boolean; n: number; superseded: boolean };

const MARK = /^<<<file path="([^"\n]+)">>>[ \t]*$/m;
const END = /^<<<end>>>[ \t]*$/m;

function normalize(path: string) {
  let out = path.trim().replaceAll('\\', '/');
  while (out.startsWith('./')) out = out.slice(2);
  return out.replace(/^\/+|\/+$/g, '');
}

export function splitAnswer(answer: string): AnswerSegment[] {
  const out: AnswerSegment[] = [];
  let rest = answer;
  while (rest) {
    const mark = MARK.exec(rest);
    if (!mark) {
      out.push({ kind: 'text', text: rest });
      break;
    }
    if (mark.index > 0) out.push({ kind: 'text', text: rest.slice(0, mark.index) });
    let body = rest.slice(mark.index + mark[0].length);
    if (body.startsWith('\n')) body = body.slice(1);
    const end = END.exec(body);
    const next = MARK.exec(body);
    const closed = !!end && (!next || end.index < next.index);
    const stop = closed ? end!.index : next ? next.index : body.length;
    out.push({ kind: 'file', path: normalize(mark[1]), text: body.slice(0, stop), closed, n: 0, superseded: false });
    rest = closed ? body.slice(end!.index + end![0].length) : body.slice(stop);
  }
  const order: string[] = [];
  const last = new Map<string, number>();
  out.forEach((segment, index) => {
    if (segment.kind !== 'file') return;
    if (!order.includes(segment.path)) order.push(segment.path);
    last.set(segment.path, index);
  });
  return out
    .map((segment, index) =>
      segment.kind === 'file' ? { ...segment, n: order.indexOf(segment.path) + 1, superseded: last.get(segment.path) !== index } : segment,
    )
    .filter((segment) => segment.kind === 'file' || segment.text.trim());
}
