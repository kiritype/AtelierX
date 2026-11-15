import DownloadsSection from './DownloadsSection';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { msgText, t, tm } from '../../i18n';
import type { PresetModelCheck } from '../../imageTypes';
import Dialog from './ContentDialog';
import type { Preset } from './PresetEditor';

const size = (n?: number | null) => n == null ? t('preset_models.unknown_size') : n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : `${(n / 1024 ** 2).toFixed(1)} MB`;
type ModelState = { state: string; missing: number; downloading: number };
const stateLabel = (value?: ModelState) => value ? [t(`preset_models.state.${value.state}`), ...(value.missing ? [t('preset_models.missing_count', { n: value.missing })] : [])].join(' · ') : t('preset_models.state.unknown');
const errorText = (e: unknown) => e instanceof ApiError ? tm(e.msg) : String(e);

// Also embedded as the last step of the default-content dialog, without nesting dialogs.
export function PresetModelsContent({ ids, onChanged }: { ids: string[]; onChanged?: () => void }) {
  const qc = useQueryClient();
  const [token, setToken] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [local, setLocal] = useState<Record<string, string>>({});
  const check = useQuery<PresetModelCheck>({ queryKey: ['preset-model-check', token], enabled: !!token,
    queryFn: () => post('/api/image/presets/resources/status', { token }),
    refetchInterval: q => q.state.data?.items.some(i => ['queued', 'running'].includes(i.status)) ? 2000 : false });
  const items = check.data?.items ?? [];
  const ready = items.filter(i => i.status === 'ready').map(i => i.id).join(',');
  const changed = useRef(onChanged);
  changed.current = onChanged;
  useEffect(() => {
    if (ready) { qc.invalidateQueries({ queryKey: ['image-presets'] }); qc.invalidateQueries({ queryKey: ['image-catalog'] }); changed.current?.(); }
  }, [ready, qc]);
  useEffect(() => {
    if (!check.data) return;
    for (const id of ids) {
      const used = check.data.items.filter(i => i.presets.some(p => p.id === id));
      const state = used.some(i => i.status === 'unknown') ? 'unknown' : used.some(i => ['running', 'queued'].includes(i.status)) ? 'running'
        : used.every(i => i.status === 'ready') ? 'ready' : 'missing';
      qc.setQueryData(['preset-model-state', id], { state, missing: used.filter(i => !['ready', 'unknown', 'queued', 'running'].includes(i.status)).length, downloading: used.filter(i => ['queued', 'running'].includes(i.status)).length });
    }
  }, [check.data, ids, qc]);
  async function run(action: string, body: object) {
    setBusy(true); setError('');
    try {
      const result = await post<PresetModelCheck>(`/api/image/presets/resources/${action}`, body);
      qc.setQueryData(['preset-model-check', result.token], result);
      setToken(result.token);
      if (result.errors?.length) setError(result.errors.map(msgText).join('\n'));
      qc.invalidateQueries({ queryKey: ['model-downloads'] });
      if (action === 'check' || action === 'download') setSelected([]);
    } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
  }
  const chosen = items.filter(i => i.downloadable && selected.includes(i.id));
  return <div className="col" style={{ gap: 12 }}>
    <p className="faint small">{t('preset_models.about')}</p>
    <div className="row"><button disabled={busy || !ids.length} onClick={() => run('check', { ids })}>{t(busy ? 'preset_models.checking' : 'preset_models.check')}</button>
      {check.data && <button disabled={busy} onClick={() => setSelected(items.filter(i => i.downloadable).map(i => i.id))}>{t('preset_models.select_all')}</button>}
    </div>
    {(error || check.error) && <p role="alert" className="error">{error || errorText(check.error)}</p>}
    {check.data && !check.data.connected && <p role="status" className="warn-text">{t('preset_models.offline')}</p>}
    {check.data?.connected && !check.data.local && <p className="warn-text">{t('preset_models.remote')}</p>}
    {check.data && !check.data.has_key && <p className="faint small">{t('preset_models.key_hint')}</p>}
    {check.data && <button onClick={() => setShowKey(!showKey)}>{t('image_settings.civitai_key')}</button>}
    {showKey && <DownloadsSection />}
    {check.data && !items.length && <p>{t('preset_models.none')}</p>}
    <div className="col" style={{ gap: 10, maxHeight: '48vh', overflow: 'auto' }}>
      {items.map(item => <div className="gen-patch col" style={{ gap: 5 }} key={item.id}>
        <label className="row"><input type="checkbox" aria-label={item.name} disabled={busy || !item.downloadable} checked={selected.includes(item.id) && item.downloadable}
          onChange={e => setSelected(old => e.target.checked ? [...old, item.id] : old.filter(id => id !== item.id))} />
          <strong style={{ overflowWrap: 'anywhere' }}>{item.name}</strong><span className="chip small">{t(`preset_models.state.${item.status}`)}</span></label>
        <span className="small faint">{t(`presets.share.kind.${item.kind}`)} · {size(item.size)}{item.version ? ` · ${item.version}` : ''}</span>
        <span className="small">{t('preset_models.used_by', { names: item.presets.map(p => p.name).join(', ') })}</span>
        {item.civitai && <a href={item.civitai} target="_blank" rel="noreferrer">{t('preset_models.source')}</a>}
        {item.license && <details className="small"><summary>{t('preset_models.license')}</summary><pre>{JSON.stringify(item.license, null, 2)}</pre></details>}
        {item.destination && <span className="small faint">{t('preset_models.destination', { path: item.destination })}</span>}
        {(item.error || item.job?.error) && <p className="warn-text small">{msgText(item.job?.error || item.error)}</p>}
        {item.job && ['queued', 'running', 'paused', 'failed'].includes(item.status) && <div className="row small">
          <progress aria-label={t('preset_models.progress')} max={item.job.size || 1} value={item.job.received} />
          <span>{size(item.job.received)} / {size(item.job.size)}</span>
          <button disabled={busy} onClick={async () => { try { await post(`/api/image/models/downloads/${item.job!.id}/${['failed', 'paused'].includes(item.status) ? 'resume' : 'cancel'}`); await check.refetch(); } catch (e) { setError(errorText(e)); } }}>{t(['failed', 'paused'].includes(item.status) ? 'preset_models.resume' : 'common.cancel')}</button>
        </div>}
        {item.status !== 'ready' && item.candidates.length > 0 && <details className="small"><summary>{t('preset_models.connect')}</summary>
          <p>{t('preset_models.connect_hint')}</p><div className="row"><select aria-label={t('preset_models.connect')} value={local[item.id] ?? ''} onChange={e => setLocal({ ...local, [item.id]: e.target.value })}>
            <option value="">{t('preset_models.choose_file')}</option>{item.candidates.map(c => <option key={`${c.kind}:${c.name}`} value={JSON.stringify(c)}>{c.name}</option>)}</select>
            <button disabled={busy || !local[item.id]} onClick={() => run('link', { token, id: item.id, ...JSON.parse(local[item.id]) as { kind: string; name: string } })}>{t('preset_models.connect')}</button></div></details>}
      </div>)}
    </div>
    {check.data && <div className="row"><span className="grow">{t('preset_models.selected', { n: chosen.length, size: size(chosen.reduce((n, i) => n + (i.size ?? 0), 0)) })}</span>
      <button className="primary" disabled={busy || !chosen.length} onClick={() => run('download', { token, selected: chosen.map(i => i.id) })}>{t('preset_models.download')}</button></div>}
    <p className="faint small">{t('preset_models.background')}</p>
  </div>;
}

export default function PresetModelsButton({ ids, disabled, onResolved }: { ids: string[]; disabled?: boolean; onResolved?: (before: Preset[], after: Preset[]) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const baseline = useRef<Preset[]>([]);
  const [error, setError] = useState('');
  const state = useQuery<ModelState>({ queryKey: ['preset-model-state', ids.join(',')], enabled: false });
  async function refresh() {
    try {
      const after = await get<Preset[]>('/api/image/presets');
      qc.setQueryData(['image-presets'], after);
      onResolved?.(baseline.current, after);
      baseline.current = after;
    } catch (e) { setError(errorText(e)); }
  }
  return <><button disabled={disabled || !ids.length} onClick={async () => {
    try { baseline.current = await get<Preset[]>('/api/image/presets'); setOpen(true); } catch (e) { setError(errorText(e)); }
  }}>{t('preset_models.title')}{state.data ? ` · ${stateLabel(state.data)}` : ''}</button>
    {error && <span role="alert">{error}</span>}
    {open && <Dialog title={t('preset_models.title')} closeLabel={t('preset_models.later')} onClose={() => { setOpen(false); void refresh(); }}>
      <PresetModelsContent ids={ids} onChanged={refresh} />
    </Dialog>}
  </>;
}

export function PresetModelBadge({ id }: { id: string }) {
  const state = useQuery<ModelState>({ queryKey: ['preset-model-state', id], enabled: false });
  return <span className="chip small faint">{stateLabel(state.data)}</span>;
}
