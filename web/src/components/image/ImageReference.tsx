import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ApiError, get, notifyUnauthorized, post, q } from '../../api';
import type { ReferenceAsset, ReferenceSnapshot, ReferenceStatus, SingleRun, SingleRuns } from '../../imageTypes';
import { msgText, t, tm } from '../../i18n';
import { settingsFromPreset } from '../../lib/presetSettings';
import { takeReferenceHandoff } from '../../lib/referenceHandoff';
import { editablePrompt } from '../../lib/singlePromptSources';
import type { ImageView } from '../../types';
import { useUnsaved } from '../Unsaved';
import { Loading } from '../ui';
import GalleryDetailFrame from './GalleryDetailFrame';
import GenSettings, { FAMILY_DEFAULTS, modelsForFamily, useCatalog, type GenerationSettings } from './GenSettings';
import SingleResultDetails from './SingleResultDetails';
import { resultSettings } from './singleResult';
import './ImageSingle.css';
import './ImageReference.css';

type Preset = { id: string; name: string; service: string; family: string; settings: GenerationSettings };
type Draft = {
  positive: string;
  negative: string;
  settings: GenerationSettings;
  preset: string;
  reference: ReferenceAsset | null;
  guidance: string;
};
const initialDraft = (): Draft => ({
  positive: '', negative: '', settings: { ...FAMILY_DEFAULTS.anima, family: 'anima', seed: -1 },
  preset: '', reference: null, guidance: '4.5',
});
const working = (run: SingleRun | undefined) => run && ['queued', 'running', 'cancelling'].includes(run.status);
const failed = (run: SingleRun) => ['failed', 'cancelled', 'interrupted'].includes(run.status);
const usedReference = (run: SingleRun): ReferenceSnapshot | undefined => run.reference ?? run.actual?.reference;
const errorText = (error: unknown) => error instanceof ApiError ? tm(error.msg) : String(error);
const filename = (run: SingleRun) => run.path?.split('/').pop() || run.id;
const draftKey = (workId: string) => 'atelierx-reference-draft-' + workId;

function loadDraft(workId: string): Draft {
  try {
    const saved = JSON.parse(localStorage.getItem(draftKey(workId)) || 'null') as Draft | null;
    return saved ? { ...initialDraft(), ...saved, settings: { ...saved.settings, family: 'anima' } } : initialDraft();
  } catch {
    return initialDraft();
  }
}

function fileData(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result) : reject(new Error(t('reference.read_failed')));
    reader.onerror = () => reject(new Error(t('reference.read_failed')));
    reader.readAsDataURL(file);
  });
}

export default function ImageReference({ workId, openView, openSettings, active = true }: {
  workId: string;
  openView: (view: ImageView) => void;
  openSettings?: (section?: 'image' | 'install') => void;
  active?: boolean;
}) {
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const assetRequest = useRef(0);
  const endpoint = '/api/works/' + q(workId) + '/image/reference';
  const [draft, setDraft] = useState(() => loadDraft(workId));
  const [storageFailed, setStorageFailed] = useState(false);
  const [error, setError] = useState('');
  const [pendingAsset, setPendingAsset] = useState(false);
  const [pendingJob, setPendingJob] = useState('');
  const [selectedRunId, setSelectedRunId] = useState('');
  const [previewOpen, setPreviewOpen] = useState(false);
  const [includeReference, setIncludeReference] = useState(false);
  const [exporting, setExporting] = useState(false);
  const catalogQuery = useCatalog();
  const catalog = catalogQuery.data;
  const status = useQuery<ReferenceStatus>({
    queryKey: ['image-reference-status'],
    queryFn: () => get('/api/image/reference/status'),
    enabled: active,
    staleTime: 0,
  });
  const presets = useQuery<Preset[]>({
    queryKey: ['image-presets'],
    queryFn: () => get('/api/image/presets'),
  });
  const runs = useQuery<SingleRuns>({
    queryKey: ['image-reference-runs', workId],
    queryFn: () => get(endpoint + '/runs'),
    enabled: active,
    refetchInterval: 1500,
  });
  const history = runs.data?.runs ?? [];
  const run = history.find(item => item.id === selectedRunId) ?? history[0];
  const busy = !!pendingJob || history.some(working);
  const guidance = Number(draft.guidance);
  const validGuidance = draft.guidance !== '' && Number.isFinite(guidance) && guidance >= 0 && guidance <= 20;
  const installed = !!(status.data?.ready && catalog?.connected);
  const animaModels = catalog?.connected ? modelsForFamily(catalog, 'anima') : [];
  const ready = installed && animaModels.includes(draft.settings.model ?? '');
  const presetChoices = (presets.data ?? []).filter(preset => preset.service === 'comfyui' && preset.family === 'anima');

  function update(patch: Partial<Draft>) {
    setDraft(current => ({ ...current, ...patch }));
  }

  useEffect(() => {
    try {
      localStorage.setItem(draftKey(workId), JSON.stringify(draft));
      setStorageFailed(false);
    } catch {
      setStorageFailed(true);
    }
  }, [workId, draft]);
  useUnsaved('reference-draft', storageFailed || pendingAsset);

  useEffect(() => {
    if (!catalog?.connected) return;
    const models = modelsForFamily(catalog, 'anima');
    setDraft(current => {
      if (current.settings.model) return current;
      const model = models.find(name => name.split(/[\\/]/).at(-1) === 'anima-base-v1.0.safetensors')
        ?? (models.includes(catalog.defaults.model ?? '') ? catalog.defaults.model : models[0]);
      if (!model) return current;
      return { ...current, settings: { ...catalog.defaults, ...current.settings, model, family: 'anima' } };
    });
  }, [catalog]);

  const addAsset = useCallback(async (source: File | string) => {
    const selection = ++assetRequest.current;
    setPendingAsset(true);
    setError('');
    try {
      if (typeof source !== 'string' && source.size > 32 * 1024 * 1024) throw new Error(t('server.reference.invalid_image'));
      const body = typeof source === 'string' ? { gallery_path: source } : { data_url: await fileData(source), filename: source.name };
      const reference = await post<ReferenceAsset>(endpoint + '/assets', body);
      if (selection === assetRequest.current) setDraft(current => ({ ...current, reference }));
    } catch (err) {
      if (selection === assetRequest.current) setError(errorText(err));
    } finally {
      if (selection === assetRequest.current) setPendingAsset(false);
    }
  }, [endpoint]);

  useEffect(() => {
    if (!active) return;
    const galleryPath = takeReferenceHandoff(workId);
    if (galleryPath) void addAsset(galleryPath);
  }, [active, workId, addAsset]);

  function choosePreset(presetId: string) {
    const preset = presetChoices.find(item => item.id === presetId);
    setDraft(current => ({
      ...current,
      preset: preset?.id ?? '',
      settings: preset ? settingsFromPreset(current.settings, preset.settings, 'anima', FAMILY_DEFAULTS) : current.settings,
    }));
  }

  async function runAction(action: string, submit: () => Promise<{ job_id: string } | void>) {
    setPendingJob(action);
    setError('');
    try {
      const result = await submit();
      if (result) {
        setSelectedRunId(result.job_id);
        setIncludeReference(false);
        setPreviewOpen(false);
      }
      await runs.refetch();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPendingJob('');
    }
  }

  function enqueue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready || !draft.reference || pendingAsset || !validGuidance || !draft.positive.trim()) return;
    const body = {
      service: 'comfyui', positive: draft.positive, negative: draft.negative,
      preset_id: draft.preset || undefined, settings: draft.settings,
      reference: { id: draft.reference.id, guidance },
    };
    void runAction('generate', () => post<{ job_id: string }>(endpoint + '/queue', body));
  }

  function restore(selected: SingleRun) {
    const reference = usedReference(selected);
    if (!reference || !selected.actual) return;
    update({
      positive: editablePrompt(selected.actual.positive),
      negative: editablePrompt(selected.actual.negative),
      preset: '',
      settings: { ...resultSettings(selected), family: 'anima' },
      reference,
      guidance: String(reference.guidance),
    });
  }

  async function download(path: string) {
    setExporting(true);
    setError('');
    try {
      const response = await fetch(endpoint + '/export?path=' + q(path) + '&include_reference=' + includeReference, { credentials: 'same-origin' });
      if (!response.ok) {
        if (response.status === 401) notifyUnauthorized();
        const data = await response.json().catch(() => null) as { error?: ApiError['msg'] } | null;
        throw data?.error ? new ApiError(response.status, data.error) : new Error(t('reference.export_failed'));
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      const basename = path.split('/').pop()?.replace(/\.png$/i, '') || 'reference';
      link.download = basename + '-workflow.zip';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setExporting(false);
    }
  }

  const resultReference = run ? usedReference(run) : undefined;
  const resultDetails = run?.status === 'done' && <>
    {resultReference && <dl className="single-result-summary reference-record">
      <div><dt>{t('reference.image')}</dt><dd>{resultReference.name}</dd></div>
      <div><dt>{t('reference.guidance')}</dt><dd>{resultReference.guidance}</dd></div>
      <div><dt>SHA-256</dt><dd className="mono">{resultReference.sha256}</dd></div>
    </dl>}
    <SingleResultDetails
      run={run}
      current={{ service: 'comfyui', positive: draft.positive, negative: draft.negative, settings: draft.settings }}
      busy={busy || !resultReference || !run.path}
      handoffPending={false}
      restore={() => restore(run)}
      regenerate={newSeed => {
        if (!run.path) return;
        void runAction('regenerate', () => post<{ job_id: string }>(endpoint + '/regenerate', { path: run.path, same_seed: !newSeed }));
      }}
    />
    {run.path && <div className="single-result-group col">
      <h4>{t('reference.export')}</h4>
      <label className="row"><input type="checkbox" checked={includeReference} onChange={event => setIncludeReference(event.target.checked)} />
        {t('reference.include_original')}
      </label>
      <div><button type="button" disabled={exporting} onClick={() => void download(run.path!)}>{t('gallery.download_zip')}</button></div>
    </div>}
  </>;

  return <section className="single-image generation-page reference-image" aria-label={t('image_menu.reference')}>
    <div className="generation-content">
      <header className="single-heading">
        <div>
          <h2>{t('reference.title')} <span className="moss-beta">BETA</span></h2>
          <p className="faint">{t('reference.about')}</p>
        </div>
      </header>
      <div className="generation-service-bar">
        <div className="generation-service-tabs" role="group" aria-label={t('gen.service')}>
          <button type="button" className="on" aria-pressed="true">ComfyUI</button>
          <button type="button" disabled aria-pressed="false">NovelAI <small>{t('reference.coming')}</small></button>
        </div>
      </div>
      {status.isPending && <Loading />}
      {(!installed && !status.isPending) && <div className="single-review reference-status" role="status">
        <div>
          <strong>{t('reference.not_ready')}</strong>
          <div>{status.error ? errorText(status.error) : [
            !catalog?.connected && t('gen.not_connected'),
            !status.data?.node_ready && t('reference.node_missing'),
            !status.data?.weights_ready && t('reference.weights_missing'),
          ].filter(Boolean).join(' · ')}</div>
        </div>
        <div className="row">
          {openSettings && <button type="button" onClick={() => openSettings(catalog?.connected ? 'install' : 'image')}>{t(catalog?.connected ? 'reference.open_install' : 'gen.open_settings')}</button>}
          <button type="button" disabled={status.isFetching || catalogQuery.isFetching} onClick={() => { void status.refetch(); void catalogQuery.refetch(); }}>{t('reference.recheck')}</button>
        </div>
      </div>}
      {installed && !ready && <p className="warn-text" role="status">{t('reference.choose_anima_model')}</p>}
      {storageFailed && <p className="warn-text" role="alert">{t('reference.storage_failed')}</p>}
      {error && <p className="warn-text" role="alert">{error}</p>}
      <div className="single-layout">
        <aside className="single-form single-settings">
          <label className="single-field">
            <span>{t('single.preset')}</span>
            <select value={draft.preset} onChange={event => choosePreset(event.target.value)}>
              <option value="">{t('gen.default')}</option>
              {presetChoices.map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          </label>
          <GenSettings value={draft.settings} onChange={settings => update({ settings })} onlyFamily="anima" />
        </aside>
        <div className="single-workspace">
          <form className="single-form single-prompts" onSubmit={enqueue}>
            <div className="reference-card">
              {draft.reference && <img src={draft.reference.url} alt={draft.reference.name} />}
              <div className="col">
                <h3>{t('reference.image')}</h3>
                {draft.reference ? <strong>{draft.reference.name}</strong> : <span className="faint">{t('reference.choose_hint')}</span>}
                <div className="row">
                  <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden
                    onChange={event => {
                      const file = event.currentTarget.files?.[0];
                      event.currentTarget.value = '';
                      if (file) void addAsset(file);
                    }} />
                  <button type="button" disabled={pendingAsset} onClick={() => fileInput.current?.click()}>
                    {t(draft.reference ? 'reference.replace_file' : 'reference.choose_file')}
                  </button>
                  <button type="button" disabled={pendingAsset} onClick={() => openView('gallery')} title={t('reference.gallery_hint')}>{t('reference.choose_gallery')}</button>
                  {draft.reference && <button type="button" className="ghost" disabled={pendingAsset} onClick={() => update({ reference: null })}>
                    {t('reference.remove')}
                  </button>}
                </div>
                {pendingAsset && <span role="status" className="faint">{t('reference.importing')}</span>}
              </div>
            </div>
            <label className="single-field" htmlFor={id + '-scene'}>
              <span>{t('reference.scene')}</span>
              <textarea id={id + '-scene'} rows={5} value={draft.positive} placeholder={t('reference.scene_hint')} onChange={event => update({ positive: event.target.value })} />
            </label>
            <label className="single-field" htmlFor={id + '-negative'}>
              <span>{t('single.negative')}</span>
              <textarea id={id + '-negative'} rows={3} value={draft.negative} onChange={event => update({ negative: event.target.value })} />
            </label>
            <details className="single-details">
              <summary>{t('reference.details')}</summary>
              <label className="row reference-guidance">
                <span>{t('reference.guidance')}</span>
                <input type="number" min={0} max={20} step="any" value={draft.guidance} onChange={event => update({ guidance: event.target.value })}
                  aria-describedby={id + '-guidance-hint'} />
              </label>
              <p id={id + '-guidance-hint'} className="faint small">{t('reference.guidance_hint')}</p>
            </details>
            <div className="row reference-actions">
              <button type="submit" className="primary" disabled={busy || !ready || !draft.reference || pendingAsset || !validGuidance || !draft.positive.trim()}>{t('single.run')}</button>
              <button type="button" className="ghost" onClick={() => openView('queue')}>{t('image_menu.queue')}</button>
            </div>
          </form>
          <section className="single-result">
            <div className="single-result-head">
              <h3>{t('single.result')}</h3>
              <span role="status">{t('single.state.' + (run?.status ?? 'idle'))}</span>
            </div>
            {runs.error && <p className="warn-text" role="alert">{errorText(runs.error)}</p>}
            {run?.error && <p className="warn-text" role="alert">{msgText(run.error)}</p>}
            {run?.image_url ? <button type="button" className="single-canvas" aria-label={t('single.open_preview')} onClick={() => setPreviewOpen(true)}>
              <img src={run.image_url} alt={t('single.result')} />
            </button> : <p className="faint">{t('reference.result_hint')}</p>}
            {run && working(run) && <button type="button" disabled={!!pendingJob || run.status === 'cancelling'}
              onClick={() => void runAction('cancel', async () => { await post('/api/image/jobs/' + q(run.id) + '/cancel'); })}>{t('common.cancel')}</button>}
            {run && failed(run) && <button type="button" disabled={busy || !ready}
              onClick={() => void runAction('retry', async () => {
                const result = await post<{ job_id: string }>('/api/image/jobs/' + q(run.id) + '/retry');
                await post('/api/image/queue/resume');
                return result;
              })}>{t('single.retry')}</button>}
            {resultDetails}
            {run?.status === 'done' && <div className="single-result-links"><button type="button" className="ghost" onClick={() => openView('gallery')}>{t('image_menu.gallery')}</button></div>}
            {!!history.length && <div className="single-history">
              <h4>{t('single.history')}</h4>
              <div className="single-history-list">
                {history.slice(0, 12).map(item => <button key={item.id} type="button" className={'single-history-row' + (item.id === run?.id ? ' is-selected' : '')}
                  aria-pressed={item.id === run?.id} onClick={() => {
                    setSelectedRunId(item.id); setIncludeReference(false); setPreviewOpen(false);
                  }}>
                  {item.image_url ? <img className="single-history-thumb" src={item.image_url} alt="" loading="lazy" /> : <span className="single-history-thumb" />}
                  <span className="single-history-content">
                    <span className="single-history-name" title={filename(item)}>{filename(item)}</span>
                    <span className="faint small">{t('single.state.' + item.status)}</span>
                  </span>
                </button>)}
              </div>
            </div>}
          </section>
        </div>
      </div>
      {previewOpen && run?.image_url && <GalleryDetailFrame imageUrl={run.image_url} label={filename(run)} close={() => setPreviewOpen(false)}>
        <div className="row"><strong className="grow">{filename(run)}</strong>
          <button type="button" className="ghost" aria-label={t('common.close')} onClick={() => setPreviewOpen(false)}>×</button>
        </div>
      </GalleryDetailFrame>}
    </div>
  </section>;
}
