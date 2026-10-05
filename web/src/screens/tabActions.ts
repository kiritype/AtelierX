export function bulkCloseKeys(keys: string[], anchor: string, pinned: string[], mode: 'others' | 'right') {
  const anchorIndex = keys.indexOf(anchor);
  return keys.filter((key, index) => key !== anchor && !pinned.includes(key) && (mode === 'others' || index > anchorIndex));
}

export function nextActiveKey(keys: string[], closing: Set<string>, active: string | null) {
  if (!active || !closing.has(active)) return active;
  const index = keys.indexOf(active);
  const remaining = keys.filter((key) => !closing.has(key));
  return remaining.length ? remaining[Math.min(Math.max(index, 0), remaining.length - 1)] : null;
}

// Tabs whose inputs hold data that is saved with a button there (settings, the prompt library, LoRA captions …). Image
// screens that only choose what to run (generate, queue, compare, gallery filters, tool selections) keep nothing to
// save, so typing or ticking there never asks "save before leaving?". Item tabs report their own state.
const RUN_VIEWS = new Set(['generate', 'queue', 'lab', 'gallery', 'tools']);
export function tracksFormChanges(tab: { type: string; view?: string }) {
  // The settings tab's forms report their own unsaved state (settingsDirty.ts); several of them save at once.
  if (tab.type === 'item' || tab.type === 'settings') return false;
  return !(tab.type === 'image' && RUN_VIEWS.has(tab.view ?? ''));
}
