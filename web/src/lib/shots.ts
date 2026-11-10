import { useQuery } from '@tanstack/react-query';
import { get } from '../api';
import { t } from '../i18n';
import { fits, type Fragment, type Target } from './fragments';

const FRAMES = ['face', 'upper', 'cowboy', 'full'] as const;
const DIRECTIONS = ['front', 'three_quarter', 'side', 'back'] as const;
const HEIGHTS = ['eye', 'high', 'low'] as const;

export const SHOT_OPTIONS = { framing: FRAMES, direction: DIRECTIONS, height: HEIGHTS };
export type Shot = { framing: typeof FRAMES[number]; direction: typeof DIRECTIONS[number]; height: typeof HEIGHTS[number] };
export type ShotChoice = { mode: 'auto' } | { mode: 'visual'; shot: Shot } | { mode: 'library'; id: string };
export type Composition = Fragment & { prompt?: string[]; negative?: string[]; suggest_slots?: string[]; hide_outfit?: boolean };
export type CompositionSource = { kind: 'composition'; id: string; name: string; positive: string; negative: string };
export type ShotRules = {
  ratings: Target[];
  slots: Target[];
  shot_choices: {
    framing: Record<Shot['framing'], { prompt: string; slots: string[] | null }>;
    direction: Record<Shot['direction'], string>;
    height: Record<Shot['height'], string>;
  };
};

export const DEFAULT_SHOT: Shot = { framing: 'upper', direction: 'front', height: 'eye' };
export const AUTO_SHOT: ShotChoice = { mode: 'auto' };

export function useShotLibrary(workId: string) {
  const compositions = useQuery({
    queryKey: ['image-lib', 'compositions', workId],
    queryFn: () => get<Record<string, Composition>>(`/api/image/library/compositions?work=${workId}`),
  });
  const rules = useQuery({
    queryKey: ['image-lib-rules'],
    queryFn: () => get<ShotRules>('/api/image/library/rules'),
  });
  return { compositions, rules };
}

export function shotLabel(shot: Shot): string {
  return [t(`shot.framing.${shot.framing}`), t(`shot.direction.${shot.direction}`), t(`shot.height.${shot.height}`)].join(' · ');
}

export function shotChoiceFromSource(id: string): ShotChoice {
  if (!id) return AUTO_SHOT;
  if (!id.startsWith('shot:')) return { mode: 'library', id };
  const [, framing, direction, height, ...rest] = id.split(':');
  const shot = { framing, direction, height } as Shot;
  return !rest.length && FRAMES.includes(shot.framing) && DIRECTIONS.includes(shot.direction) && HEIGHTS.includes(shot.height)
    ? { mode: 'visual', shot }
    : AUTO_SHOT;
}

export function shotChoiceRequest(choice: ShotChoice): { shot?: Shot; composition_id?: string } {
  if (choice.mode === 'visual') return { shot: choice.shot };
  if (choice.mode === 'library' && choice.id) return { composition_id: choice.id };
  return {};
}

function joinedTags(tags: string[] | undefined) {
  const clean = (tags ?? []).map(tag => {
    const note = /(?:^|(?<=[\s,]))#/.exec(tag);
    return (note ? tag.slice(0, note.index) : tag).replaceAll('\\#', '#').trim();
  });
  return [...new Set(clean.filter(Boolean))].join(', ');
}

export function compositionSource(choice: ShotChoice, rules: ShotRules | undefined, compositions: Record<string, Composition> | undefined, target: string | undefined): CompositionSource | undefined {
  if (choice.mode === 'visual' && rules?.shot_choices) {
    const { framing, direction, height } = choice.shot;
    const choices = rules.shot_choices;
    return {
      kind: 'composition',
      id: `shot:${framing}:${direction}:${height}`,
      name: shotLabel(choice.shot),
      positive: [choices.framing[framing].prompt, choices.direction[direction], choices.height[height]].join(', '),
      negative: '',
    };
  }
  const item = choice.mode === 'library' ? compositions?.[choice.id] : undefined;
  return item && fits(item, target) ? {
    kind: 'composition', id: item.id, name: item.name, positive: joinedTags(item.prompt), negative: joinedTags(item.negative),
  } : undefined;
}

export function shotSlotLabels(slots: string[], rules: ShotRules | undefined) {
  return slots.map(slot => {
    const key = `shot.slot.${slot}`;
    const label = t(key);
    return label !== key ? label : rules?.slots.find(item => item.id === slot)?.name ?? slot;
  }).join(', ');
}
