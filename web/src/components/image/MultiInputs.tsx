import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get } from '../../api';
import { t } from '../../i18n';
import type { MultiInput } from '../../imageTypes';

type Design = { appearance?: { prompt?: string[] }; outfits?: Record<string, { name?: string; slots?: Record<string, { prompt?: string[] }> }> };
export const freshMulti = (): MultiInput => ({ characters: [{ id: 'A', name: 'A', prompt: '' }, { id: 'B', name: 'B', prompt: '' }], left_id: 'A' });
export function multiPrompt(scene: string, value: MultiInput): string {
  const left = value.characters.find(p => p.id === value.left_id);
  const right = value.characters.find(p => p.id !== value.left_id);
  return `Two people. ${scene}. On the left: ${left?.prompt ?? ''}. On the right: ${right?.prompt ?? ''}.`;
}
export default function MultiInputs({ workId, value, onChange }: { workId: string; value: MultiInput; onChange: (v: MultiInput) => void }) {
  const designs = useQuery<{ id: string; name: string }[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const [target, setTarget] = useState('');
  const [character, setCharacter] = useState('');
  const [outfit, setOutfit] = useState('');
  const design = useQuery<{ design: Design | null }>({ queryKey: ['multi-import', workId, character], queryFn: () => get(`/api/works/${workId}/image/characters/${encodeURIComponent(character)}`), enabled: !!character });
  const d = design.data?.design;
  const imported = [...(d?.appearance?.prompt ?? []), ...Object.values(d?.outfits?.[outfit]?.slots ?? {}).flatMap(slot => slot.prompt ?? [])].join(', ');
  return <section className="col">
    <p className="faint">{t('multi.limit')}</p>
    <div className="row wrap">{value.characters.map(p => <label key={p.id} className="col grow">
      <span>{p.name} · {t(p.id === value.left_id ? 'multi.left' : 'multi.right')}</span>
      <textarea rows={5} value={p.prompt} aria-label={t('multi.person_prompt', { name: p.name })} onChange={e => onChange({ ...value, characters: value.characters.map(x => x.id === p.id ? { ...x, prompt: e.target.value } : x) })} />
      <button type="button" onClick={() => { setTarget(p.id); setCharacter(''); setOutfit(''); }}>{t('multi.import')}</button>
    </label>)}</div>
    <div className="row"><span>{value.characters.find(p => p.id === value.left_id)?.name} ← → {value.characters.find(p => p.id !== value.left_id)?.name}</span><button type="button" onClick={() => onChange({ ...value, left_id: value.characters.find(p => p.id !== value.left_id)!.id })}>{t('multi.swap')}</button></div>
    {value.characters.some(p => /\bsolo\b|\b1girl\b|\b1boy\b/.test(p.prompt)) && <p className="warn-text">{t('multi.count_warning')}</p>}
    {target && <section className="col single-handoff"><strong>{t('multi.import')} · {target}</strong>
      <label>{t('multi.character')}<select value={character} onChange={e => { setCharacter(e.target.value); setOutfit(''); }}><option value="">—</option>{(designs.data ?? []).map(d => <option key={d.id} value={d.id}>{d.name || d.id}</option>)}</select></label>
      <label>{t('multi.outfit')}<select value={outfit} onChange={e => setOutfit(e.target.value)}><option value="">—</option>{Object.entries(d?.outfits ?? {}).map(([id, o]) => <option key={id} value={id}>{o.name || id}</option>)}</select></label>
      <pre className="prompt-box">{imported}</pre>{design.isError && <p role="alert">{t('multi.import_failed')}</p>}
      <div className="row"><button disabled={!imported} onClick={() => { onChange({ ...value, characters: value.characters.map(p => p.id === target ? { ...p, prompt: [p.prompt, imported].filter(Boolean).join(', ') } : p) }); setTarget(''); }}>{t('multi.import_apply')}</button><button onClick={() => setTarget('')}>{t('common.cancel')}</button></div>
    </section>}
  </section>;
}
