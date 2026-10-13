// Synthetic settings for the single-image UI preview. None of these IDs name a real remote resource.
import type { Catalog, GenerationSettings } from './GenSettings';
import type { NovelAIInfo } from './NovelAISettings';
import type { PixAIInfo } from './PixAISettings';

export const COMFY_PREVIEW_DEFAULTS: GenerationSettings = {
  family: 'anima', model: 'demo-anima.safetensors', text_encoder: 'demo-encoder.safetensors',
  vae: 'demo-vae.safetensors', sampler: 'demo_sampler', scheduler: 'demo_schedule',
  width: 1024, height: 1024, steps: 24, cfg: 5, seed: -1, loras: [],
};
export const NOVELAI_PREVIEW_DEFAULTS: Record<string, unknown> = {
  model: 'demo-novelai', width: 1024, height: 1024, steps: 24, scale: 5, seed: -1,
  sampler: 'demo_sampler', noise_schedule: 'demo_schedule', quality_toggle: true, uc_preset: 0,
};
export const PIXAI_PREVIEW_DEFAULTS: Record<string, unknown> = {
  model: 'demo-pixai-sdxl', aspect_ratio: '1:1', size: 'demo-size', mode: 'demo-mode',
  sampler: 'demo_sampler', steps: 24, cfg_scale: 5, seed: -1, prompt_helper: false, loras: [],
};

export const COMFY_PREVIEW_CATALOG: Catalog = {
  connected: true,
  models: ['demo-anima.safetensors', 'checkpoint::demo-sdxl.safetensors'],
  text_encoders: ['demo-encoder.safetensors'], vaes: ['demo-vae.safetensors'],
  loras: ['demo-lora.safetensors'], samplers: ['demo_sampler'], schedulers: ['demo_schedule'],
  upscale_models: ['demo-upscale.pth'], nodes: { upscale: true, detailer: true },
  families: { models: { 'demo-anima.safetensors': 'anima', 'checkpoint::demo-sdxl.safetensors': 'sdxl' } },
  defaults: COMFY_PREVIEW_DEFAULTS,
};
export const NOVELAI_PREVIEW_INFO: NovelAIInfo = {
  models: [{ id: 'demo-novelai', name: 'Demo model' }],
  samplers: ['demo_sampler'], noise_schedules: ['demo_schedule'], defaults: NOVELAI_PREVIEW_DEFAULTS,
  // Required by the existing panel's calculation; subscription and pricing UI is hidden in preview mode.
  free: { pixels: 0, steps: 0 },
};
export const PIXAI_PREVIEW_INFO: PixAIInfo = {
  models: [{ id: 'demo-pixai-sdxl', name: 'Demo SDXL', type: 'sdxl' }, { id: 'demo-pixai-dit', name: 'Demo DiT', type: 'dit' }],
  aspect_ratios: ['1:1', '2:3', '3:2'], sizes: ['demo-size'], modes: ['demo-mode'], samplers: ['demo_sampler'],
  max_loras: 5, loras: [{ id: 'demo-pixai-lora', name: 'Demo LoRA', weight: 1, trigger_words: 'demo' }],
  defaults: PIXAI_PREVIEW_DEFAULTS,
};
