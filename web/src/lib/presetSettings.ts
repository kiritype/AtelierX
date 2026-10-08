// The generation settings a style preset leaves on the generate screen (#210). A preset that names a model carries
// whole settings and replaces them; one with only some values (artist tags and a few numbers, or none) changes just
// those and keeps the rest, starting from the family defaults when it is for another family.
type Settings = { family?: 'anima' | 'sdxl'; model?: string; seed?: number; [key: string]: unknown };

export function settingsFromPreset<T extends Settings>(
  current: T,
  preset: Partial<T>,
  family: 'anima' | 'sdxl',
  defaults: Record<'anima' | 'sdxl', Partial<T>>,
): T {
  if (preset.model) return { ...preset, family, seed: preset.seed ?? -1 } as T;
  const start = current.family === family ? current : ({ ...defaults[family], seed: current.seed } as Partial<T>);
  return { ...start, ...preset, family, seed: preset.seed ?? current.seed ?? -1 } as T;
}
