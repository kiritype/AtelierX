import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import type { MossResolved } from '../../imageTypes';
import { mossJoin } from '../../lib/mossLayout';

type Design = { id: string; name: string; has_design: boolean; default_outfit?: string; outfits: { id: string; name: string }[] };
type Expression = { id: string; name: string; targets?: string[] };
type ComposedTarget = { character_id: string; outfit_id: string; expression_id: string; outfit_name: string; expression_name: string; parts: Record<string, string>; negative: string };

export default function MossTargetPicker({ workId, value, onChange }: { workId: string; value?: MossResolved; onChange: (value: MossResolved) => void }) {
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const expressions = useQuery<Record<string, Expression>>({ queryKey: ['image-lib', 'expressions', workId], queryFn: () => get(`/api/image/library/expressions?work=${workId}`) });
  const [target, setTarget] = useState({ character_id: value?.character_id ?? '', outfit_id: value?.outfit_id ?? '', expression_id: value?.expression_id ?? '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const character = designs.data?.find(d => d.id === target.character_id);
  async function apply() {
    setBusy(true); setError('');
    try {
      const [result] = await post<ComposedTarget[]>(`/api/works/${workId}/image/compose`, { service: 'comfyui', settings: { family: 'moss' }, targets: [target], common_ids: [], artist: {}, trigger: false });
      onChange({ ...target, name: mossJoin(character?.name, result.outfit_name, result.expression_name),
        caption: mossJoin(...['trigger', 'appearance', 'outfit', 'expression'].map(key => result.parts[key])), negative: result.negative });
    } catch (err) { setError(err instanceof ApiError ? tm(err.msg) : String(err)); }
    finally { setBusy(false); }
  }
  return <fieldset className="moss-target" disabled={busy}><legend>{t('moss.target')}</legend>
    <label>{t('materials.character')}<select value={target.character_id} onChange={e => {
      const design = designs.data?.find(d => d.id === e.target.value);
      setTarget({ ...target, character_id: e.target.value, outfit_id: design?.default_outfit ?? design?.outfits[0]?.id ?? '' });
    }}><option value="">{t('materials.choose')}</option>{designs.data?.filter(d => d.has_design).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
    <label>{t('moss.outfit')}<select value={target.outfit_id} onChange={e => setTarget({ ...target, outfit_id: e.target.value })}><option value="">{t('materials.choose')}</option>{character?.outfits.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
    <label>{t('materials.expression')}<select value={target.expression_id} onChange={e => setTarget({ ...target, expression_id: e.target.value })}><option value="">{t('materials.choose')}</option>{Object.values(expressions.data ?? {}).filter(e => !e.targets?.length || e.targets.includes('moss')).map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
    <button type="button" disabled={!target.character_id || !target.outfit_id || !target.expression_id} onClick={apply}>{t('moss.apply_target')}</button>
    {value && <p className="small">{value.name}</p>}{error && <p role="alert">{error}</p>}
  </fieldset>;
}
