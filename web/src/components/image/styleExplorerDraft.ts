import { FAMILY_DEFAULTS } from './GenSettings';
import type { ExplorerArtist, ExplorerMaterial, ExplorerRules, ExplorerSelectionRules, ExplorerWeight } from '../../styleExplorerTypes';

export const EXPLORER_DRAFT_KEY = 'atelierx-explorer-v2-global';

const defaultRules: ExplorerRules = {
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
const { artist_min, artist_max, lora_min, lora_max } = defaultRules;
const defaultCounts = { artist_min, artist_max, lora_min, lora_max };
type MaterialPool = { materials: ExplorerMaterial[]; rules: ExplorerSelectionRules };
type LegacyDraft = Partial<ExplorerDraft> & { artists?: ExplorerArtist[]; pool?: string; rules?: Partial<ExplorerRules> };

export type ExplorerLoraOption = { name: string; id?: string; weight?: number; trigger_words?: string };
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

export function materialPool(d: ExplorerDraft): MaterialPool {
  return d.materialPools[settingsKey(d)] ?? { materials: [], rules: { ...defaultCounts } };
}

export const materialKey = (material: Pick<ExplorerMaterial, 'kind' | 'name' | 'id'>) =>
  `${material.kind}:${material.id ?? material.name}`;

export function findLora(material: Pick<ExplorerLoraOption, 'id' | 'name'>, options?: ExplorerLoraOption[]) {
  return options?.find((option) => (option.id ?? option.name) === (material.id ?? material.name));
}

export function randomWeight(kind: ExplorerMaterial['kind'], rules = defaultRules): ExplorerWeight {
  return kind === 'tag'
    ? { mode: 'random', low: rules.artist_low, high: rules.artist_high, step: rules.artist_step }
    : { mode: 'random', low: rules.lora_low, high: rules.lora_high, step: rules.lora_step };
}

function migrateMaterials(value: LegacyDraft, settings: ExplorerDraft['settings']) {
  const rules = { ...defaultRules, ...value.rules };
  const { artist_min, artist_max, lora_min, lora_max } = rules;
  const counts = { artist_min, artist_max, lora_min, lora_max };
  const tags = (value.artists ?? parseNames(value.pool ?? '').map((name) => ({ name, mode: 'candidate' as const })))
    .map((artist): ExplorerMaterial => ({ ...artist, kind: 'tag', role: 'style', weight: randomWeight('tag', rules) }));
  const pools: Record<string, MaterialPool> = {};
  for (const [key, entry] of Object.entries(settings)) {
    const loras: ExplorerMaterial[] = [];
    if (key !== 'novelai' && Array.isArray(entry.loras)) {
      for (const item of entry.loras) {
        if (!item || typeof item !== 'object') continue;
        const id = key === 'pixai' && typeof item.id === 'string' ? item.id : undefined;
        const name = typeof item.name === 'string' && item.name.trim() ? item.name.trim() : id;
        if (!name || (key === 'pixai' && !id)) continue;
        loras.push({
          kind: 'lora',
          name,
          ...(id ? { id } : {}),
          role: 'style',
          mode: item.enabled === false ? 'exclude' : 'candidate',
          weight: randomWeight('lora', rules),
          ...(typeof item.trigger_words === 'string' ? { trigger_words: item.trigger_words } : {}),
        });
      }
    }
    const unique = new Map([...tags, ...loras].map((material) => [materialKey(material), material]));
    pools[key] = { materials: [...unique.values()], rules: { ...counts } };
  }
  return pools;
}

export const legacyDraftKey = (workId: string) => `atelierx-explorer-v1-${workId}`;

export function readDraft(workId?: string): ExplorerDraft {
  const base = freshDraft();
  try {
    const stored = localStorage.getItem(EXPLORER_DRAFT_KEY)
      ?? (workId ? localStorage.getItem(legacyDraftKey(workId)) : null);
    const value: LegacyDraft | null = JSON.parse(stored ?? 'null');
    if (!value?.service || !['comfyui', 'novelai', 'pixai'].includes(value.service)) return base;
    const { artists, pool, rules, ...draft } = value;
    const settings = { ...base.settings, ...value.settings };
    const materialPools = value.materialPools ?? migrateMaterials({ artists, pool, rules }, settings);
    for (const key of Object.keys(settings)) {
      const { loras: _loras, ...generation } = settings[key];
      settings[key] = generation;
    }
    return { ...base, ...draft, materialPools, settings };
  } catch {
    return base;
  }
}

export function materialCounts(materials: ExplorerMaterial[], kind: ExplorerMaterial['kind']) {
  const eligible = materials.filter((material) => material.kind === kind && material.mode !== 'exclude');
  return { available: eligible.length, always: eligible.filter((material) => material.mode === 'always').length };
}

export const loraLimit = (service: string, pixaiLimit = 5) =>
  service === 'novelai' ? 0 : service === 'pixai' ? pixaiLimit : 16;

export function effectiveRules(d: ExplorerDraft, maxLoras = loraLimit(d.service)): ExplorerSelectionRules {
  const { materials, rules } = materialPool(d);
  const tags = materialCounts(materials, 'tag');
  const loras = materialCounts(materials, 'lora');
  const artistMax = Math.max(tags.always, Math.min(rules.artist_max, tags.available));
  const loraMax = Math.min(maxLoras, Math.max(loras.always, Math.min(rules.lora_max, loras.available)));
  return {
    artist_min: Math.max(tags.always, Math.min(rules.artist_min, artistMax)),
    artist_max: artistMax,
    lora_min: Math.min(loraMax, Math.max(loras.always, rules.lora_min)),
    lora_max: loraMax,
  };
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
