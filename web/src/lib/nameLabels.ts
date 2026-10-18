type Named = { id: string; name: string };

export const displayName = (item: Named) => item.name.trim() || item.id;

// Only names that collide need an ID hint. Extend the prefix if two IDs begin alike.
export function nameIdHint(item: Named, peers: Named[]): string | null {
  const name = item.name.trim();
  const sameName = peers.filter((peer) => peer.id !== item.id && name && peer.name.trim() === name);
  if (!sameName.length) return null;
  for (let size = Math.min(8, item.id.length); size < item.id.length; size++) {
    if (sameName.every((peer) => peer.id.slice(0, size) !== item.id.slice(0, size))) {
      return item.id.slice(0, size);
    }
  }
  return item.id;
}

export function nameLabel(item: Named, peers: Named[]): string {
  const hint = nameIdHint(item, peers);
  return displayName(item) + (hint ? ` (${hint})` : '');
}
