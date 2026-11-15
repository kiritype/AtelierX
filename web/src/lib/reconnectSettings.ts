import type { Preset } from '../components/image/PresetEditor';

// Keep edits made on the generation screen; reconnect only fields still pointing at the checked preset's file.
export function reconnectSettings<T extends object>(current: T, before?: Preset, after?: Preset): T {
  if (!before || !after) return current;
  const next = structuredClone(current) as Record<string, unknown>;
  for (const key of ['model', 'text_encoder', 'vae']) {
    if (next[key] === before.settings[key] && after.settings[key]) next[key] = after.settings[key];
  }
  const loras = next.loras as { name: string }[] | undefined;
  const oldLoras = before.settings.loras as { name: string }[] | undefined;
  const newLoras = after.settings.loras as { name: string }[] | undefined;
  loras?.forEach(lora => { const index = oldLoras?.findIndex(old => old.name === lora.name) ?? -1;
    if (index >= 0 && newLoras?.[index]) lora.name = newLoras[index].name;
  });
  const upscale = next.upscale as { model?: string } | undefined;
  const oldUpscale = before.settings.upscale as { model?: string } | undefined;
  const newUpscale = after.settings.upscale as { model?: string } | undefined;
  if (upscale?.model && upscale.model === oldUpscale?.model && newUpscale?.model) upscale.model = newUpscale.model;
  return next as T;
}
