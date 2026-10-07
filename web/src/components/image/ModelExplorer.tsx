import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { ApiError, get, post, put } from '../../api';
import { t, tm } from '../../i18n';
import Explorer, { type Facet } from '../explorer/Explorer';
import { useToast } from '../Toasts';

// Image menu → Models (#161): the files the image server offers, by kind, family and source, on the shared explorer
// layout. A model's family is set here (it used to be a table in Settings → Image), and its Civitai information is
// looked up by hash on request.
type Info = {
  source?: string;
  model_id?: number;
  version_id?: number;
  model_name?: string;
  version_name?: string;
  base_model?: string;
  trained_words?: string[];
  author?: string;
  nsfw?: boolean;
  license?: Record<string, unknown>;
  url?: string | null;
  from?: 'cm-info' | 'lookup';
  not_found?: boolean;
};
export type ModelItem = {
  kind: 'checkpoint' | 'diffusion_model' | 'lora' | 'text_encoder' | 'vae' | 'upscale_model';
  name: string;
  file: string;
  path: string | null;
  size: number | null;
  family: string | null;
  family_by: string | null;
  preview: string | null;
  info: Info | null;
  source: 'civitai' | 'trained' | 'unknown';
  hashed?: boolean;
};
// The family kinds ModelProfiles uses when a family is set by hand.
const FAMILY_KIND: Record<string, string> = {
  checkpoint: 'checkpoints',
  diffusion_model: 'diffusion_models',
  lora: 'loras',
  text_encoder: 'text_encoders',
  vae: 'vaes',
};
const size = (n: number | null) => (!n ? '' : n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)} GB` : `${Math.round(n / 1024 ** 2)} MB`);
const previewUrl = (m: ModelItem) => `/api/image/models/preview?kind=${m.kind}&name=${encodeURIComponent(m.name)}`;
const idOf = (m: ModelItem) => `${m.kind}:${m.name}`;

export default function ModelExplorer() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const list = useQuery<{ items: ModelItem[] }>({ queryKey: ['image-models'], queryFn: () => get('/api/image/models/list'), retry: false });
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const items = list.data?.items ?? [];
  const chosen = items.find((m) => idOf(m) === selected) ?? null;
  const facets = useMemo<Facet<ModelItem>[]>(
    () => [
      { id: 'kind', label: t('models.facet.kind'), values: (m) => [m.kind], name: (v) => t(`models.kind.${v}`) },
      { id: 'family', label: t('models.facet.family'), values: (m) => [m.family ?? 'unknown'], name: (v) => t(`models.family.${v}`) },
      { id: 'source', label: t('models.facet.source'), values: (m) => [m.source], name: (v) => t(`models.source.${v}`) },
      { id: 'base', label: t('models.facet.base'), values: (m) => (m.info?.base_model ? [m.info.base_model] : []) },
    ],
    [],
  );

  async function lookup(m: ModelItem) {
    setBusy(idOf(m));
    try {
      const found = await post<ModelItem>('/api/image/models/lookup', { kind: m.kind, name: m.name });
      qc.setQueryData<{ items: ModelItem[] }>(['image-models'], (old) => old && { items: old.items.map((x) => (idOf(x) === idOf(m) ? found : x)) });
      qc.invalidateQueries({ queryKey: ['image-catalog'] });
      toast({ text: found.info?.not_found ? t('models.lookup_none') : t('models.lookup_done', { name: found.info?.model_name ?? m.file }) });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function setFamily(m: ModelItem, family: string) {
    try {
      await put('/api/image/models/family', { kind: FAMILY_KIND[m.kind], name: m.name.replace(/^checkpoint::/, ''), family: family || null });
      await qc.invalidateQueries({ queryKey: ['image-models'] });
      qc.invalidateQueries({ queryKey: ['image-catalog'] });
    } catch (err) {
      fail(err);
    }
  }

  if (list.isError) return <div className="pad warn-text">{list.error instanceof ApiError ? tm(list.error.msg) : t('models.not_connected')}</div>;

  const card = (m: ModelItem) => (
    <>
      <div className="preset-thumb">
        {m.preview ? <img src={previewUrl(m)} alt="" loading="lazy" /> : <span className="faint small">{t(`models.kind.${m.kind}`)}</span>}
      </div>
      <div className="col" style={{ gap: 2, padding: '6px 8px' }}>
        <strong className="ellipsis" title={m.name}>
          {m.info?.model_name || m.file}
        </strong>
        <span className="faint small mono ellipsis" title={m.file}>
          {m.file}
        </span>
        <div className="row" style={{ gap: 4, flexWrap: 'wrap' }}>
          <span className="chip small">{t(`models.kind.${m.kind}`)}</span>
          {m.family && <span className="chip small">{t(`models.family.${m.family}`)}</span>}
          <span className={`chip small${m.source === 'unknown' ? ' faint' : ''}`}>{t(`models.source.${m.source}`)}</span>
          {!m.path && <span className="chip small warn">{t('models.no_file')}</span>}
        </div>
      </div>
    </>
  );

  const detail = !chosen ? (
    <div className="col pad" style={{ gap: 8 }}>
      <p className="faint">{t('models.about')}</p>
    </div>
  ) : (
    <div className="col pad" style={{ gap: 8 }}>
      <div className="row">
        <strong className="grow" style={{ wordBreak: 'break-all' }}>
          {chosen.info?.model_name || chosen.file}
        </strong>
        <button className="ghost small" onClick={() => setSelected(null)}>
          ×
        </button>
      </div>
      {chosen.preview && <img className="preset-detail-img" src={previewUrl(chosen)} alt="" />}
      <table className="gen-table small">
        <tbody>
          <tr>
            <th>{t('models.file')}</th>
            <td className="mono">{chosen.name}</td>
          </tr>
          <tr>
            <th>{t('models.where')}</th>
            <td className="mono">{chosen.path ?? t('models.no_file')}</td>
          </tr>
          {chosen.size !== null && (
            <tr>
              <th>{t('models.size')}</th>
              <td>{size(chosen.size)}</td>
            </tr>
          )}
          <tr>
            <th>{t('models.facet.source')}</th>
            <td>
              {t(`models.source.${chosen.source}`)}
              {chosen.info?.from && <span className="faint"> · {t(`models.from.${chosen.info.from}`)}</span>}
            </td>
          </tr>
          {chosen.info?.model_name && (
            <tr>
              <th>Civitai</th>
              <td>
                {chosen.info.model_name} {chosen.info.version_name}
                {chosen.info.author ? ` · ${chosen.info.author}` : ''}
                {chosen.info.url && (
                  <div className="mono faint" style={{ wordBreak: 'break-all' }}>
                    {chosen.info.url}
                  </div>
                )}
              </td>
            </tr>
          )}
          {chosen.info?.base_model && (
            <tr>
              <th>{t('models.facet.base')}</th>
              <td>{chosen.info.base_model}</td>
            </tr>
          )}
          {(chosen.info?.trained_words ?? []).length > 0 && (
            <tr>
              <th>{t('models.trained_words')}</th>
              <td className="mono" style={{ cursor: 'copy' }} title={t('gallery.click_copy')} onClick={() => navigator.clipboard.writeText(chosen.info!.trained_words!.join(', ')).then(() => toast({ text: t('gallery.copied') }))}>
                {chosen.info!.trained_words!.join(', ')}
              </td>
            </tr>
          )}
          {chosen.info?.license && Object.keys(chosen.info.license).length > 0 && (
            <tr>
              <th>{t('models.license')}</th>
              <td className="small">
                {Object.entries(chosen.info.license)
                  .map(([k, v]) => `${t(`models.license_key.${k}`)}: ${Array.isArray(v) ? v.join(', ') || '—' : v ? t('models.yes') : t('models.no')}`)
                  .join(' · ')}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {FAMILY_KIND[chosen.kind] && (
        <label className="row" style={{ gap: 6 }}>
          <span className="muted">{t('models.facet.family')}</span>
          <select value={chosen.family_by === 'manual' ? (chosen.family ?? '') : ''} onChange={(e) => setFamily(chosen, e.target.value)}>
            <option value="">{t('models.family_auto')}</option>
            <option value="anima">Anima</option>
            <option value="sdxl">SDXL·IL</option>
          </select>
          <span className="faint small">{chosen.family_by ? t(`models.family_by.${chosen.family_by}`) : ''}</span>
        </label>
      )}
      <div className="row">
        <button disabled={!chosen.path || busy === idOf(chosen)} onClick={() => lookup(chosen)} title={t('models.lookup_hint')}>
          {busy === idOf(chosen) ? t('models.looking_up') : chosen.info?.from === 'lookup' ? t('models.lookup_again') : t('models.lookup')}
        </button>
      </div>
      {chosen.info?.not_found && <span className="faint small">{t('models.lookup_none')}</span>}
    </div>
  );

  return (
    <Explorer
      items={items}
      idOf={idOf}
      search={(m) => [m.name, m.info?.model_name, m.info?.base_model, ...(m.info?.trained_words ?? [])].filter(Boolean).join(' ')}
      facets={facets}
      card={card}
      detail={detail}
      compare={(chosenItems) => (
        <div className="preset-compare" style={{ gridTemplateColumns: `repeat(${chosenItems.length}, minmax(0, 1fr))` }}>
          {chosenItems.map((m) => (
            <div key={idOf(m)} className="col" style={{ gap: 6 }}>
              <div className="preset-thumb large">{m.preview ? <img src={previewUrl(m)} alt="" /> : <span className="faint">{t(`models.kind.${m.kind}`)}</span>}</div>
              <strong>{m.info?.model_name || m.file}</strong>
              <dl className="kv small">
                <div>
                  <dt>{t('models.facet.family')}</dt>
                  <dd>{m.family ? t(`models.family.${m.family}`) : '—'}</dd>
                </div>
                <div>
                  <dt>{t('models.facet.base')}</dt>
                  <dd>{m.info?.base_model || '—'}</dd>
                </div>
                <div>
                  <dt>{t('models.trained_words')}</dt>
                  <dd className="mono">{(m.info?.trained_words ?? []).join(', ') || '—'}</dd>
                </div>
                <div>
                  <dt>{t('models.size')}</dt>
                  <dd>{size(m.size) || '—'}</dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}
      selected={selected}
      onSelect={setSelected}
      empty={list.isLoading ? t('models.loading') : t('models.empty')}
      toolbar={
        <button onClick={() => qc.invalidateQueries({ queryKey: ['image-models'] })} title={t('models.refresh_hint')}>
          {t('models.refresh')}
        </button>
      }
    />
  );
}
