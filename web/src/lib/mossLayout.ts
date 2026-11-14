import type { MossDocument, MossItem } from '../imageTypes';

export const freshMoss = (): MossDocument => ({ schema_version: 1, mode: 'general', width: 1024, height: 1024, scene: '', items: [] });
export const mossJoin = (...parts: (string | undefined)[]) => parts.filter(p => p?.trim()).map(p => p!.trim()).join(', ');
export const validRect = (r: number[]) => r.length === 4 && r.every(Number.isFinite) && Math.min(r[0], r[1]) >= 0 && Math.min(r[2], r[3]) > 0 && r[0] + r[2] <= 1 + 1e-9 && r[1] + r[3] <= 1 + 1e-9;
export function mossErrors(doc: MossDocument, batch = false): string[] {
  const errors: string[] = [];
  if (!doc.scene.trim()) errors.push('scene');
  if (!doc.items.length || doc.items.length > 32) errors.push('items');
  for (const item of doc.items) {
    if (!validRect(item.rect)) errors.push(`${item.id}:rect`);
    if (!(batch && item.binding === 'target') && (!mossJoin(item.resolved?.caption, item.caption) || (item.binding === 'target' && !item.resolved?.caption.trim()))) errors.push(`${item.id}:caption`);
    if (item.label === 'text' && !item.text?.trim()) errors.push(`${item.id}:text`);
  }
  if (![doc.width, doc.height].every(n => Number.isInteger(n) && n >= 256 && n <= 3072 && n % 16 === 0)) errors.push('size');
  return errors;
}
// Same enclosure rounding as the native MOSSImageLayoutPrompt. This is only a preview;
// generation always validates and compiles again on the server.
export function compileMoss(doc: MossDocument, sceneMaterial = '') {
  const round = (n: number) => Math.round(n * 1e9) / 1e9;
  return JSON.stringify({ summary: { caption: mossJoin(doc.scene, sceneMaterial) }, items: doc.items.map(item => {
    const [x, y, w, h] = item.rect;
    return { label: item.label, caption: mossJoin(item.resolved?.caption, item.caption),
      bbox: [Math.floor(round(y * doc.height)) - doc.height / 2, Math.floor(round(x * doc.width)) - doc.width / 2,
        Math.ceil(round((y + h) * doc.height)) - doc.height / 2, Math.ceil(round((x + w) * doc.width)) - doc.width / 2],
      ...(item.label === 'text' ? { text: item.text ?? '' } : {}) };
  }), bbox_coord_space: 'abs_centralized', bbox_format: 'yxyx' });
}
export function templateMoss(doc: MossDocument): MossDocument {
  return { ...doc, items: doc.items.map(({ resolved: _resolved, ...item }) => item) };
}
export const newMossItem = (label: MossItem['label']): MossItem => ({ id: crypto.randomUUID(), name: '', label, caption: '', binding: 'manual', rect: [0.2, 0.15, 0.4, 0.65], ...(label === 'text' ? { text: '' } : {}) });
