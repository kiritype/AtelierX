import { FAMILY_DEFAULTS } from './GenSettings';
import type { ExplorerRules, ExplorerArtist } from '../../styleExplorerTypes';
export const rules: ExplorerRules = {
  artist_min: 1,
  artist_max: 3,
  artist_low: 0.7,
  artist_high: 1.2,
  artist_step: 0.1,
  lora_min: 0,
  lora_max: 2,
  lora_low: 0.5,
  lora_high: 1,
  lora_step: 0.1,
};
export type ExplorerDraft = {
  name: string;
  service: string;
  family: string;
  positive: string;
  negative: string;
  seed: number;
  count: number;
  budget: number;
  artists: ExplorerArtist[];
  pool: string;
  models: string;
  modelPools: Record<string, string>;
  rules: ExplorerRules;
  settings: Record<string, Record<string, unknown>>;
};
export const freshDraft = (): ExplorerDraft => ({
  name: '',
  service: 'comfyui',
  family: 'anima',
  positive: '',
  negative: '',
  seed: 42,
  count: 8,
  budget: 30,
  artists: [],
  pool: '',
  models: '',
  modelPools: {},
  rules: { ...rules },
  settings: {
    'comfyui:anima': { family: 'anima', ...FAMILY_DEFAULTS.anima },
    'comfyui:sdxl': { family: 'sdxl', ...FAMILY_DEFAULTS.sdxl },
    novelai: {},
    pixai: {},
  },
});
export const settingsKey = (d: Pick<ExplorerDraft, 'service' | 'family'>) =>
  d.service === 'comfyui' ? `${d.service}:${d.family}` : d.service;
export function readDraft(key: string): ExplorerDraft {
  const base = freshDraft();
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    if (!value || !['comfyui', 'novelai', 'pixai'].includes(value.service)) return base;
    return {
      ...base,
      ...value,
      modelPools: { ...base.modelPools, ...value.modelPools },
      rules: { ...rules, ...value.rules },
      settings: { ...base.settings, ...value.settings },
    };
  } catch {
    return base;
  }
}
export function parseArtists(text: string, previous: ExplorerArtist[]): ExplorerArtist[] {
  return [
    ...new Set(
      text
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ].map((name) => previous.find((a) => a.name === name) ?? { name, mode: 'candidate' });
}
export function effectiveRules(d: ExplorerDraft): ExplorerRules {
  const artistCount = d.artists.filter((a) => a.mode !== 'exclude').length;
  const loras = d.settings[settingsKey(d)]?.loras;
  const loraCount =
    d.service === 'novelai'
      ? 0
      : Array.isArray(loras)
        ? loras.filter((l) => l && typeof l === 'object' && l.enabled !== false).length
        : 0;
  const always = d.artists.filter((a) => a.mode === 'always').length;
  const artistMax = Math.max(always, Math.min(d.rules.artist_max, artistCount)),
    loraMax = Math.min(d.rules.lora_max, loraCount);
  return {
    ...d.rules,
    artist_min: Math.min(d.rules.artist_min, artistMax),
    artist_max: artistMax,
    lora_min: Math.min(d.rules.lora_min, loraMax),
    lora_max: loraMax,
  };
}
export function switchContext(
  d: ExplorerDraft,
  context: Partial<Pick<ExplorerDraft, 'service' | 'family'>>,
): ExplorerDraft {
  const next = { ...d, ...context };
  const oldKey = settingsKey(d),
    newKey = settingsKey(next);
  if (oldKey === newKey) return next;
  const modelPools = { ...d.modelPools, [oldKey]: d.models };
  return { ...next, modelPools, models: modelPools[newKey] ?? '' };
}
