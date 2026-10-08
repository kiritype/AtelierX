// The character × outfit table of the generate screen (#208): which outfits of different characters share a column.
// Outfits with the same deployment code share one, in ascending code order; outfits without a code share one by name
// when two or more characters have it. The rest go to the last "other outfits" column, inside each character's cell.
export type OutfitRef = { id: string; name: string; code?: string };
export type CharacterRef = { id: string; has_design: boolean; outfits: OutfitRef[] };
export type Column = { key: string; code: string; name: string; members: Record<string, string> };
export type Selection = Record<string, string[]>;

const byCode = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

export function outfitColumns(characters: CharacterRef[]): { columns: Column[]; others: Record<string, OutfitRef[]> } {
  const usable = characters.filter((c) => c.has_design);
  const codes = new Map<string, Column>();
  const names = new Map<string, Column>();
  const rest: [string, OutfitRef][] = [];
  for (const c of usable) {
    for (const o of c.outfits) {
      const code = (o.code ?? '').trim();
      if (code) {
        const column = codes.get(code) ?? { key: `code:${code}`, code, name: o.name, members: {} };
        // A second outfit of the same character with this code is not lost: it goes to the other outfits.
        if (column.members[c.id]) rest.push([c.id, o]);
        else column.members[c.id] = o.id;
        codes.set(code, column);
      } else rest.push([c.id, o]);
    }
  }
  const others: Record<string, OutfitRef[]> = {};
  const nameCount = new Map<string, Set<string>>();
  for (const [cid, o] of rest) if (!(o.code ?? '').trim()) nameCount.set(o.name, (nameCount.get(o.name) ?? new Set()).add(cid));
  for (const [cid, o] of rest) {
    const shared = !(o.code ?? '').trim() && (nameCount.get(o.name)?.size ?? 0) > 1;
    const column = shared ? names.get(o.name) ?? { key: `name:${o.name}`, code: '', name: o.name, members: {} } : null;
    if (column && !column.members[cid]) {
      column.members[cid] = o.id;
      names.set(o.name, column);
    } else (others[cid] ??= []).push(o);
  }
  // The column name is the one most of its outfits use.
  for (const column of codes.values()) {
    const counts = new Map<string, number>();
    for (const [cid, oid] of Object.entries(column.members)) {
      const name = usable.find((c) => c.id === cid)?.outfits.find((o) => o.id === oid)?.name ?? '';
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    column.name = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? column.name;
  }
  const columns = [...[...codes.values()].sort((a, b) => byCode.compare(a.code, b.code)), ...[...names.values()].sort((a, b) => byCode.compare(a.name, b.name))];
  return { columns, others };
}

type Check = 'all' | 'some' | 'none';
const state = (on: number, of: number): Check => (of === 0 || on === 0 ? 'none' : on === of ? 'all' : 'some');

export function allOutfits(characters: CharacterRef[]): Selection {
  return Object.fromEntries(characters.filter((c) => c.has_design && c.outfits.length).map((c) => [c.id, c.outfits.map((o) => o.id)]));
}

export function selectionState(selection: Selection, characters: CharacterRef[]): Check {
  const all = allOutfits(characters);
  const total = Object.values(all).reduce((n, list) => n + list.length, 0);
  const on = Object.entries(all).reduce((n, [cid, list]) => n + list.filter((o) => selection[cid]?.includes(o)).length, 0);
  return state(on, total);
}

export function rowState(selection: Selection, character: CharacterRef): Check {
  return state(character.outfits.filter((o) => selection[character.id]?.includes(o.id)).length, character.outfits.length);
}

export function columnState(selection: Selection, column: Column): Check {
  const pairs = Object.entries(column.members);
  return state(pairs.filter(([cid, oid]) => selection[cid]?.includes(oid)).length, pairs.length);
}

// Turn one outfit of one character on or off; a character with no outfit left is not chosen any more.
export function setOutfit(selection: Selection, cid: string, oid: string, on: boolean): Selection {
  const list = selection[cid] ?? [];
  const next = on ? [...new Set([...list, oid])] : list.filter((x) => x !== oid);
  const out = { ...selection };
  if (next.length) out[cid] = next;
  else delete out[cid];
  return out;
}

export function setRow(selection: Selection, character: CharacterRef, on: boolean): Selection {
  return character.outfits.reduce((s, o) => setOutfit(s, character.id, o.id, on), selection);
}

export function setColumn(selection: Selection, column: Column, on: boolean): Selection {
  return Object.entries(column.members).reduce((s, [cid, oid]) => setOutfit(s, cid, oid, on), selection);
}
