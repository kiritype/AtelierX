import { describe, expect, it } from 'vitest';
import { settingsFromPreset } from './presetSettings';

const DEFAULTS = { anima: { steps: 32, cfg: 5, width: 1536, height: 1536 }, sdxl: { steps: 28, cfg: 5, width: 1024, height: 1024 } };
const current = { family: 'anima' as const, model: 'anima-base.safetensors', steps: 25, cfg: 4, width: 1216, height: 1536, seed: 7, loras: [{ name: 'a' }] };

describe('settings from a style preset', () => {
  it('replaces everything with a preset that names a model', () => {
    const next = settingsFromPreset(current, { model: 'other.safetensors', steps: 30 }, 'anima', DEFAULTS);
    expect(next).toEqual({ model: 'other.safetensors', steps: 30, family: 'anima', seed: -1 });
  });

  it('keeps what a partial preset does not set', () => {
    expect(settingsFromPreset(current, {}, 'anima', DEFAULTS)).toEqual(current);
    expect(settingsFromPreset(current, { steps: 24, cfg: 4.5 }, 'anima', DEFAULTS)).toEqual({ ...current, steps: 24, cfg: 4.5 });
  });

  it('starts from the family defaults for a partial preset of another family', () => {
    expect(settingsFromPreset(current, { cfg: 6 }, 'sdxl', DEFAULTS)).toEqual({ steps: 28, cfg: 6, width: 1024, height: 1024, family: 'sdxl', seed: 7 });
  });
});
