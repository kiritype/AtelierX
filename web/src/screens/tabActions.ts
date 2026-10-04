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
