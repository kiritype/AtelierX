import { FAMILY_DEFAULTS } from './GenSettings';
import type { ExplorerArtist, ExplorerMaterial, ExplorerRules, ExplorerSelectionRules, ExplorerWeight } from '../../styleExplorerTypes';

export const EXPLORER_DRAFT_KEY = 'atelierx-explorer-v3-global';
const V2_DRAFT_KEY = 'atelierx-explorer-v2-global';
const WEIGHT_STEP = 0.1;
const legacyRules: ExplorerRules = {
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

export type ExplorerLora = { name: string; id?: string; trigger_words?: string };
export type MaterialGroup<T> = {
  items: T[];
  countMin: number;
  countMax: number;
  weightMin?: number;
  weightMax?: number;
};
export type MaterialPool = { tags: MaterialGroup<string>; loras: MaterialGroup<ExplorerLora> };
type LegacyDraft = Partial<Omit<ExplorerDraft, 'materialPools'>> & {
  artists?: ExplorerArtist[];
  pool?: string;
  rules?: Partial<ExplorerRules>;
  materialPools?: Record<string, { materials: ExplorerMaterial[]; rules: ExplorerSelectionRules }>;
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
  models: string;
  modelPools: Record<string, string>;
  materialPools: Record<string, MaterialPool>;
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
  models: '',
  modelPools: {},
  materialPools: {},
  settings: {
    'comfyui:anima': { family: 'anima', ...FAMILY_DEFAULTS.anima },
    'comfyui:sdxl': { family: 'sdxl', ...FAMILY_DEFAULTS.sdxl },
    novelai: {},
    pixai: {},
  },
});

export const settingsKey = (d: Pick<ExplorerDraft, 'service' | 'family'>) =>
  d.service === 'comfyui' ? `${d.service}:${d.family}` : d.service;

export function parseNames(text: string) {
  return [...new Set(text.split(/[\n,]/).map((name) => name.trim()).filter(Boolean))];
}

function newPool(rules = legacyRules): MaterialPool {
  return {
    tags: { items: [], countMin: rules.artist_min, countMax: rules.artist_max, weightMin: rules.artist_low, weightMax: rules.artist_high },
    loras: { items: [], countMin: rules.lora_min, countMax: rules.lora_max, weightMin: rules.lora_low, weightMax: rules.lora_high },
  };
}

export function materialPool(d: ExplorerDraft): MaterialPool {
  return d.materialPools[settingsKey(d)] ?? newPool();
}

export const loraKey = (lora: ExplorerLora) => lora.id ?? lora.name;

export function findLora(lora: ExplorerLora, catalog?: ExplorerLora[]) {
  return catalog?.find((option) => loraKey(option) === loraKey(lora));
}

function weightBounds(materials: ExplorerMaterial[]) {
  const endpoints = materials.flatMap(({ weight }) => weight.mode === 'fixed' ? [weight.value] : [weight.low, weight.high])
    .filter((value): value is number => value != null && Number.isFinite(value));
  return endpoints.length ? { weightMin: Math.min(...endpoints), weightMax: Math.max(...endpoints) } : {};
}

function migrateV2(pools: NonNullable<LegacyDraft['materialPools']>) {
  return Object.fromEntries(Object.entries(pools).map(([key, { materials, rules }]) => {
    const pool = newPool({ ...legacyRules, ...rules });
    const tags = materials.filter((row) => row.kind === 'tag' && row.mode !== 'exclude');
    const loras = key === 'novelai' ? [] : materials.filter((row) => row.kind === 'lora' && row.mode !== 'exclude');
    return [key, {
      tags: { ...pool.tags, ...weightBounds(tags), items: tags.map(({ name }) => name) },
      loras: { ...pool.loras, ...weightBounds(loras), items: loras.map(({ name, id, trigger_words }) => ({ name, id, trigger_words })) },
    }];
  }));
}

function migrateV1(value: LegacyDraft, settings: ExplorerDraft['settings']) {
  const tags = value.artists
    ? [...new Set(value.artists.filter(({ mode }) => mode !== 'exclude').map(({ name }) => name))]
    : parseNames(value.pool ?? '');
  const rules = { ...legacyRules, ...value.rules };
  const pools: Record<string, MaterialPool> = {};
  for (const [key, entry] of Object.entries(settings)) {
    const pool = newPool(rules);
    const loras = new Map<string, ExplorerLora>();
    if (key !== 'novelai' && Array.isArray(entry.loras)) {
      for (const item of entry.loras) {
        if (!item || typeof item !== 'object' || item.enabled === false) continue;
        const id = key === 'pixai' && typeof item.id === 'string' ? item.id : undefined;
        const name = typeof item.name === 'string' && item.name.trim() ? item.name.trim() : id;
        if (!name || (key === 'pixai' && !id)) continue;
        loras.set(id ?? name, { name, id, trigger_words: typeof item.trigger_words === 'string' ? item.trigger_words : undefined });
      }
    }
    pool.tags.items = tags;
    pool.loras.items = [...loras.values()];
    pools[key] = pool;
  }
  return pools;
}

export function storedDraft(workId?: string) {
  const current = localStorage.getItem(EXPLORER_DRAFT_KEY);
  if (current !== null) return { version: 3, raw: current } as const;
  const v2 = localStorage.getItem(V2_DRAFT_KEY);
  if (v2 !== null) return { version: 2, raw: v2 } as const;
  const v1 = workId ? localStorage.getItem(`atelierx-explorer-v1-${workId}`) : null;
  return v1 === null ? null : { version: 1, raw: v1 } as const;
}

export function readDraft(workId?: string): ExplorerDraft {
  const base = freshDraft();
  try {
    const stored = storedDraft(workId);
    if (!stored) return base;
    const value = JSON.parse(stored.raw);
    if (!value || !['comfyui', 'novelai', 'pixai'].includes(value.service)) return base;
    if (stored.version === 3) return { ...base, ...value, settings: { ...base.settings, ...value.settings } };
    const { artists, pool, rules, materialPools, ...draft } = value as LegacyDraft;
    const settings = { ...base.settings, ...draft.settings };
    const migratedPools = stored.version === 2 && materialPools
      ? migrateV2(materialPools)
      : migrateV1({ artists, pool, rules }, settings);
    for (const key of Object.keys(settings)) {
      const { loras: _loras, ...generation } = settings[key];
      settings[key] = generation;
    }
    return { ...base, ...draft, settings, materialPools: migratedPools };
  } catch {
    return base;
  }
}

export const loraLimit = (service: string, pixaiLimit = 5) =>
  service === 'novelai' ? 0 : service === 'pixai' ? pixaiLimit : 16;

export const loraWeightLimit = (service: string) => service === 'pixai' ? 1 : 10;

export function effectiveCount(group: MaterialGroup<unknown>, limit = group.items.length) {
  const cap = Math.min(group.items.length, limit);
  const max = Math.max(0, Math.min(group.countMax, cap));
  const min = Math.max(0, Math.min(group.countMin, max));
  return { min, max, cap };
}

export function effectiveRules(pool: MaterialPool, maxLoras: number): ExplorerSelectionRules {
  const { min: artist_min, max: artist_max } = effectiveCount(pool.tags);
  const { min: lora_min, max: lora_max } = effectiveCount(pool.loras, maxLoras);
  return { artist_min, artist_max, lora_min, lora_max };
}

export function validWeight(group: MaterialGroup<unknown>, max: number) {
  const { weightMin, weightMax } = group;
  return weightMin != null && weightMax != null && Number.isFinite(weightMin) && Number.isFinite(weightMax)
    && 0 <= weightMin && weightMin <= weightMax && weightMax <= max;
}

function groupWeight(group: MaterialGroup<unknown>): ExplorerWeight {
  return { mode: 'random', low: group.weightMin, high: group.weightMax, step: WEIGHT_STEP, include_high: true };
}

export function requestMaterials(pool: MaterialPool, catalog?: ExplorerLora[]): ExplorerMaterial[] {
  const tagWeight = groupWeight(pool.tags);
  const loraWeight = groupWeight(pool.loras);
  return [
    ...pool.tags.items.map((name): ExplorerMaterial => ({ kind: 'tag', name, weight: tagWeight })),
    ...pool.loras.items.map((lora): ExplorerMaterial => {
      const option = findLora(lora, catalog);
      return {
        ...lora,
        kind: 'lora',
        name: option?.name ?? lora.name,
        trigger_words: lora.trigger_words ?? option?.trigger_words,
        weight: loraWeight,
      };
    }),
  ];
}

export function switchContext(
  d: ExplorerDraft,
  context: Partial<Pick<ExplorerDraft, 'service' | 'family'>>,
): ExplorerDraft {
  const next = { ...d, ...context };
  const oldKey = settingsKey(d);
  const newKey = settingsKey(next);
  if (oldKey === newKey) return next;
  const modelPools = { ...d.modelPools, [oldKey]: d.models };
  return { ...next, modelPools, models: modelPools[newKey] ?? '' };
}
