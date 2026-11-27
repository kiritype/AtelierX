import { useQuery } from '@tanstack/react-query';
import { useId, useState, type ReactNode } from 'react';
import { ApiError, get, post } from '../../api';
import type { MossTemplate, ReferenceEmotionComposition, ReferenceEmotionPreview, ReferenceEmotionSelection } from '../../imageTypes';
import { t, tm } from '../../i18n';
import { byGroup, fits, type Fragment } from '../../lib/fragments';

const endpoint = '/api/image/reference/emotions';
type Preview = ReferenceEmotionPreview & { key: string };

export default function ReferenceEmotions({ family, shown, active, ready, busy, readiness, enqueue, openQueue }: {
  family: ReferenceEmotionSelection['family'];
  shown: boolean;
  active: boolean;
  ready: boolean;
  busy: boolean;
  readiness: ReactNode;
  enqueue: (selection: ReferenceEmotionSelection, revision: string, previewStale: (message: string) => void) => void;
  openQueue: () => void;
}) {
  const id = useId();
  const expressions = useQuery<Record<string, Fragment>>({
    queryKey: ['image-lib', 'expressions', undefined],
    queryFn: () => get('/api/image/library/expressions'),
    enabled: active && shown,
  });
  const [chosen, setChosen] = useState<string[]>([]);
  const [mode, setMode] = useState<ReferenceEmotionComposition['mode']>('none');
  const [compositionId, setCompositionId] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<{ key: string; text: string } | null>(null);
  const compositions = useQuery<Record<string, MossTemplate>>({
    queryKey: ['image-lib', 'compositions', undefined],
    queryFn: () => get('/api/image/library/compositions'),
    enabled: active && shown && mode === 'library',
  });
  const expressionChoices = Object.values(expressions.data ?? {}).filter(item => fits(item, family));
  const compositionChoices = Object.values(compositions.data ?? {}).filter(item => !item.moss_layout && fits(item, family));
  const selectedComposition = compositionChoices.find(item => item.id === compositionId);
  const selection: ReferenceEmotionSelection = {
    family,
    expression_ids: expressionChoices.filter(item => chosen.includes(item.id)).map(item => item.id),
    composition: mode === 'library' ? { mode, id: selectedComposition?.id ?? '' } : { mode },
  };
  const key = JSON.stringify(selection);
  const currentPreview = preview?.key === key ? preview : null;
  const canPreview = !!selection.expression_ids.length && !expressions.isError
    && (mode !== 'library' || (!!selectedComposition && !compositions.isError));
  const canQueue = ready && !busy && canPreview && !!currentPreview?.rows.length && !pending;

  function clearPreview() {
    setPreview(null);
    setError(null);
  }

  async function review() {
    if (!canPreview || pending) return;
    setPending(true);
    clearPreview();
    try {
      const result = await post<ReferenceEmotionPreview>(endpoint + '/preview', selection);
      setPreview({ ...result, key });
    } catch (err) {
      setError({ key, text: err instanceof ApiError ? tm(err.msg) : String(err) });
    } finally {
      setPending(false);
    }
  }

  return <form className="single-form reference-emotions" hidden={!shown} onSubmit={event => {
    event.preventDefault();
    if (!canQueue || !currentPreview) return;
    enqueue(selection, currentPreview.revision, message => {
      setPreview(current => current === currentPreview ? null : current);
      setError({ key, text: message });
    });
  }}>
    <fieldset>
      <legend>{t('reference.emotions_expressions')}</legend>
      {expressions.isPending ? <p className="faint small" role="status">{t('reference.emotions_loading')}</p>
        : expressions.error ? <p role="alert" className="warn-text">{expressions.error instanceof ApiError ? tm(expressions.error.msg) : String(expressions.error)}</p>
          : !expressionChoices.length ? <p className="faint small">{t('reference.emotions_none_available')}</p>
            : <div className="reference-emotion-options">
              {byGroup(expressionChoices).map(group => <div key={group.group} className="reference-emotion-group">
                {group.group && <strong>{group.group}</strong>}
                <div className="reference-emotion-choices">
                  {group.items.map(item => <label key={item.id}>
                    <input type="checkbox" checked={chosen.includes(item.id)} onChange={event => {
                      const checked = event.target.checked;
                      setChosen(current => checked ? [...current, item.id] : current.filter(value => value !== item.id));
                      clearPreview();
                    }} />{item.name}
                  </label>)}
                </div>
              </div>)}
            </div>}
    </fieldset>
    <fieldset>
      <legend>{t('reference.emotions_composition')}</legend>
      <div className="reference-emotion-choices">
        {(['none', 'linked', 'library'] as const).map(value => <label key={value}>
          <input type="radio" name={id + '-composition'} value={value} checked={mode === value} onChange={() => {
            setMode(value);
            clearPreview();
          }} />{t('reference.emotions_' + value)}
        </label>)}
      </div>
      {mode === 'library' && <label className="single-field reference-emotion-composition">
        <span>{t('reference.emotions_choose_composition')}</span>
        <select value={selectedComposition?.id ?? ''} disabled={!compositionChoices.length || compositions.isError} onChange={event => {
          setCompositionId(event.target.value);
          clearPreview();
        }}>
          <option value="">{t(compositions.isPending ? 'reference.emotions_compositions_loading'
            : compositionChoices.length || compositions.isError ? 'materials.choose' : 'reference.emotions_compositions_unavailable')}</option>
          {compositionChoices.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>}
      {mode === 'library' && compositions.error && <p className="warn-text" role="alert">
        {compositions.error instanceof ApiError ? tm(compositions.error.msg) : String(compositions.error)}
      </p>}
    </fieldset>
    <section className="reference-emotion-review" aria-label={t('reference.emotions_preview')}>
      <button type="button" disabled={!canPreview || pending || busy} onClick={() => void review()}>{t('reference.emotions_preview_action')}</button>
      {pending && <p role="status" className="faint small">{t('reference.emotions_preview_pending')}</p>}
      {error?.key === key && <p role="alert" className="warn-text">{error.text}</p>}
      {!!currentPreview?.rows.length && <div className="reference-emotion-preview-list">
        {currentPreview.rows.map(row => <details key={row.expression_id}>
          <summary><strong>{row.expression_name}</strong>
            {row.composition_name && <span className="faint">{row.composition_name}</span>}
            {row.composition_omitted && <span className="faint">{t('reference.emotions_composition_omitted')}</span>}
          </summary>
          <dl>
            <div><dt>{t('single.positive')}</dt><dd>{row.positive}</dd></div>
            <div><dt>{t('single.negative')}</dt><dd>{row.negative || '—'}</dd></div>
          </dl>
        </details>)}
      </div>}
      <p role="status" className="muted">{t('reference.emotions_total', { count: currentPreview?.rows.length ?? selection.expression_ids.length })}</p>
    </section>
    {readiness}
    <div className="row reference-actions">
      <button type="submit" className="primary" disabled={!canQueue}>
        {t('reference.emotions_queue')}
      </button>
      <button type="button" className="ghost" onClick={openQueue}>{t('image_menu.queue')}</button>
    </div>
  </form>;
}
