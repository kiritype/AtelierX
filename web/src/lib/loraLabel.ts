import type { LoraRef } from '../imageTypes';

export function loraLabel(lora: Partial<LoraRef>) {
  const model = lora.strength_model ?? lora.strength ?? lora.model_strength ?? lora.weight ?? 1;
  const clip = lora.strength_clip ?? lora.clip_strength;
  return `${lora.name ?? lora.id ?? 'LoRA'} (${model}${clip === undefined ? '' : ` · CLIP ${clip}`})`;
}
