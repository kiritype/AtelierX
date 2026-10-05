// Component calls in text (`<Name a='…' b="…" />`), read the way the platform reads a reply: the work's platform
// preset sets `jsx.response` (07-jsx). server/atelierx/core/review.py reads attribute values the same way.

export type AttributeFormat = 'json' | 'json_lenient' | 'text';
export type ResponseRule = {
  syntax?: string;
  attribute_format?: AttributeFormat;
  decode?: (string[] | { from?: string; to?: string })[];
};
export type Call = { name: string; raw: string; attrs: Record<string, unknown>; errors: string[]; index: number };
export type Segment = { text: string } | { component: string; attrs: Record<string, unknown>; raw: string };

// `text` keeps the written text; `json` must be JSON; `json_lenient` also allows single quotes and trailing commas and
// takes a value that does not look like JSON (C001, 001) as the written text.
export function readValue(raw: string, format: AttributeFormat = 'json_lenient'): { value?: unknown; error?: string } {
  if (format === 'text') return { value: raw };
  const candidates = format === 'json' ? [raw] : [raw, raw.replace(/,\s*([}\]])/g, '$1'), raw.replace(/'/g, '"')];
  let error = '';
  for (const candidate of candidates) {
    try {
      return { value: JSON.parse(candidate) };
    } catch (err) {
      error = (err as Error).message;
    }
  }
  if (format !== 'json' && !/^\s*[[{]/.test(raw)) return { value: raw };
  return { error };
}

export function decodeText(text: string, rule?: ResponseRule): string {
  for (const pair of rule?.decode ?? []) {
    const [from, to] = Array.isArray(pair) ? pair : [pair.from, pair.to];
    if (from) text = text.split(from).join(to ?? '');
  }
  return text;
}

const escape = (name: string) => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// Every call of the named components, in order, with the props read and the attributes that could not be read.
export function findCalls(text: string, names: string[], rule?: ResponseRule): Call[] {
  if (!names.length) return [];
  const format = rule?.attribute_format ?? 'json_lenient';
  const pattern = new RegExp(`<(${names.map(escape).join('|')})((?:\\s+[\\w-]+=(?:'[^']*'|"[^"]*"))*)\\s*/>`, 'g');
  const out: Call[] = [];
  for (const match of decodeText(text, rule).matchAll(pattern)) {
    const attrs: Record<string, unknown> = {};
    const errors: string[] = [];
    for (const a of match[2].matchAll(/([\w-]+)=(?:'([^']*)'|"([^"]*)")/g)) {
      const read = readValue(a[2] ?? a[3], format);
      if (read.error) errors.push(`${a[1]}: ${read.error}`);
      attrs[a[1]] = read.value ?? null;
    }
    out.push({ name: match[1], raw: match[0], attrs, errors, index: match.index! });
  }
  return out;
}

// Split a reply into text and component calls for the work's JSX items.
export function splitReply(text: string, names: string[], rule?: ResponseRule): Segment[] {
  const decoded = decodeText(text, rule);
  const out: Segment[] = [];
  let last = 0;
  for (const call of findCalls(decoded, names, { ...rule, decode: [] })) {
    if (call.index > last) out.push({ text: decoded.slice(last, call.index) });
    out.push({ component: call.name, attrs: call.attrs, raw: call.raw });
    last = call.index + call.raw.length;
  }
  if (last < decoded.length) out.push({ text: decoded.slice(last) });
  return out.length ? out : [{ text }];
}
