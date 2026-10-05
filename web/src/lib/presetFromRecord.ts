// A generation preset made from a gallery image's record (#52): the settings that can be reused for any character.
// What belongs to the character stays out: appearance, outfit and expression are composed per target, the character's
// automatic LoRAs are added again per character, and the seed is drawn anew.
export type RecordLora = { name: string; auto?: string; [key: string]: unknown };
export type ImageRecord = {
  settings?: Record<string, unknown> & { family?: string; loras?: RecordLora[] };
  common_ids?: string[] | null;
  style_ids?: string[] | null;
};
export type PresetDraft = {
  family: 'anima' | 'sdxl';
  settings: Record<string, unknown>;
  common: string[];
  styles: string[];
  droppedLoras: string[];
};

export const PRESET_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function presetFromRecord(record: ImageRecord): PresetDraft {
  const { seed: _seed, loras = [], ...rest } = record.settings ?? {};
  const kept = loras.filter((lora) => !lora.auto);
  return {
    family: rest.family === 'sdxl' ? 'sdxl' : 'anima',
    settings: { ...rest, seed: -1, ...(kept.length ? { loras: kept } : {}) },
    common: [...(record.common_ids ?? [])],
    styles: [...(record.style_ids ?? [])],
    droppedLoras: loras.filter((lora) => lora.auto).map((lora) => lora.name),
  };
}
