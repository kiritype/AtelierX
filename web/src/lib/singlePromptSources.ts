import type { PromptSource, SingleRun } from '../imageTypes';

export const SOURCE_KINDS: PromptSource['kind'][] = ['common', 'direct', 'character', 'expression', 'composition', 'style'];

// Match server comments.strip_text, including the comma before a trailing note.
export function cleanPrompt(value: string): string {
  return value.split(/\r?\n/).map(line => {
    const note = /(^|[\s,])#/.exec(line);
    const text = note ? line.slice(0, note.index).replace(/[ \t,]+$/, '') : line.trimEnd();
    return text.replaceAll('\\#', '#');
  }).filter(line => line.trim()).join('\n').trim();
}

// A saved prompt has already passed note processing. Escape every hash so another pass preserves its text.
export const editablePrompt = (value: string) => value.replaceAll('#', '\\#');
export const orderedSources = (sources: PromptSource[]) => SOURCE_KINDS.flatMap(kind => sources.filter(source => source.kind === kind));
export const replaceSource = (sources: PromptSource[], kind: PromptSource['kind'], source?: PromptSource) =>
  orderedSources([...sources.filter(item => item.kind !== kind), ...(source ? [source] : [])]);
export function promptSources(positive: string, negative: string, sources: PromptSource[]): PromptSource[] {
  return replaceSource(sources, 'direct', { kind: 'direct', id: '', name: '', positive: cleanPrompt(positive), negative: cleanPrompt(negative) });
}
export const combineSources = (sources: PromptSource[], target: 'positive' | 'negative') =>
  orderedSources(sources).map(source => source[target]).filter(Boolean).join(', ');

export function validSources(value: unknown): value is PromptSource[] {
  return Array.isArray(value) && value.length <= SOURCE_KINDS.length &&
    new Set(value.map(item => item?.kind)).size === value.length && value.every(item => item && SOURCE_KINDS.includes(item.kind) &&
      ['id', 'name', 'positive', 'negative'].every(key => typeof item[key] === 'string'));
}

export function restorePromptSources(run: SingleRun) {
  if (!run.actual) return { positive: '', negative: '', sources: [] };
  const recorded = run.actual.prompt_sources;
  if (run.actual.moss_layout?.mode === 'layout' && run.request) return {
    positive: run.request.positive, negative: run.request.negative,
    sources: validSources(recorded) ? recorded.filter(source => source.kind !== 'direct').map(source => ({ ...source })) : [],
  };
  if (!validSources(recorded)) return { positive: editablePrompt(run.actual.positive), negative: editablePrompt(run.actual.negative), sources: [] };
  const direct = recorded.find(source => source.kind === 'direct');
  return { positive: editablePrompt(direct?.positive ?? ''), negative: editablePrompt(direct?.negative ?? ''),
    sources: recorded.filter(source => source.kind !== 'direct').map(source => ({ ...source })) };
}
