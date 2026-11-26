import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ApiError, get, notifyUnauthorized, post, q } from '../../api';
import type { MossReferenceStatus, ReferenceAsset, ReferenceSnapshot, ReferenceStatus, SingleRun, SingleRuns } from '../../imageTypes';
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
type ReferenceFamily = 'anima' | 'moss';
type FamilyDraft = { settings: GenerationSettings; preset: string };
type Draft = {
  positive: string;
  negative: string;
  family: ReferenceFamily;
  parameters: Record<ReferenceFamily, FamilyDraft>;
  reference: ReferenceAsset | null;
  guidance: string;
};
const mossDefaults: GenerationSettings = {
  ...FAMILY_DEFAULTS.moss, family: 'moss', steps: 35, cfg: 3.5, scheduler: 'sgm_uniform', seed: -1, shift: undefined, moss_slg: false, loras: [],
};
const initialDraft = (): Draft => ({
  positive: '', negative: '', family: 'anima', reference: null, guidance: '4.5',
  parameters: {
    anima: { settings: { ...FAMILY_DEFAULTS.anima, family: 'anima', seed: -1 }, preset: '' },
    moss: { settings: mossDefaults, preset: '' },
  },
});
const working = (run: SingleRun | undefined) => run && ['queued', 'running', 'cancelling'].includes(run.status);
const failed = (run: SingleRun) => ['failed', 'cancelled', 'interrupted'].includes(run.status);
const usedReference = (run: SingleRun): ReferenceSnapshot | undefined => run.reference ?? run.actual?.reference;
const errorText = (error: unknown) => error instanceof ApiError ? tm(error.msg) : String(error);
const filename = (run: SingleRun) => run.path?.split('/').pop() || run.id;
const draftKey = (workId: string) => 'atelierx-reference-draft-' + workId;

function loadDraft(workId: string): Draft {
  const initial = initialDraft();
  try {
    const saved = JSON.parse(localStorage.getItem(draftKey(workId)) || 'null') as (Partial<Draft> & Partial<FamilyDraft>) | null;
    if (!saved) return initial;
    return {
      positive: saved.positive ?? initial.positive,
      negative: saved.negative ?? initial.negative,
      reference: saved.reference ?? initial.reference,
      guidance: saved.guidance ?? initial.guidance,
      family: saved.family === 'moss' ? 'moss' : 'anima',
      parameters: {
        anima: {
          settings: { ...initial.parameters.anima.settings, ...(saved.parameters?.anima?.settings ?? saved.settings), family: 'anima' },
          preset: saved.parameters?.anima?.preset ?? saved.preset ?? '',
        },
        moss: {
          settings: { ...mossDefaults, ...saved.parameters?.moss?.settings },
          preset: saved.parameters?.moss?.preset ?? '',
        },
      },
    };
  } catch {
    return initial;
  }
}

function mossSettings(value: GenerationSettings, status?: MossReferenceStatus): GenerationSettings {
  return {
    ...mossDefaults, ...value,
    family: 'moss', clip_type: 'moss_image', moss_slg: false, loras: [],
    model: value.model || status?.models[0],
    text_encoder: value.text_encoder || status?.text_encoders[0],
    vae: value.vae || status?.vaes[0],
  };
}

function supportsMossPreset(value: GenerationSettings, status?: MossReferenceStatus) {
  return !!status
    && !value.moss_slg && !value.upscale && !value.detailer && !value.clip_skip
    && (!value.clip_type || value.clip_type === 'moss_image')
    && !value.loras?.some(lora => lora.enabled !== false)
    && (!value.model || status.models.includes(value.model))
    && (!value.text_encoder || status.text_encoders.includes(value.text_encoder))
    && (!value.vae || status.vaes.includes(value.vae));
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
  const [preview, setPreview] = useState<'reference' | 'result' | null>(null);
  const [includeReference, setIncludeReference] = useState(false);
  const [exporting, setExporting] = useState(false);
  const catalogQuery = useCatalog();
  const catalog = catalogQuery.data;
  const animaStatus = useQuery<ReferenceStatus>({
    queryKey: ['image-reference-status'],
    queryFn: () => get('/api/image/reference/status'),
    enabled: active,
    staleTime: 0,
  });
  const mossStatus = useQuery<MossReferenceStatus>({
    queryKey: ['image-reference-status', 'moss'],
    queryFn: () => get('/api/image/reference/status?family=moss'),
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
  const { family } = draft;
  const { preset, settings: rawSettings } = draft.parameters[family];
  const moss = family === 'moss';
  const status = moss ? mossStatus : animaStatus;
  const mossInfo = mossStatus.data;
  const settings = moss ? mossSettings(rawSettings, mossInfo) : rawSettings;
  const mossModelChoices: Pick<MossReferenceStatus, 'models' | 'text_encoders' | 'vaes'> =
    mossInfo ?? { models: [], text_encoders: [], vaes: [] };
  const guidance = Number(draft.guidance);
  const validGuidance = moss || (draft.guidance !== '' && Number.isFinite(guidance) && guidance >= 0 && guidance <= 20);
  const installed = !!(status.data?.ready && catalog?.connected);
  const animaModels = catalog?.connected ? modelsForFamily(catalog, 'anima') : [];
  const ready = installed && (moss
    ? mossModelChoices.models.includes(settings.model ?? '')
      && mossModelChoices.text_encoders.includes(settings.text_encoder ?? '')
      && mossModelChoices.vaes.includes(settings.vae ?? '')
    : animaModels.includes(settings.model ?? ''));
  const canGenerate = !busy && ready && !!draft.reference && !pendingAsset && validGuidance && !!draft.positive.trim();
  const presetChoices = (presets.data ?? []).filter(item =>
    item.service === 'comfyui' && item.family === family && (!moss || supportsMossPreset(item.settings, mossInfo)));
  const mossFilesUnverified = moss && (mossInfo?.weights_ready === null || mossInfo?.foundation_ready === null);
  const statusMessages = [
    !catalog?.connected && t('gen.not_connected'),
    ...(moss ? [
      mossInfo?.node_ready === false && t('reference.moss_node_missing'),
      mossInfo?.edit_node_ready === false && t('reference.moss_edit_node_missing'),
      mossInfo?.weights_ready === false && t('reference.moss_weights_missing'),
      mossInfo?.foundation_ready === false && t('reference.moss_foundation_missing'),
      mossInfo?.node_ready && mossInfo.edit_node_ready
        && (!mossInfo.models.length || !mossInfo.text_encoders.length || !mossInfo.vaes.length)
        && t('reference.moss_models_missing'),
    ] : [
      !animaStatus.data?.node_ready && t('reference.node_missing'),
      !animaStatus.data?.weights_ready && t('reference.weights_missing'),
    ]),
  ].filter(Boolean);

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
      const anima = current.parameters.anima;
      if (anima.settings.model) return current;
      const model = models.find(name => name.split(/[\\/]/).at(-1) === 'anima-base-v1.0.safetensors')
        ?? (models.includes(catalog.defaults.model ?? '') ? catalog.defaults.model : models[0]);
      if (!model) return current;
      const settings: GenerationSettings = { ...catalog.defaults, ...anima.settings, model, family: 'anima' };
      return { ...current, parameters: { ...current.parameters, anima: { ...anima, settings } } };
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
    const chosen = presetChoices.find(item => item.id === presetId);
    setDraft(current => ({
      ...current,
      parameters: {
        ...current.parameters,
        [family]: {
          preset: chosen?.id ?? '',
          settings: chosen ? settingsFromPreset(settings, chosen.settings, family, FAMILY_DEFAULTS) : settings,
        },
      },
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
        setPreview(null);
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
    if (!canGenerate || !draft.reference) return;
    const body = {
      service: 'comfyui', positive: draft.positive, negative: draft.negative,
      preset_id: presetChoices.some(item => item.id === preset) ? preset : undefined, settings,
      reference: moss ? { id: draft.reference.id, engine: 'mossref' } : { id: draft.reference.id, guidance },
    };
    void runAction('generate', () => post<{ job_id: string }>(endpoint + '/queue', body));
  }

  function restore(selected: SingleRun) {
    const reference = usedReference(selected);
    if (!reference || !selected.actual) return;
    const family = reference.engine === 'mossref' ? 'moss' : 'anima';
    const actual = selected.actual;
    setDraft(current => ({
      ...current,
      positive: editablePrompt(actual.positive),
      negative: editablePrompt(actual.negative),
      family,
      parameters: {
        ...current.parameters,
        [family]: { settings: { ...resultSettings(selected), family }, preset: '' },
      },
      reference,
      guidance: reference.engine === 'mossref' ? current.guidance : String(reference.guidance),
    }));
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

  const previewImage = preview === 'reference' ? draft.reference
    : preview === 'result' && run?.image_url ? { url: run.image_url, name: filename(run) } : null;
  const resultReference = run ? usedReference(run) : undefined;
  const resultModel = run?.actual?.settings.model;
  const resultIsMoss = resultReference?.engine === 'mossref';
  const retryReady = !!catalog?.connected && (resultIsMoss
    ? !!mossInfo?.ready && (typeof resultModel !== 'string' || mossInfo.models.includes(resultModel))
    : !!animaStatus.data?.ready && (typeof resultModel !== 'string' || animaModels.includes(resultModel)));
  const resultDetails = run?.status === 'done' && <>
    {resultReference && <dl className="single-result-summary reference-record">
      <div><dt>{t('reference.image')}</dt><dd>{resultReference.name}</dd></div>
      <div><dt>{t('gen.family')}</dt><dd>{resultIsMoss ? 'MOSS (MossRef)' : 'Anima'}</dd></div>
      {resultReference.engine !== 'mossref' && <div><dt>{t('reference.guidance')}</dt><dd>{resultReference.guidance}</dd></div>}
      <div><dt>SHA-256</dt><dd className="mono">{resultReference.sha256}</dd></div>
    </dl>}
    <SingleResultDetails
      run={run}
      current={{ service: 'comfyui', positive: draft.positive, negative: draft.negative, settings }}
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
      <div className="row reference-family">
        <span id={id + '-family'} className="muted">{t('gen.family')}</span>
        <div className="seg" role="group" aria-labelledby={id + '-family'}>
          <button type="button" className={!moss ? 'on' : ''} aria-pressed={!moss} onClick={() => update({ family: 'anima' })}>Anima</button>
          <button type="button" className={moss ? 'on' : ''} aria-pressed={moss} onClick={() => update({ family: 'moss' })}>MOSS</button>
        </div>
      </div>
      {status.isPending && <Loading />}
      {(!installed && !status.isPending) && <div className="single-review reference-status" role="status">
        <div>
          <strong>{t('reference.not_ready')}</strong>
          <div>{status.error ? errorText(status.error) : statusMessages.join(' · ')}</div>
        </div>
        <div className="row">
          {moss && <a href="https://github.com/Neon3579/MossRef/tree/v2.0.0#install--quick-start" target="_blank" rel="noreferrer">{t('reference.moss_install')}</a>}
          {openSettings && (!moss || !catalog?.connected) && <button type="button" onClick={() => openSettings(catalog?.connected ? 'install' : 'image')}>{t(catalog?.connected ? 'reference.open_install' : 'gen.open_settings')}</button>}
          <button type="button" disabled={status.isFetching || catalogQuery.isFetching} onClick={() => { void status.refetch(); void catalogQuery.refetch(); }}>{t('reference.recheck')}</button>
        </div>
      </div>}
      {installed && mossFilesUnverified && <p className="warn-text" role="status">{t('reference.moss_files_unverified')}</p>}
      {installed && !ready && <p className="warn-text" role="status">{t(moss ? 'reference.choose_moss_model' : 'reference.choose_anima_model')}</p>}
      {storageFailed && <p className="warn-text" role="alert">{t('reference.storage_failed')}</p>}
      {error && <p className="warn-text" role="alert">{error}</p>}
      <div className="single-layout">
        <aside className="single-form single-settings">
          <label className="single-field">
            <span>{t('single.preset')}</span>
            <select value={presetChoices.some(item => item.id === preset) ? preset : ''} onChange={event => choosePreset(event.target.value)}>
              <option value="">{t('gen.default')}</option>
              {presetChoices.map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          </label>
          <GenSettings value={settings} onChange={settings => setDraft(current => ({
            ...current, parameters: { ...current.parameters, [family]: { ...current.parameters[family], settings } },
          }))} onlyFamily={family} showFamily={false} mossReference={moss ? mossModelChoices : undefined} />
        </aside>
        <div className="single-workspace">
          <form className="single-form single-prompts" onSubmit={enqueue}>
            <div className="reference-card">
              {draft.reference && <button type="button" className="reference-preview" aria-haspopup="dialog"
                aria-label={t('reference.open_preview', { name: draft.reference.name })} onClick={event => {
                  event.currentTarget.focus();
                  setPreview('reference');
                }}>
                <img src={draft.reference.url} alt="" />
              </button>}
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
              <textarea id={id + '-scene'} rows={5} value={draft.positive} placeholder={t(moss ? 'reference.moss_scene_hint' : 'reference.scene_hint')} onChange={event => update({ positive: event.target.value })} />
            </label>
            <label className="single-field" htmlFor={id + '-negative'}>
              <span>{t('single.negative')}</span>
              <textarea id={id + '-negative'} rows={3} value={draft.negative} onChange={event => update({ negative: event.target.value })} />
            </label>
            {!moss && <details className="single-details">
              <summary>{t('reference.details')}</summary>
              <label className="row reference-guidance">
                <span>{t('reference.guidance')}</span>
                <input type="number" min={0} max={20} step="any" value={draft.guidance} onChange={event => update({ guidance: event.target.value })}
                  aria-describedby={id + '-guidance-hint'} />
              </label>
              <p id={id + '-guidance-hint'} className="faint small">{t('reference.guidance_hint')}</p>
            </details>}
            <div className="row reference-actions">
              <button type="submit" className="primary" disabled={!canGenerate}>{t('single.run')}</button>
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
            {run?.image_url ? <button type="button" className="single-canvas" aria-label={t('single.open_preview')} onClick={() => setPreview('result')}>
              <img src={run.image_url} alt={t('single.result')} />
            </button> : <p className="faint">{t('reference.result_hint')}</p>}
            {run && working(run) && <button type="button" disabled={!!pendingJob || run.status === 'cancelling'}
              onClick={() => void runAction('cancel', async () => { await post('/api/image/jobs/' + q(run.id) + '/cancel'); })}>{t('common.cancel')}</button>}
            {run && failed(run) && <button type="button" disabled={busy || !retryReady}
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
                    setSelectedRunId(item.id); setIncludeReference(false); setPreview(null);
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
      {previewImage && <GalleryDetailFrame imageUrl={previewImage.url}
        label={preview === 'reference' ? t('reference.preview_title', { name: previewImage.name }) : previewImage.name}
        close={() => setPreview(null)}>
        <div className="row"><strong className="grow">{previewImage.name}</strong>
          <button type="button" className="ghost" aria-label={t('common.close')} onClick={() => setPreview(null)}>×</button>
        </div>
      </GalleryDetailFrame>}
    </div>
  </section>;
}
