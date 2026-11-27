import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { ApiError, get, notifyUnauthorized, post, q } from '../../api';
import type {
  AnimaReferenceEngine, AnimaReferenceStatus, MossReferenceStatus, ReferenceAsset,
  ReferenceAssets, ReferenceEmotionSelection, ReferencePosition, ReferenceSlot, ReferenceSnapshot, SingleRun, SingleRuns,
} from '../../imageTypes';
import { msgText, t, tm } from '../../i18n';
import { settingsFromPreset } from '../../lib/presetSettings';
import { pickReferenceFromGallery, takeReferenceHandoff } from '../../lib/referenceHandoff';
import { editablePrompt } from '../../lib/singlePromptSources';
import type { ImageView } from '../../types';
import { useUnsaved } from '../Unsaved';
import { Loading } from '../ui';
import ContentDialog from './ContentDialog';
import GalleryDetailFrame from './GalleryDetailFrame';
import QueuedImageNotice from './QueuedImageNotice';
import GenSettings, { FAMILY_DEFAULTS, modelsForFamily, useCatalog, type GenerationSettings } from './GenSettings';
import ReferenceEmotions from './ReferenceEmotions';
import SingleResultDetails from './SingleResultDetails';
import { resultSettings } from './singleResult';
import { mossDefaults, useReferenceDraft, type Draft, type ReferenceFamily, type SecondSubject } from './referenceDraft';
import './ImageSingle.css';
import './ImageReference.css';

type Preset = { id: string; name: string; service: string; family: string; settings: GenerationSettings };
type ReadinessAction = 'image' | 'install' | 'models' | 'moss' | 'update';
type Readiness = {
  family: ReferenceFamily;
  reasons: string[];
  actions: Set<ReadinessAction>;
  checking?: boolean;
  unverified?: boolean;
};
const working = (run: SingleRun | undefined) => run && ['queued', 'running', 'cancelling'].includes(run.status);
const failed = (run: SingleRun) => ['failed', 'cancelled', 'interrupted'].includes(run.status);
const usedReference = (run: SingleRun): ReferenceSnapshot | undefined => run.reference ?? run.actual?.reference;
const errorText = (error: unknown) => error instanceof ApiError ? tm(error.msg) : String(error);
const filename = (run: SingleRun) => run.path?.split('/').pop() || run.id;
const adapterName = { anima_v2: 'Anima Ref Adapter v2', snapref: 'SnapRef v2a' };
const emptySubject = (): SecondSubject => ({ reference: null, description: '' });

function groupHistory(history: SingleRun[]) {
  const entries: (SingleRun | { batchId: string; runs: SingleRun[] })[] = [];
  const batches = new Map<string, SingleRun[]>();
  for (const item of history) {
    if (!item.reference_batch) {
      entries.push(item);
      continue;
    }
    const batchId = item.reference_batch.id;
    const existing = batches.get(batchId);
    if (existing) existing.push(item);
    else {
      const runs = [item];
      batches.set(batchId, runs);
      entries.push({ batchId, runs });
    }
  }
  for (const items of batches.values()) {
    items.sort((a, b) => a.reference_batch!.index - b.reference_batch!.index);
  }
  return entries;
}

function runAnimaEngine(reference?: ReferenceSnapshot): AnimaReferenceEngine {
  return reference?.engine === 'snapref' ? 'snapref' : 'anima_v2';
}

function subjectPositionKey(position: ReferencePosition) {
  return 'reference.position_' + position;
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

function catalogSelection(value: string, names: string[]) {
  if (names.includes(value)) return value;
  const file = (path: string) => {
    const parts = path.split('::');
    const name = parts.pop()?.split(/[\\/]/).at(-1);
    return [...parts, name].join('::');
  };
  const matches = names.filter(name => file(name) === file(value));
  return matches.length === 1 ? matches[0] : value;
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
  workId?: string;
  openView: (view: ImageView) => void;
  openSettings?: (section?: 'image' | 'install') => void;
  active?: boolean;
}) {
  const id = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const fileSlot = useRef<ReferenceSlot>('a');
  const assetRequest = useRef(0);
  const endpoint = workId ? '/api/works/' + q(workId) + '/image/reference' : '/api/image/reference';
  const { draft, setDraft, loaded, dirty, loadError, saving, saveError, save, reload } = useReferenceDraft(workId, endpoint);
  const [generationMode, setGenerationMode] = useState<'single' | 'emotions'>('single');
  const [savedSlot, setSavedSlot] = useState<ReferenceSlot | null>(null);
  const [historyPage, setHistoryPage] = useState(0);
  const [error, setError] = useState('');
  const [pendingAsset, setPendingAsset] = useState<ReferenceSlot | null>(null);
  const [pendingJob, setPendingJob] = useState('');
  const [selectedRunId, setSelectedRunId] = useState('');
  const [preview, setPreview] = useState<ReferenceSlot | 'result' | null>(null);
  const [includeReference, setIncludeReference] = useState(false);
  const [exporting, setExporting] = useState(false);
  const catalogQuery = useCatalog();
  const catalog = catalogQuery.data;
  const animaStatus = useQuery<AnimaReferenceStatus>({
    queryKey: ['image-reference-status'],
    queryFn: () => get('/api/image/reference/status?family=anima'),
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
  const savedAssets = useQuery<ReferenceAssets>({
    queryKey: ['image-reference-assets'],
    queryFn: () => get(endpoint + '/assets'),
    enabled: active && !workId && savedSlot !== null,
  });
  const history = runs.data?.runs ?? [];
  const historyEntries = workId ? history : groupHistory(history);
  const historyPageCount = Math.max(1, Math.ceil(historyEntries.length / 12));
  const page = workId ? 0 : Math.min(historyPage, historyPageCount - 1);
  const run = history.find(item => item.id === selectedRunId) ?? history[0];
  const busy = !!pendingJob || history.some(working);
  const { family } = draft;
  const { preset, settings: rawSettings } = draft.parameters[family];
  const moss = family === 'moss';
  const snapref = !moss && draft.animaEngine === 'snapref';
  const batch = !workId && generationMode === 'emotions';
  const second = !moss && !batch ? draft.second : null;
  const firstPosition: ReferencePosition = second ? (draft.firstOnRight ? 'right' : 'left') : 'center';
  const secondPosition: ReferencePosition = draft.firstOnRight ? 'left' : 'right';
  const animaInfo = animaStatus.data;
  const animaAdapter = (engine: AnimaReferenceEngine) => animaInfo?.adapters?.[engine] ?? (engine === 'anima_v2' ? animaInfo : undefined);
  const mossInfo = mossStatus.data;
  const settings = moss ? mossSettings(rawSettings, mossInfo) : rawSettings;
  const mossModelChoices: Pick<MossReferenceStatus, 'models' | 'text_encoders' | 'vaes'> =
    mossInfo ?? { models: [], text_encoders: [], vaes: [] };
  const guidance = Number(draft.guidance);
  const validGuidance = moss || snapref || (draft.guidance !== '' && Number.isFinite(guidance) && guidance >= 0 && guidance <= 20);
  const animaModels = catalog?.connected ? modelsForFamily(catalog, 'anima') : [];
  const draftReadiness = checkReadiness(family, draft.animaEngine, settings, !!second);
  const validSubjects = !!draft.reference && (!second || !!second.reference);
  const canUseReference = !busy && !draftReadiness.reasons.length && validSubjects && !pendingAsset && validGuidance;
  const canGenerate = canUseReference && !!draft.positive.trim();
  const presetChoices = (presets.data ?? []).filter(item =>
    item.service === 'comfyui' && item.family === family && (!moss || supportsMossPreset(item.settings, mossInfo)));

  function checkReadiness(targetFamily: ReferenceFamily, engine: AnimaReferenceEngine,
    choices: Record<string, unknown> | undefined, twoSubjects: boolean, saved = false): Readiness {
    const isMoss = targetFamily === 'moss';
    const targetStatus = isMoss ? mossStatus : animaStatus;
    const reasons: string[] = [];
    const actions = new Set<ReadinessAction>();
    const add = (key: string, action: ReadinessAction) => { reasons.push(t(key)); actions.add(action); };
    const state = { family: targetFamily, reasons, actions };
    if (catalogQuery.error) {
      reasons.push(errorText(catalogQuery.error));
      actions.add('image');
    } else if (catalogQuery.isPending) return { ...state, reasons: [t('reference.checking_setup')], checking: true };
    else if (!catalog?.connected) add('gen.not_connected', 'image');
    if (!catalog?.connected || catalogQuery.error) return state;
    if (targetStatus.error) return { ...state, reasons: [errorText(targetStatus.error)] };
    if (targetStatus.isPending) return { ...state, reasons: [t('reference.checking_setup')], checking: true };

    if (isMoss) {
      if (!mossInfo?.node_ready) add('reference.moss_node_missing', 'moss');
      if (!mossInfo?.edit_node_ready) add('reference.moss_edit_node_missing', 'update');
      if (mossInfo?.weights_ready === false) add('reference.moss_weights_missing', 'moss');
      if (mossInfo?.foundation_ready === false) add('reference.moss_foundation_missing', 'moss');
      if (mossInfo && !mossInfo.ready && !reasons.length
        && mossInfo.models.length && mossInfo.text_encoders.length && mossInfo.vaes.length) {
        add('reference.moss_native_missing', 'update');
      }
    } else {
      const adapter = animaAdapter(engine);
      if (!adapter?.node_ready) add(engine === 'snapref' ? 'reference.snapref_node_missing' : 'reference.node_missing', 'install');
      if (!adapter?.weights_ready) add(engine === 'snapref' ? 'reference.snapref_weights_missing' : 'reference.weights_missing', 'install');
      if (adapter && !adapter.ready && !reasons.length) add('reference.not_ready', 'install');
      if (twoSubjects && !animaInfo?.stitch_ready) add('reference.stitch_missing', 'update');
    }

    const components = [
      { key: 'model', label: 'gen.model', catalogNames: catalog.models, allowed: isMoss ? mossModelChoices.models : animaModels },
      { key: 'text_encoder', label: 'gen.text_encoder', catalogNames: catalog.text_encoders, allowed: isMoss ? mossModelChoices.text_encoders : catalog.text_encoders },
      { key: 'vae', label: 'gen.vae', catalogNames: catalog.vaes, allowed: isMoss ? mossModelChoices.vaes : catalog.vaes },
    ] as const;
    for (const { key, label, catalogNames, allowed } of components) {
      const value = choices?.[key];
      // Anima fills omitted encoder and VAE choices from the connected server when queuing a new draft.
      if (!saved && !isMoss && key !== 'model' && value === undefined && allowed.length) continue;
      const selected = typeof value === 'string' ? value : '';
      const name = saved ? selected : catalogSelection(selected, catalogNames);
      if (allowed.includes(name) && catalogNames.includes(name)) continue;
      const component = t(label);
      if (selected) {
        reasons.push(t(saved ? 'reference.recorded_component_unavailable' : 'reference.selected_component_unavailable', { component, name: selected }));
      } else if (!saved && !isMoss && key === 'model') reasons.push(t('reference.choose_anima_model'));
      else reasons.push(t(saved ? 'reference.recorded_component_missing' : 'reference.choose_component', { component }));
      if (saved || !allowed.length || selected) actions.add(isMoss ? 'moss' : 'models');
    }
    return {
      ...state,
      unverified: isMoss && (mossInfo?.weights_ready === null || mossInfo?.foundation_ready === null),
    };
  }

  function readinessNotice({ family, reasons, actions, checking, unverified }: Readiness) {
    if (!reasons.length && !unverified) return null;
    const targetStatus = family === 'moss' ? mossStatus : animaStatus;
    return <div className="single-review reference-status" role="status">
      <div>
        {reasons.length ? reasons.map(reason => <div key={reason}>{reason}</div>)
          : <div>{t('reference.moss_files_unverified')}</div>}
      </div>
      {!!reasons.length && !checking && <div className="row reference-status-actions">
        {openSettings && actions.has('image') && <button type="button" onClick={() => openSettings('image')}>{t('gen.open_settings')}</button>}
        {openSettings && (actions.has('install') || (!workId && actions.has('models'))) && <button type="button" onClick={() => openSettings('install')}>{t('reference.open_install')}</button>}
        {workId && actions.has('models') && <button type="button" onClick={() => openView('models')}>{t('reference.open_models')}</button>}
        {actions.has('moss') && <a href="https://github.com/Neon3579/MossRef/tree/v2.0.0#install--quick-start" target="_blank" rel="noreferrer">{t('reference.moss_install')}</a>}
        {actions.has('update') && <a href="https://docs.comfy.org/installation/update_comfyui" target="_blank" rel="noreferrer">{t('reference.comfy_update')}</a>}
        <button type="button" disabled={targetStatus.isFetching || catalogQuery.isFetching}
          onClick={() => { void targetStatus.refetch(); void catalogQuery.refetch(); }}>{t('reference.recheck')}</button>
      </div>}
    </div>;
  }

  function update(patch: Partial<Draft>) {
    setDraft(current => ({ ...current, ...patch }));
  }

  useUnsaved('reference-draft', dirty || !!pendingAsset || (!workId && busy), async () => {
    if (pendingAsset || (!workId && busy)) return false;
    return !dirty || save();
  });

  useEffect(() => {
    if (!loaded || !catalog?.connected) return;
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
  }, [catalog, loaded, setDraft]);

  const setAsset = useCallback((slot: ReferenceSlot, reference: ReferenceAsset) => {
    setDraft(current => slot === 'a'
      ? { ...current, reference }
      : { ...current, second: { ...(current.second ?? emptySubject()), reference } });
  }, [setDraft]);

  const addAsset = useCallback(async (source: File | string, slot: ReferenceSlot) => {
    const selection = ++assetRequest.current;
    setPendingAsset(slot);
    setError('');
    try {
      if (typeof source !== 'string' && source.size > 32 * 1024 * 1024) throw new Error(t('server.reference.invalid_image'));
      const body = typeof source === 'string' ? { gallery_path: source } : { data_url: await fileData(source), filename: source.name };
      const reference = await post<ReferenceAsset>(endpoint + '/assets', body);
      if (selection === assetRequest.current) setAsset(slot, reference);
    } catch (err) {
      if (selection === assetRequest.current) setError(errorText(err));
    } finally {
      if (selection === assetRequest.current) setPendingAsset(null);
    }
  }, [endpoint, setAsset]);

  useEffect(() => {
    if (!active || !workId) return;
    const handoff = takeReferenceHandoff(workId);
    if (handoff) void addAsset(handoff.path, handoff.slot);
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

  async function runAction(action: string, submit: () => Promise<{ job_id: string } | void>, handleError?: (error: unknown) => boolean) {
    setPendingJob(action);
    setError('');
    try {
      const result = await submit();
      if (result) {
        setSelectedRunId(result.job_id);
        setHistoryPage(0);
        setIncludeReference(false);
        setPreview(null);
      }
      await runs.refetch();
    } catch (err) {
      if (!handleError?.(err)) setError(errorText(err));
    } finally {
      setPendingJob('');
    }
  }

  function enqueue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canGenerate || !draft.reference) return;
    const first = { slot: 'a', id: draft.reference.id, position: firstPosition, description: draft.description.trim() || undefined };
    const subjects = second?.reference
      ? [first, { slot: 'b', id: second.reference.id, position: secondPosition, description: second.description.trim() || undefined }]
      : [first];
    const body = {
      service: 'comfyui', positive: draft.positive, negative: draft.negative,
      preset_id: presetChoices.some(item => item.id === preset) ? preset : undefined, settings,
      reference: moss ? { id: draft.reference.id, engine: 'mossref' } : {
        engine: draft.animaEngine, subjects, ...(snapref ? { snapref_mode: draft.snaprefMode } : { guidance }),
      },
    };
    void runAction('generate', () => post<{ job_id: string }>(endpoint + '/queue', body));
  }

  function enqueueEmotions(selection: ReferenceEmotionSelection, revision: string, previewStale: (message: string) => void) {
    if (!batch || !canUseReference || !draft.reference || selection.family !== family) return;
    const reference = moss ? { id: draft.reference.id, engine: 'mossref' } : {
      engine: draft.animaEngine,
      subjects: [{ slot: 'a', id: draft.reference.id, position: 'center' }],
      ...(snapref ? { snapref_mode: draft.snaprefMode } : { guidance }),
    };
    void runAction('generate', () => post<{ job_id: string }>(endpoint + '/emotions/queue', {
      ...selection, settings, reference, preview_revision: revision,
    }), err => {
      if (!(err instanceof ApiError) || err.msg.key !== 'server.reference.emotions_stale') return false;
      previewStale(tm(err.msg));
      return true;
    });
  }

  function restore(selected: SingleRun) {
    const reference = usedReference(selected);
    if (!reference || !selected.actual) return;
    const family = reference.engine === 'mossref' ? 'moss' : 'anima';
    const actual = selected.actual;
    const first = 'subjects' in reference ? reference.subjects.find(item => item.slot === 'a') : reference;
    const second = 'subjects' in reference ? reference.subjects.find(item => item.slot === 'b') : undefined;
    if (!first) return;
    const scene = 'scene' in reference ? reference.scene_prompt ?? reference.scene : actual.positive;
    setGenerationMode('single');
    setDraft(current => ({
      ...current,
      positive: editablePrompt(scene),
      negative: editablePrompt(actual.negative),
      family,
      parameters: {
        ...current.parameters,
        [family]: { settings: { ...resultSettings(selected), family }, preset: '' },
      },
      reference: first,
      ...(reference.engine !== 'mossref' && {
        animaEngine: runAnimaEngine(reference),
        snaprefMode: reference.engine === 'snapref' ? reference.snapref_mode ?? 'cs' : current.snaprefMode,
        description: 'subjects' in reference ? reference.subjects.find(item => item.slot === 'a')?.description ?? '' : '',
        second: second ? { reference: second, description: second.description ?? '' } : null,
        firstOnRight: 'position' in first && first.position === 'right',
        guidance: typeof reference.guidance === 'number' ? String(reference.guidance) : current.guidance,
      }),
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

  const previewImage = preview === 'a' ? draft.reference : preview === 'b' ? second?.reference
    : preview === 'result' && run?.image_url ? { url: run.image_url, name: filename(run) } : null;
  const resultReference = run ? usedReference(run) : undefined;
  const resultSubjects = resultReference && 'subjects' in resultReference ? resultReference.subjects : undefined;
  const resultIsMoss = resultReference?.engine === 'mossref';
  const resultAdapter = runAnimaEngine(resultReference);
  const resultReadiness = resultReference && checkReadiness(
    resultIsMoss ? 'moss' : 'anima', resultAdapter, run?.actual?.settings, resultSubjects?.length === 2, true);
  const retryReady = resultReadiness?.reasons.length === 0;
  const resultDetails = run?.status === 'done' && <>
    {resultReference && <dl className="single-result-summary reference-record">
      <div><dt>{t('gen.family')}</dt><dd>{resultIsMoss ? 'MOSS (MossRef)' : 'Anima'}</dd></div>
      {!resultIsMoss && <div><dt>{t('reference.adapter')}</dt><dd>{adapterName[resultAdapter]}</dd></div>}
      {resultReference.engine === 'snapref' && <div><dt>{t('reference.snapref_mode')}</dt><dd>{t(resultReference.snapref_mode === 'char' ? 'reference.snapref_char' : 'reference.snapref_cs')}</dd></div>}
      {resultReference.engine !== 'mossref' && resultReference.guidance !== undefined
        && <div><dt>{t('reference.guidance')}</dt><dd>{resultReference.guidance}</dd></div>}
      {'subjects' in resultReference ? resultReference.subjects.map(subject => <div key={subject.slot}>
        <dt>{t(subject.slot === 'a' ? 'reference.subject_a' : 'reference.subject_b')} · {t(subjectPositionKey(subject.position))}</dt>
        <dd>{subject.name}{subject.description ? ' · ' + subject.description : ''}<br /><span className="mono">SHA-256 {subject.sha256}</span></dd>
      </div>) : <>
        <div><dt>{t('reference.image')}</dt><dd>{resultReference.name}</dd></div>
        <div><dt>SHA-256</dt><dd className="mono">{resultReference.sha256}</dd></div>
      </>}
    </dl>}
    <SingleResultDetails
      run={run}
      current={{ service: 'comfyui', positive: draft.positive, negative: draft.negative, settings }}
      busy={busy || !resultReference || !run.path}
      regenerateReadiness={resultReadiness && { blocked: !retryReady, notice: readinessNotice(resultReadiness) }}
      handoffPending={false}
      restore={() => restore(run)}
      regenerate={newSeed => {
        if (!run.path || !retryReady) return;
        void runAction('regenerate', () => post<{ job_id: string }>(endpoint + '/regenerate', { path: run.path, same_seed: !newSeed }));
      }}
    />
    {run.path && <div className="single-result-group col">
      <h4>{t('reference.export')}</h4>
      <label className="row"><input type="checkbox" checked={includeReference} onChange={event => setIncludeReference(event.target.checked)} />
        {t(resultSubjects && resultSubjects.length > 1 ? 'reference.include_originals' : 'reference.include_original')}
      </label>
      <div><button type="button" disabled={exporting} onClick={() => void download(run.path!)}>{t('gallery.download_zip')}</button></div>
    </div>}
  </>;

  function renderReference(slot: ReferenceSlot, asset: ReferenceAsset | null, description: string, position: ReferencePosition) {
    const title = t(second ? (slot === 'a' ? 'reference.subject_a' : 'reference.subject_b') : 'reference.image');
    return <section key={slot} id={slot === 'b' ? id + '-second' : undefined} className="reference-card" data-slot={slot}
      aria-labelledby={id + '-subject-' + slot} aria-describedby={second ? id + '-position-' + slot : undefined}>
      {asset && <button type="button" className="reference-preview" aria-haspopup="dialog"
        aria-label={t('reference.open_preview', { name: asset.name })} onClick={event => {
          event.currentTarget.focus();
          setPreview(slot);
        }}>
        <img src={asset.url} alt="" />
      </button>}
      <div className="col">
        <div className="row">
          <h3 id={id + '-subject-' + slot}>{title}</h3>
          {second && <span id={id + '-position-' + slot} className="muted small">{t(subjectPositionKey(position))}</span>}
        </div>
        {batch && <p className="reference-emotion-hint muted small">{t('reference.emotions_reference_hint')}</p>}
        {asset ? <strong>{asset.name}</strong> : <span className="faint">{t('reference.choose_hint')}</span>}
        <div className="row">
          <button type="button" disabled={!!pendingAsset} onClick={() => {
            fileSlot.current = slot;
            fileInput.current?.click();
          }}>{t(asset ? 'reference.replace_file' : 'reference.choose_file')}</button>
          {workId ? <button type="button" disabled={!!pendingAsset} onClick={() => {
            pickReferenceFromGallery(workId, slot);
            openView('gallery');
          }} title={t('reference.gallery_hint')}>{t('reference.choose_gallery')}</button>
          : <button type="button" disabled={!!pendingAsset} aria-haspopup="dialog" onClick={() => setSavedSlot(slot)}>
            {t('reference.choose_saved')}
          </button>}
          {asset && <button type="button" className="ghost" disabled={!!pendingAsset} onClick={() => {
            if (slot === 'a') update({ reference: null });
            else if (second) update({ second: { ...second, reference: null } });
          }}>{t('reference.remove')}</button>}
        </div>
        {!batch && !moss && (second || description) && <label className="single-field reference-subject-description">
          <span>{t('reference.subject_description')}</span>
          <input value={description} placeholder={t('reference.subject_description_hint')} onChange={event => {
            const value = event.target.value;
            if (slot === 'a') update({ description: value });
            else if (second) update({ second: { ...second, description: value } });
          }} />
        </label>}
        {pendingAsset === slot && <span role="status" className="faint">{t('reference.importing')}</span>}
      </div>
    </section>;
  }

  function renderHistoryItem(item: SingleRun) {
    const batchItem = item.reference_batch;
    const name = batchItem?.expression_name ?? filename(item);
    return <button key={item.id} type="button" className={'single-history-row' + (item.id === run?.id ? ' is-selected' : '')}
      aria-pressed={item.id === run?.id} onClick={() => {
        setSelectedRunId(item.id); setIncludeReference(false); setPreview(null);
      }}>
      {item.image_url ? <img className="single-history-thumb" src={item.image_url} alt="" loading="lazy" /> : <span className="single-history-thumb" />}
      <span className="single-history-content">
        <span className="single-history-name" title={name}>{name}</span>
        {batchItem?.composition_name && <span className="faint small">{batchItem.composition_name}</span>}
        <span className="faint small">{t('single.state.' + item.status)}</span>
      </span>
    </button>;
  }

  if (!loaded) return loadError
    ? <div role="alert">{loadError} <button type="button" onClick={reload}>{t('single.reload_draft')}</button></div>
    : <Loading />;

  const firstCard = renderReference('a', draft.reference, draft.description, firstPosition);
  const secondCard = second && renderReference('b', second.reference, second.description, secondPosition);
  const guidanceSettings = !moss && !snapref && <details className="single-details">
    <summary>{t('reference.details')}</summary>
    <label className="row reference-guidance">
      <span>{t('reference.guidance')}</span>
      <input type="number" min={0} max={20} step="any" value={draft.guidance} onChange={event => update({ guidance: event.target.value })}
        aria-describedby={id + '-guidance-hint'} />
    </label>
    <p id={id + '-guidance-hint'} className="faint small">{t('reference.guidance_hint')}</p>
  </details>;

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
      {!workId && <div className="seg reference-generation-modes" role="group" aria-label={t('reference.generation_mode')}>
        <button type="button" className={!batch ? 'on' : ''} aria-pressed={!batch}
          onClick={() => setGenerationMode('single')}>{t('reference.single_mode')}</button>
        <button type="button" className={batch ? 'on' : ''} aria-pressed={batch}
          onClick={() => setGenerationMode('emotions')}>{t('reference.emotions_mode')}</button>
      </div>}
      <div className="row reference-family">
        <span id={id + '-family'} className="muted">{t('gen.family')}</span>
        <div className="seg" role="group" aria-labelledby={id + '-family'}>
          <button type="button" className={!moss ? 'on' : ''} aria-pressed={!moss} onClick={() => update({ family: 'anima' })}>Anima</button>
          <button type="button" className={moss ? 'on' : ''} aria-pressed={moss} onClick={() => update({ family: 'moss' })}>MOSS</button>
        </div>
        {!moss && <label className="row reference-adapter">
          <span className="muted">{t('reference.adapter')}</span>
          <select value={draft.animaEngine} onChange={event => update({ animaEngine: event.target.value === 'snapref' ? 'snapref' : 'anima_v2' })}>
            <option value="anima_v2">{adapterName.anima_v2}</option>
            <option value="snapref">{adapterName.snapref}</option>
          </select>
        </label>}
        {snapref && <label className="row reference-adapter">
          <span className="muted">{t('reference.snapref_mode')}</span>
          <select value={draft.snaprefMode} onChange={event => update({ snaprefMode: event.target.value === 'char' ? 'char' : 'cs' })}>
            <option value="cs">{t('reference.snapref_cs')}</option>
            <option value="char">{t('reference.snapref_char')}</option>
          </select>
        </label>}
      </div>
      {saveError ? <p className="warn-text" role="alert">{saveError} <button type="button" disabled={saving} onClick={() => void save()}>{t('common.save')}</button>
        {!workId && <button type="button" disabled={saving} onClick={() => { if (confirm(t('single.reload_draft_confirm'))) reload(); }}>{t('single.reload_draft')}</button>}
      </p> : !workId && <p className="faint small">{t(dirty ? 'single.saving_draft' : 'single.portable_draft')}</p>}
      {error && <p className="warn-text" role="alert">{error}</p>}
      <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden
        onChange={event => {
          const file = event.currentTarget.files?.[0];
          event.currentTarget.value = '';
          if (file) void addAsset(file, fileSlot.current);
        }} />
      {batch && firstCard}
      <div className="single-layout">
        <aside className="single-form single-settings">
          <label className="single-field">
            <span>{t(batch ? 'reference.emotions_settings_preset' : 'single.preset')}</span>
            <select value={presetChoices.some(item => item.id === preset) ? preset : ''} onChange={event => choosePreset(event.target.value)}>
              <option value="">{t('gen.default')}</option>
              {presetChoices.map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          </label>
          <GenSettings value={settings} onChange={settings => setDraft(current => ({
            ...current, parameters: { ...current.parameters, [family]: { ...current.parameters[family], settings } },
          }))} onlyFamily={family} showFamily={false} mossReference={moss ? mossModelChoices : undefined} />
          {batch && guidanceSettings}
        </aside>
        <div className="single-workspace">
          {!workId && <ReferenceEmotions family={family} shown={batch} active={active} ready={canUseReference} busy={busy}
            readiness={batch && readinessNotice(draftReadiness)} enqueue={enqueueEmotions} openQueue={() => openView('queue')} />}
          {!batch && <form className="single-form single-prompts" onSubmit={enqueue}>
            <div className={second ? 'reference-subjects-pair' : undefined}>
              {secondCard && draft.firstOnRight ? [secondCard, firstCard] : [firstCard, secondCard]}
              {!moss && !second && <div id={id + '-second'} hidden />}
            </div>
            {!moss && <div className="row reference-subject-actions">
              <button type="button" className="ghost" aria-expanded={!!second} aria-controls={id + '-second'}
                disabled={!!pendingAsset} onClick={() => update({ second: second ? null : emptySubject(), firstOnRight: false })}>
                {t(second ? 'reference.remove_subject' : 'reference.add_subject')}
              </button>
              {second && <button type="button" onClick={() => update({ firstOnRight: !draft.firstOnRight })}>
                {t('reference.swap_positions')}
              </button>}
            </div>}
            <label className="single-field" htmlFor={id + '-scene'}>
              <span>{t('reference.scene')}</span>
              <textarea id={id + '-scene'} rows={5} value={draft.positive} placeholder={t(moss ? 'reference.moss_scene_hint' : 'reference.scene_hint')} onChange={event => update({ positive: event.target.value })} />
            </label>
            <label className="single-field" htmlFor={id + '-negative'}>
              <span>{t('single.negative')}</span>
              <textarea id={id + '-negative'} rows={3} value={draft.negative} onChange={event => update({ negative: event.target.value })} />
            </label>
            {guidanceSettings}
            {readinessNotice(draftReadiness)}
            <div className="row reference-actions">
              <button type="submit" className="primary" disabled={!canGenerate}>{t('single.run')}</button>
              <button type="button" className="ghost" onClick={() => openView('queue')}>{t('image_menu.queue')}</button>
            </div>
          </form>}
          <section className="single-result">
            <div className="single-result-head">
              <h3>{t('single.result')}</h3>
              <span role="status">{t('single.state.' + (run?.status ?? 'idle'))}</span>
            </div>
            {run?.reference_batch && <p className="reference-result-emotion">
              <strong>{run.reference_batch.expression_name}</strong>
              {run.reference_batch.composition_name && <span className="muted">{run.reference_batch.composition_name}</span>}
            </p>}
            {active && run?.status === 'queued' && <QueuedImageNotice />}
            {runs.error && <p className="warn-text" role="alert">{errorText(runs.error)}</p>}
            {run?.error && <p className="warn-text" role="alert">{msgText(run.error)}</p>}
            {run?.image_url ? <button type="button" className="single-canvas" aria-label={t('single.open_preview')} onClick={() => setPreview('result')}>
              <img src={run.image_url} alt={t('single.result')} />
            </button> : <p className="faint">{t('reference.result_hint')}</p>}
            {run && working(run) && <button type="button" disabled={!!pendingJob || run.status === 'cancelling'}
              onClick={() => void runAction('cancel', async () => { await post('/api/image/jobs/' + q(run.id) + '/cancel'); })}>{t('common.cancel')}</button>}
            {run && failed(run) && resultReadiness && readinessNotice(resultReadiness)}
            {run && failed(run) && <button type="button" disabled={busy || !retryReady}
              onClick={() => void runAction('retry', () => post<{ job_id: string }>('/api/image/jobs/' + q(run.id) + '/retry'))}>{t('single.retry')}</button>}
            {resultDetails}
            {workId && run?.status === 'done' && <div className="single-result-links"><button type="button" className="ghost" onClick={() => openView('gallery')}>{t('image_menu.gallery')}</button></div>}
            {!!history.length && <div className="single-history">
              <h4>{t(workId ? 'single.history' : 'reference.standalone_history')}</h4>
              <div className="single-history-list">
                {historyEntries.slice(page * 12, (page + 1) * 12).map(item => 'batchId' in item
                  ? <section key={item.batchId} className="reference-history-batch">
                    <h5>{t('reference.emotions_batch', { count: item.runs[0].reference_batch!.count })}</h5>
                    <div className="single-history-list">{item.runs.map(renderHistoryItem)}</div>
                  </section>
                  : renderHistoryItem(item))}
              </div>
              {!workId && historyPageCount > 1 && <div className="single-history-pages">
                <button type="button" disabled={page === 0} onClick={() => setHistoryPage(page - 1)}>{t('single.previous_page')}</button>
                <span>{t('single.history_page', { current: page + 1, total: historyPageCount })}</span>
                <button type="button" disabled={page + 1 >= historyPageCount} onClick={() => setHistoryPage(page + 1)}>{t('single.next_page')}</button>
              </div>}
            </div>}
          </section>
        </div>
      </div>
      {savedSlot && <ContentDialog title={t('reference.choose_saved')} onClose={() => setSavedSlot(null)}>
        {savedAssets.isPending ? <Loading /> : savedAssets.error ? <p role="alert">{errorText(savedAssets.error)}</p>
          : !savedAssets.data?.assets.length ? <p className="faint">{t('reference.no_saved_assets')}</p>
          : <div className="single-history-list reference-saved-assets">
            {savedAssets.data.assets.map(asset => <button key={asset.id} type="button" className="single-history-row" onClick={() => {
              setAsset(savedSlot, asset);
              setSavedSlot(null);
            }}>
              <img src={asset.url} alt="" className="single-history-thumb" loading="lazy" />
              <span className="single-history-content"><span className="single-history-name" title={asset.name}>{asset.name}</span></span>
            </button>)}
          </div>}
      </ContentDialog>}
      {previewImage && <GalleryDetailFrame imageUrl={previewImage.url}
        label={preview === 'result' ? previewImage.name : t('reference.preview_title', { name: previewImage.name })}
        close={() => setPreview(null)}>
        <div className="row"><strong className="grow">{previewImage.name}</strong>
          <button type="button" className="ghost" aria-label={t('common.close')} onClick={() => setPreview(null)}>×</button>
        </div>
      </GalleryDetailFrame>}
    </div>
  </section>;
}
