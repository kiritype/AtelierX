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
      artist: { positive: '@watercolor', negative: '@bad' },
    });
    expect(draft).toEqual({
      service: 'comfyui',
      family: 'sdxl',
      settings: { family: 'sdxl', model: 'illustrious.safetensors', sampler: 'euler', steps: 28, cfg: 5, seed: -1, loras: [{ name: 'style.safetensors', strength: 0.6 }] },
      common: ['quality'],
      artist: { positive: '@watercolor', negative: '@bad' },
      droppedLoras: ['C001-e04.safetensors'],
    });
  });

  it('copes with a record that has no settings or ids', () => {
    expect(presetFromRecord({ common_ids: null })).toEqual({
      service: 'comfyui',
      family: 'anima',
      settings: { seed: -1 },
      common: [],
      artist: { positive: '', negative: '' },
      droppedLoras: [],
    });
  });

  it('reads the artist tags of older records from their style part, and keeps an internet service', () => {
    const draft = presetFromRecord({ service: 'novelai', settings: { model: 'nai-diffusion-4-5-full' }, parts: { style: 'artist:foo' } });
    expect([draft.service, draft.family, draft.artist.positive]).toEqual(['novelai', 'novelai', 'artist:foo']);
  });
});
