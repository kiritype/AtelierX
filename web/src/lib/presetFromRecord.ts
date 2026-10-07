// A style preset made from a gallery image's record (#52, #169): the settings and artist tags that can be reused for any
// character. What belongs to the character stays out: appearance, outfit and expression are composed per target, the
// character's automatic LoRAs are added again per character, and the seed is drawn anew.
export type RecordLora = { name: string; auto?: string; [key: string]: unknown };
export type ImageRecord = {
  service?: string;
  settings?: Record<string, unknown> & { family?: string; loras?: RecordLora[] };
  common_ids?: string[] | null;
  artist?: { positive?: string; negative?: string } | null;
  // Records from before #169 kept the style fragments' text as the "style" part.
  parts?: Record<string, string> | null;
};
export type PresetDraft = {
  service: string;
  family: string;
  settings: Record<string, unknown>;
  common: string[];
  artist: { positive: string; negative: string };
  droppedLoras: string[];
};

export const PRESET_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function presetFromRecord(record: ImageRecord): PresetDraft {
  const { seed: _seed, loras = [], ...rest } = record.settings ?? {};
  const kept = loras.filter((lora) => !lora.auto);
  const service = record.service && record.service !== 'comfyui' ? record.service : 'comfyui';
  return {
    service,
    family: service !== 'comfyui' ? service : rest.family === 'sdxl' ? 'sdxl' : 'anima',
    settings: { ...rest, seed: -1, ...(kept.length ? { loras: kept } : {}) },
    common: [...(record.common_ids ?? [])],
    artist: {
      positive: record.artist?.positive ?? record.parts?.artist ?? record.parts?.style ?? '',
      negative: record.artist?.negative ?? '',
    },
    droppedLoras: loras.filter((lora) => lora.auto).map((lora) => lora.name),
  };
}
