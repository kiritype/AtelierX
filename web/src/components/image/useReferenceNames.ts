import { useQueries, useQuery } from '@tanstack/react-query';
import { get } from '../../api';
import type { WorkList } from '../../types';

// Resolve display names at render time. IDs remain the values used by filters and requests.
export function useReferenceNames(workIds: string[]) {
  const works = useQuery<WorkList>({ queryKey: ['works'], queryFn: () => get('/api/works') });
  const ids = [...new Set(workIds.filter(Boolean))];
  const workRows = Array.isArray(works.data?.works) ? works.data.works : [];
  const known = new Set(workRows.map((work) => work.id));
  const designs = useQueries({ queries: ids.map((id) => ({
    queryKey: ['image-designs', id],
    queryFn: (): Promise<{ id: string; name: string; outfits?: { id: string; name: string }[] }[]> => get(`/api/works/${id}/image/designs`),
    staleTime: 30000,
    enabled: known.has(id),
    retry: false,
  })) });
  const workNames = new Map(workRows.map((work) => [work.id, work.name]));
  const workCounts = new Map<string, number>();
  for (const work of workRows) if (work.name?.trim()) workCounts.set(work.name.trim(), (workCounts.get(work.name.trim()) ?? 0) + 1);
  const rows = designs.map((query) => Array.isArray(query.data) ? query.data : []);
  const characterNames = new Map(ids.map((id, index) => [id, new Map(rows[index].map((design) => [design.id, design.name]))]));
  const characterCounts = new Map(ids.map((id, index) => {
    const counts = new Map<string, number>();
    for (const design of rows[index]) if (design.name?.trim()) counts.set(design.name.trim(), (counts.get(design.name.trim()) ?? 0) + 1);
    return [id, counts] as const;
  }));
  const outfitNames = new Map(ids.map((id, index) => [id, new Map(rows[index].flatMap((design) => (design.outfits ?? []).map((outfit) => [`${design.id}\u0000${outfit.id}`, outfit.name] as const)))]));
  return {
    workName: (id: string) => {
      const name = workNames.get(id)?.trim();
      return name ? `${name}${(workCounts.get(name) ?? 0) > 1 ? ` (${id})` : ''}` : id;
    },
    characterName: (workId: string, id: string) => {
      const name = characterNames.get(workId)?.get(id)?.trim();
      return name ? `${name}${(characterCounts.get(workId)?.get(name) ?? 0) > 1 ? ` (${id})` : ''}` : id;
    },
    outfitName: (workId: string, characterId: string, id: string) => outfitNames.get(workId)?.get(`${characterId}\u0000${id}`)?.trim() || id,
  };
}
