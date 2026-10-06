// Library fragments with a group and the targets they are written for (#80). Empty targets fit everything.

export type Fragment = { id: string; name: string; group?: string; targets?: string[] };
export type Target = { id: string; name: string };

export const fits = (item: Fragment, target: string | undefined) => !target || !item.targets?.length || item.targets.includes(target);

// Items by group in the order groups first appear; items without a group come last.
export function byGroup<T extends Fragment>(items: T[]): { group: string; items: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const group = item.group?.trim() ?? '';
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  const named = [...groups.entries()].filter(([g]) => g).map(([group, list]) => ({ group, items: list }));
  return groups.has('') ? [...named, { group: '', items: groups.get('')! }] : named;
}

// What the generate screen lists for one target: the fitting items, plus chosen ones that do not fit (marked) so
// they can be unticked; the rest only when asked for.
export function visibleFor<T extends Fragment>(items: T[], target: string | undefined, chosen: string[], showOthers: boolean) {
  const others = items.filter((i) => !fits(i, target));
  return {
    shown: items.filter((i) => showOthers || fits(i, target) || chosen.includes(i.id)),
    hidden: showOthers ? 0 : others.filter((i) => !chosen.includes(i.id)).length,
  };
}

export const targetNames = (ids: string[] | undefined, targets: Target[]) => (ids ?? []).map((id) => targets.find((t) => t.id === id)?.name ?? id).join(', ');
