import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';

type Design = { id: string; name: string; has_design: boolean; outfits: { id: string; name: string }[] };
type Expression = { id: string; name: string };

// Bring a lab result into a character's outfit × expression combination (#53): it joins the gallery with its
// generation record, and can be adopted right away.
export default function LabImport({ workId, path, onDone }: { workId: string; path: string; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const expressions = useQuery<Record<string, Expression>>({
    queryKey: ['image-lib', 'expressions', workId],
    queryFn: () => get(`/api/image/library/expressions?work=${workId}`),
  });
  const characters = (designs.data ?? []).filter((d) => d.has_design && d.outfits.length);
  const [characterId, setCharacterId] = useState('');
  const [outfitId, setOutfitId] = useState('');
  const [expressionId, setExpressionId] = useState('');
  const [adopt, setAdopt] = useState(true);
  const [busy, setBusy] = useState(false);
  const character = characters.find((c) => c.id === characterId);

  async function run() {
    setBusy(true);
    try {
      const imported = await post<{ path: string }>('/api/image/lab/import', {
        path,
        work_id: workId,
        character_id: characterId,
        outfit_id: outfitId,
        expression_id: expressionId,
      });
      if (adopt) await post('/api/image/gallery/review', { verdict: 'pass', items: [{ path: imported.path }] });
      qc.invalidateQueries({ queryKey: ['gallery-tree'] });
      qc.invalidateQueries({ queryKey: ['image-board', workId] });
      toast({ text: t(adopt ? 'lab.imported_adopted' : 'lab.imported', { path: imported.path }) });
      onDone();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="col lab-import">
      <div className="section-title">{t('lab.import_title')}</div>
      {characters.length === 0 && <div className="faint small">{t('lab.import_no_characters')}</div>}
      <div className="row wrap">
        <select
          aria-label={t('lab.import_character')}
          value={characterId}
          onChange={(e) => {
            setCharacterId(e.target.value);
            setOutfitId('');
          }}
        >
          <option value="">{t('lab.import_character')}</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.id})
            </option>
          ))}
        </select>
        <select aria-label={t('lab.import_outfit')} value={outfitId} disabled={!character} onChange={(e) => setOutfitId(e.target.value)}>
          <option value="">{t('lab.import_outfit')}</option>
          {(character?.outfits ?? []).map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <select aria-label={t('lab.import_expression')} value={expressionId} onChange={(e) => setExpressionId(e.target.value)}>
          <option value="">{t('lab.import_expression')}</option>
          {Object.values(expressions.data ?? {}).map((x) => (
            <option key={x.id} value={x.id}>
              {x.name}
            </option>
          ))}
        </select>
        <label className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={adopt} onChange={(e) => setAdopt(e.target.checked)} />
          {t('lab.import_adopt')}
        </label>
      </div>
      <div className="row">
        <button className="primary" disabled={busy || !characterId || !outfitId || !expressionId} onClick={run}>
          {t('lab.import_run')}
        </button>
        <button className="ghost" onClick={onDone}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}
