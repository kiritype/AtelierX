// Where a part of a character's image design came from (#150): pieces of the character's text. "auto" pieces are what
// a whole-text conversion quoted, "pick" pieces are ranges the person chose. Designs from before #150 name a section.
export type Span = { text: string; by: 'auto' | 'pick' };
export type Source = { spans?: Span[]; section?: string; heading?: string | null; hash?: string } | null | undefined;
type Part = { source?: Source; prompt?: string[]; negative?: string[]; slots?: Record<string, unknown> } | null | undefined;

export const spansOf = (part: Part): Span[] => part?.source?.spans?.filter((s) => typeof s?.text === 'string') ?? [];

// Written by hand, or converted from a chosen range: a whole-text conversion keeps it unless the person says otherwise.
export function picked(part: Part): boolean {
  if (!part) return false;
  if (!part.source) {
    // An empty part made by an earlier conversion with nothing in it is not worth keeping.
    return !!(part.prompt?.length || part.negative?.length || Object.keys(part.slots ?? {}).length);
  }
  return spansOf(part).some((s) => s.by === 'pick');
}
