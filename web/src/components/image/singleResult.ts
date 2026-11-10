import type { SingleRun, SingleService } from '../../imageTypes';

export type SingleInput = {
  service: SingleService;
  positive: string;
  negative: string;
  settings: Record<string, unknown>;
  sources?: ResultPromptSource[];
};

export type ResultPromptSource = {
  kind: string;
  id?: string;
  name: string;
  positive?: string;
  negative?: string;
};

type SavedActual = SingleRun['actual'] & { prompt_sources?: ResultPromptSource[] };

export function resultSource(run: SingleRun, kind: 'style' | 'composition') {
  const actual: SavedActual = run.actual;
  return actual?.prompt_sources?.find(source => source.kind === kind)?.name
    || (kind === 'style' ? actual?.generation_preset?.name : undefined);
}

export function resultSeed(run: SingleRun) {
  return [run.seed, run.actual?.settings.seed].find(
    (value): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0,
  );
}

export function resultSettings(run: SingleRun, newSeed = false) {
  const seed = newSeed ? -1 : resultSeed(run);
  const settings = { ...run.actual?.settings };
  if (seed === undefined) delete settings.seed;
  else settings.seed = seed;
  return settings;
}

// The editor treats an unescaped hash at the start of a tag as a note. The saved prompt is already resolved.
export const editableSinglePrompt = (value: string) => value.replaceAll('#', '\\#');

function equivalent(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((item, index) => equivalent(item, right[index]));
  }
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const other = right as Record<string, unknown>;
  const entries = Object.entries(left);
  return entries.length === Object.keys(other).length
    && entries.every(([key, value]) => Object.hasOwn(other, key) && equivalent(value, other[key]));
}

export function settingDifferences(current: Record<string, unknown>, result: Record<string, unknown>) {
  return [...new Set([...Object.keys(result), ...Object.keys(current)])]
    .filter(key => !equivalent(current[key], result[key]))
    .map(key => ({ key, current: current[key], result: result[key] }));
}
