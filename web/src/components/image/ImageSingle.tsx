import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm, msgText } from '../../i18n';
import type { ImageView } from '../../types';
import type { GalleryToolsResponse, PromptSource, SingleRun, SingleRuns } from '../../imageTypes';
import { combineSources, promptSources, restorePromptSources, validSources, cleanPrompt, editablePrompt, replaceSource } from '../../lib/singlePromptSources';
import { settingsFromPreset } from '../../lib/presetSettings';
import { fits } from '../../lib/fragments';
import { useUnsaved } from '../Unsaved';
import type { ImageServices } from '../ImageServiceSettings';
import GenSettings, { FAMILY_DEFAULTS, useCatalog, type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { SERVICE_NAMES } from './serviceSettings';
import { sendToLab } from './ImageLab';
import { sendToTools } from '../../lib/toolHandoff';
import GalleryDetailFrame from './GalleryDetailFrame';
import SingleResultDetails from './SingleResultDetails';
import { resultSeed, resultSettings } from './singleResult';
import GenerationResolution from './GenerationResolution';
import SinglePromptMaterials, { StyleThumbnails, tagsText, type StyleChoice } from './SinglePromptMaterials';
import ShotPicker from './ShotPicker';
import { AUTO_SHOT, compositionSource, shotChoiceFromSource, useShotLibrary, type ShotChoice } from '../../lib/shots';
import './ImageSingle.css';

type Service = 'comfyui' | 'novelai' | 'pixai';
type Draft = { schema_version: 3; positive: string; negative: string; service: Service; settings: Record<Service, Record<string, unknown>>; preset: string; sources: PromptSource[]; legacyPreset?: boolean };
type Preset = StyleChoice & { service: string; family: string; settings: Record<string, unknown>; common?: string[]; artist?: { positive?: string; negative?: string } };
type Common = { id: string; name: string; prompt?: string[]; target?: string; targets?: string[] };
const storageKey = (work: string) => `atelierx-single-v2-${work}`;
const fresh = (): Draft => ({ schema_version: 3, positive: '', negative: '', service: 'comfyui', preset: '', sources: [], settings: {
  comfyui: { family: 'anima', ...FAMILY_DEFAULTS.anima, seed: -1 }, novelai: {}, pixai: {},
} });
function readDraft(work: string): Draft {
  const fallback = fresh();
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(work)) || 'null') as Draft | null;
    if (!saved || typeof saved.positive !== 'string' || typeof saved.negative !== 'string' || !['comfyui', 'novelai', 'pixai'].includes(saved.service)) return fallback;
    return { ...fallback, positive: saved.positive, negative: saved.negative, service: saved.service,
      preset: validSources(saved.sources) && typeof saved.preset === 'string' ? saved.preset : '',
      sources: validSources(saved.sources) ? saved.sources.filter(source => source.kind !== 'direct') : [],
      legacyPreset: saved.legacyPreset || (!validSources(saved.sources) && !!saved.preset),
      settings: Object.fromEntries(Object.entries(fallback.settings).map(([key, value]) => [key, { ...value, ...saved.settings?.[key as Service] }])) as Draft['settings'] };
  } catch { return fallback; }
}
const active = (run: SingleRun | undefined) => !!run && ['queued', 'running', 'cancelling'].includes(run.status);
const filenameOf = (run: SingleRun) => run.path?.split('/').pop() || `${run.id}.png`;
const localTime = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
};
const HISTORY_PAGE_SIZE = 6;

export default function ImageSingle({ workId, openView }: { workId: string; openView: (view: ImageView) => void }) {
  const id = useId();
  const qc = useQueryClient();
  const [draft, setDraft] = useState(() => readDraft(workId));
  const [stored, setStored] = useState('');
  const [storageFailed, setStorageFailed] = useState(false);
  const [pending, setPending] = useState(false);
  const [runId, setRunId] = useState('');
  const [error, setError] = useState('');
  const [handoffPending, setHandoffPending] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [historyPage, setHistoryPage] = useState(0);
  const services = useQuery<ImageServices>({ queryKey: ['image-services'], queryFn: () => get('/api/image/services') });
  const catalog = useCatalog();
  const { compositions, rules } = useShotLibrary(workId);
  const [unappliedShot, setUnappliedShot] = useState<ShotChoice>(AUTO_SHOT);
  const presets = useQuery<Preset[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets') });
  const commons = useQuery<Record<string, Common>>({ queryKey: ['image-lib', 'common', workId], queryFn: () => get(`/api/image/library/common?work=${workId}`) });
  const runs = useQuery<SingleRuns>({ queryKey: ['image-single-runs', workId], queryFn: () => get(`/api/works/${workId}/image/single/runs`), refetchInterval: 1500 });
  const history = (runs.data?.runs ?? []).slice(0, 100);
  const pageCount = Math.max(1, Math.ceil(history.length / HISTORY_PAGE_SIZE));
  const page = Math.min(historyPage, pageCount - 1);
  const visibleHistory = history.slice(page * HISTORY_PAGE_SIZE, (page + 1) * HISTORY_PAGE_SIZE);
  const run = history.find(r => r.id === runId) ?? history[0];
  const busy = pending || history.some(active);
  const serialized = JSON.stringify(draft);
  function saveDraft(): boolean {
    try { localStorage.setItem(storageKey(workId), serialized); setStored(serialized); setStorageFailed(false); return true; }
    catch { setStorageFailed(true); return false; }
  }
  useEffect(() => { saveDraft(); }, [serialized, workId]);
  useUnsaved('single-draft', stored !== serialized || busy, async () => saveDraft() && !busy);
  useEffect(() => {
    if (!catalog.data?.connected) return;
    const defaults = catalog.data.defaults;
    setDraft(current => current.settings.comfyui.model ? current : {
      ...current, settings: { ...current.settings, comfyui: { ...defaults, ...current.settings.comfyui, model: defaults.model } },
    });
  }, [catalog.data]);
  const update = (patch: Partial<Draft>) => setDraft(current => ({ ...current, ...patch }));
  const settings = draft.settings[draft.service];
  const setSettings = (value: Record<string, unknown>) => setDraft(current => ({ ...current, settings: { ...current.settings, [current.service]: value } }));
  const serviceInfo = services.data?.services.find(service => service.id === draft.service);
  const ready = draft.service === 'comfyui' ? catalog.data?.connected : serviceInfo?.supported && serviceInfo.connected;
  const servicePresets = (presets.data ?? []).filter(preset => preset.service === draft.service);
  const shotTarget = draft.service === 'comfyui' ? String(settings.family || 'anima') : draft.service;
  const frozenShot = draft.sources.find(source => source.kind === 'composition');
  const shotChoice = frozenShot ? shotChoiceFromSource(frozenShot.id) : unappliedShot;
  function chooseShot(choice: ShotChoice) {
    const source = compositionSource(choice, rules.data, compositions.data, shotTarget);
    setUnappliedShot(source ? AUTO_SHOT : choice);
    setDraft(current => ({ ...current, sources: replaceSource(current.sources, 'composition', source) }));
  }
  const appliedStyle = draft.sources.find(source => source.kind === 'style');
  const sourceList = promptSources(draft.positive, draft.negative, draft.sources);
  const positive = combineSources(sourceList, 'positive');
  const negative = combineSources(sourceList, 'negative');
  function choosePreset(ident: string) {
    const preset = servicePresets.find(item => item.id === ident);
    const target = preset?.service === 'comfyui' ? preset.family : preset?.service;
    const items = (preset?.common ?? []).map(key => commons.data?.[key]);
    if (items.some(item => !item || !fits(item, target))) { setError(t('materials.common_unavailable')); return; }
    const selected = items.filter((item): item is Common => !!item);
    const materials: PromptSource[] = preset ? [
      { kind: 'common', id: preset.id, name: preset.name, positive: tagsText(selected.filter(item => item.target !== 'negative').flatMap(item => item.prompt ?? [])),
        negative: tagsText(selected.filter(item => item.target === 'negative').flatMap(item => item.prompt ?? [])) },
      { kind: 'style', id: preset.id, name: preset.name, positive: cleanPrompt(preset.artist?.positive ?? ''), negative: cleanPrompt(preset.artist?.negative ?? '') },
    ] : [];
    setError('');
    setDraft(current => ({ ...current, preset: ident, legacyPreset: false,
      sources: [...current.sources.filter(source => !['style', 'common'].includes(source.kind)), ...materials],
      settings: preset ? { ...current.settings, [current.service]: current.service === 'comfyui'
        ? settingsFromPreset(current.settings.comfyui, preset.settings, preset.family as 'anima' | 'sdxl', FAMILY_DEFAULTS)
        : { ...current.settings[current.service], ...preset.settings } } : current.settings }));
  }
  const fail = (err: unknown) => setError(err instanceof ApiError ? tm(err.msg) : String(err));
  const refresh = () => qc.invalidateQueries({ queryKey: ['image-single-runs', workId] });
  async function enqueue(value = draft, repeatOk = false) {
    if (busy || !combineSources(promptSources(value.positive, value.negative, value.sources), 'positive')) return;
    setPending(true); setError('');
    try {
      const request = {
        positive: value.positive, negative: value.negative, service: value.service,
        preset_id: value.preset || undefined, prompt_sources: promptSources(value.positive, value.negative, value.sources), settings: value.settings[value.service], repeat_ok: repeatOk,
      };
      let response: { job_id: string };
      try { response = await post(`/api/works/${workId}/image/single`, request); }
      catch (err) {
        if (!(err instanceof ApiError && err.msg.key === 'server.image.services.repeat' && confirm(tm(err.msg)))) throw err;
        response = await post(`/api/works/${workId}/image/single`, { ...request, repeat_ok: true });
      }
      setRunId(response.job_id);
      setHistoryPage(0);
      setPreviewOpen(false);
      await refresh();
    } catch (err) { fail(err); }
    finally { setPending(false); }
  }
  async function cancel() {
    if (!run || !active(run)) return;
    try { await post(`/api/image/jobs/${run.id}/cancel`); await refresh(); }
    catch (err) { fail(err); }
  }
  async function retry() {
    if (!run || busy) return;
    setPending(true); setError('');
    try {
      const response = await post<{ job_id: string }>(`/api/image/jobs/${run.id}/retry`);
      setRunId(response.job_id);
      setHistoryPage(0);
      setPreviewOpen(false);
      await post('/api/image/queue/resume');
      await refresh();
    } catch (err) { fail(err); }
    finally { setPending(false); }
  }
  function restore(selected: SingleRun) {
    if (busy || !selected.actual || !selected.service) return;
    setPreviewOpen(false);
    setUnappliedShot(AUTO_SHOT);
    setDraft(current => ({ ...current, ...restorePromptSources(selected),
      service: selected.service, preset: '', legacyPreset: false,
      settings: { ...current.settings, [selected.service]: resultSettings(selected) },
    }));
  }
  async function regenerate(newSeed: boolean) {
    if (!run?.actual || !run.service || (!newSeed && resultSeed(run) === undefined)) return;
    const value = {
      ...draft, ...restorePromptSources(run), service: run.service, preset: '', legacyPreset: false,
      settings: { ...draft.settings, [run.service]: resultSettings(run, newSeed) },
    };
    await enqueue(value, true);
  }
  async function handoffTools() {
    if (!run?.path || handoffPending) return;
    setHandoffPending(true); setError('');
    try {
      const response = await post<GalleryToolsResponse>('/api/image/tools/gallery', { paths: [run.path] });
      const item = response.items[0];
      if (!item) throw new Error(t('single.handoff_failed'));
      sendToTools(item.id);
      setPreviewOpen(false);
      openView('tools');
    } catch (err) { fail(err); }
    finally { setHandoffPending(false); }
  }
  function handoffLab() {
    if (!run?.actual || !run.path || run.service !== 'comfyui') return;
    sendToLab({ positive: editablePrompt(run.actual.positive), negative: editablePrompt(run.actual.negative),
      settings: resultSettings(run) as GenerationSettings, source: run.path });
    setPreviewOpen(false);
    openView('lab');
  }
  const resultDetails = run && <SingleResultDetails key={run.id} run={run}
    current={{ service: draft.service, positive, negative, settings, sources: sourceList.filter(source => source.kind !== 'direct') }}
    restoredSources={restorePromptSources(run).sources}
    busy={busy} handoffPending={handoffPending} restore={() => restore(run)} regenerate={regenerate}
    handoff={target => target === 'tools' ? handoffTools() : handoffLab()} />;

  return <section className="single-image generation-page" aria-label={t('image_menu.single')}>
    <div className="generation-content">
    <header className="single-heading"><div><h2>{t('image_menu.single')}</h2><span className="faint">{t('single.subtitle')}</span></div>
      <div className="seg" aria-label={t('single.mode')}><button type="button" className="on" aria-pressed="true">{t('single.general')}</button><button type="button" disabled>{t('single.multi')}</button></div>
    </header>
    <div className="single-layout">
      <div className="single-form">
        <div className="single-service" role="group" aria-label={t('gen.service')}>
          {(['comfyui', 'novelai', 'pixai'] as Service[]).map(service => <button type="button" key={service} className={draft.service === service ? 'selected' : ''} aria-pressed={draft.service === service} onClick={() => update({ service, preset: '', sources: draft.sources.filter(source => !['style', 'common'].includes(source.kind)) })}>{SERVICE_NAMES[service]}</button>)}
        </div>
        {!ready && <p className="warn-text" role="alert">{draft.service === 'comfyui' ? t('gen.not_connected') : t('single.service_unavailable')}</p>}
        <label className="single-field"><span>{t('single.preset')}</span><select value={appliedStyle ? '__snapshot__' : ''} onChange={e => { if (e.target.value !== '__snapshot__') choosePreset(e.target.value); }} disabled={commons.isPending}>
          {appliedStyle && <option value="__snapshot__" disabled>{t('materials.applied_style', { name: appliedStyle.name })}</option>}
          <option value="">{t('gen.no_preset')}</option>{servicePresets.map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
        </select></label>
        {draft.legacyPreset && <p className="warn-text">{t('materials.legacy_draft')}</p>}
        <StyleThumbnails presets={servicePresets} selected={appliedStyle?.id ?? ''} choose={choosePreset} disabled={commons.isPending} />
        <button type="button" className="ghost" onClick={() => openView('presets')}>{t('materials.open_styles')}</button>
        <label className="single-field" htmlFor={`${id}-positive`}><span>{t('single.positive')}</span><textarea id={`${id}-positive`} rows={6} value={draft.positive} placeholder={t('single.positive_hint')} onChange={e => update({ positive: e.target.value })} /></label>
        <label className="single-field" htmlFor={`${id}-negative`}><span>{t('single.negative')}</span><textarea id={`${id}-negative`} rows={3} value={draft.negative} placeholder={t('single.negative_hint')} onChange={e => update({ negative: e.target.value })} /></label>
        <div className="single-helpers"><button type="button" onClick={() => update({ positive: [draft.positive, 'a quiet lakeside, distant mountains, morning light'].filter(Boolean).join(', ') })}>{t('single.add_sample')}</button><span className="faint small">{t('single.sample_hint')}</span></div>
        <ShotPicker value={shotChoice} rules={rules.data} compositions={compositions.data} target={shotTarget}
          frozenSource={frozenShot} onChange={chooseShot} />
        <SinglePromptMaterials workId={workId} target={shotTarget} sources={draft.sources}
          change={modify => setDraft(current => ({ ...current, sources: modify(current.sources) }))} positive={draft.positive} negative={draft.negative} openLibrary={() => openView('library')} />
        <details className="single-details"><summary>{t('single.final_prompt')}</summary><h4>Positive</h4><pre>{positive || '—'}</pre><h4>Negative</h4><pre>{negative || '—'}</pre><p className="faint small">{t('single.final_note')}</p></details>
        <div className="section-title">{t('single.settings')}</div>
        <p className="faint small">{t('single.settings_hint')}</p>
        {draft.service === 'comfyui' && <GenSettings compact value={settings as GenerationSettings} onChange={value => setSettings(value)} />}
        {draft.service === 'novelai' && <NovelAISettings compact value={settings} onChange={setSettings} />}
        {draft.service === 'pixai' && <PixAISettings compact value={settings} onChange={setSettings} />}
        {storageFailed ? <p role="alert" className="warn-text">{t('single.storage_failed')} <button onClick={saveDraft}>{t('common.save')}</button></p> : <p className="faint small">{t('single.local_draft')}</p>}
      </div>
      <div className="single-result">
        <div className="single-result-head"><h3>{t('single.result')}</h3><span role="status" aria-live="polite">{t(`single.state.${pending && !run ? 'queued' : run?.status ?? 'idle'}`)}</span></div>
        {error && !previewOpen && <div className="single-review" role="alert">{error}</div>}
        {run?.error && <div className="single-review" role="alert">{msgText(run.error)}</div>}
        {run && ['failed', 'cancelled', 'interrupted'].includes(run.status) && <button type="button" disabled={busy} onClick={retry}>{t('single.retry')}</button>}
        {busy && <progress aria-label={t('single.progress')} />}
        {run?.image_url
          ? <button type="button" className="single-canvas" aria-label={t('single.open_preview')} onClick={() => setPreviewOpen(true)}><img src={run.image_url} alt="" /></button>
          : <div className="single-canvas"><div className="single-empty">{t('single.empty')}</div></div>}
        {resultDetails}
        <div className="single-result-links"><button type="button" className="ghost" onClick={() => openView('gallery')}>{t('image_menu.gallery')}</button><button type="button" className="ghost" onClick={() => openView('queue')}>{t('image_menu.queue')}</button></div>
        {history.length > 0 && <div className="single-history">
          <h4>{t('single.history')}</h4>
          <p className="faint small">{t('single.history_limit')} <button type="button" className="ghost" onClick={() => openView('gallery')}>{t('single.view_all')}</button></p>
          <div className="single-history-list">{visibleHistory.map(entry => <button key={entry.id} type="button"
            className={`single-history-row${run?.id === entry.id ? ' is-selected' : ''}`} aria-pressed={run?.id === entry.id}
            onClick={() => { setRunId(entry.id); setError(''); setPreviewOpen(false); }}>
            {entry.image_url ? <img className="single-history-thumb" src={entry.image_url} alt="" /> : <span className="single-history-thumb" />}
            <span className="single-history-content"><span className="single-history-name" title={filenameOf(entry)}>{filenameOf(entry)}</span>
              <span className="faint small">{localTime(entry.created_at)} · {t(`single.state.${entry.status}`)}</span></span>
          </button>)}</div>
          {pageCount > 1 && <div className="single-history-pages"><button type="button" disabled={page === 0} onClick={() => setHistoryPage(page - 1)}>{t('single.previous_page')}</button>
            <span>{t('single.history_page', { current: page + 1, total: pageCount })}</span>
            <button type="button" disabled={page + 1 >= pageCount} onClick={() => setHistoryPage(page + 1)}>{t('single.next_page')}</button></div>}
        </div>}
      </div>
    </div>
    </div>
    <footer className="image-gen-bar row" aria-label={t('gen.execution')}>
      <div className="generation-summary grow"><strong>{t('gen.images', { n: 1 })}</strong>
        <GenerationResolution service={draft.service} value={settings} /></div>
      <button type="button" className="primary" disabled={busy || !ready || !positive} onClick={() => enqueue()}>{t('single.run')}</button>
      {busy && run && active(run) && <button type="button" onClick={cancel}>{t('common.cancel')}</button>}
    </footer>
    {previewOpen && run?.image_url && <GalleryDetailFrame imageUrl={run.image_url} label={`${t('single.result')} · ${filenameOf(run)}`} close={() => setPreviewOpen(false)}>
      <div className="row"><strong className="grow single-modal-name" title={filenameOf(run)}>{filenameOf(run)}</strong>
        <button type="button" className="ghost" aria-label={t('common.close')} onClick={() => setPreviewOpen(false)}>×</button></div>
      {run.path && <div className="faint mono small single-modal-path" title={run.path}>{run.path}</div>}
      <div className="faint small">{SERVICE_NAMES[run.service] ?? run.service} · {localTime(run.created_at)} · {t(`single.state.${run.status}`)}</div>
      {error && <div className="single-review" role="alert">{error}</div>}
      {resultDetails}
    </GalleryDetailFrame>}
  </section>;
}
