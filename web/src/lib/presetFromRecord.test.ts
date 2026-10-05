import { describe, expect, it } from 'vitest';
import { presetFromRecord } from './presetFromRecord';

describe('presetFromRecord', () => {
  it('keeps reusable settings and leaves the character, its LoRAs and the seed out', () => {
    const draft = presetFromRecord({
      settings: {
        family: 'sdxl',
        model: 'illustrious.safetensors',
        sampler: 'euler',
        steps: 28,
        cfg: 5,
        seed: 1234,
        loras: [
          { name: 'style.safetensors', strength: 0.6 },
          { name: 'C001-e04.safetensors', strength: 0.8, auto: 'L001' },
        ],
      },
      common_ids: ['quality'],
      style_ids: ['watercolor'],
    });
    expect(draft).toEqual({
      family: 'sdxl',
      settings: { family: 'sdxl', model: 'illustrious.safetensors', sampler: 'euler', steps: 28, cfg: 5, seed: -1, loras: [{ name: 'style.safetensors', strength: 0.6 }] },
      common: ['quality'],
      styles: ['watercolor'],
      droppedLoras: ['C001-e04.safetensors'],
    });
  });

  it('copes with a record that has no settings or ids', () => {
    expect(presetFromRecord({ common_ids: null })).toEqual({ family: 'anima', settings: { seed: -1 }, common: [], styles: [], droppedLoras: [] });
  });
});
