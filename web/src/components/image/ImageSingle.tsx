import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm, msgText } from '../../i18n';
import type { ImageView } from '../../types';
import type { SingleRun, SingleRuns } from '../../imageTypes';
import { useUnsaved } from '../Unsaved';
import type { ImageServices } from '../ImageServiceSettings';
import GenSettings, { FAMILY_DEFAULTS, useCatalog, type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { SERVICE_NAMES } from './serviceSettings';
import { sendToLab } from './ImageLab';
import { sendToTools } from '../../lib/toolHandoff';
import './ImageSingle.css';

type Service = 'comfyui' | 'novelai' | 'pixai';
type Draft = { positive: string; negative: string; service: Service; settings: Record<Service, Record<string, unknown>>; preset: string };
type Preset = { id: string; name: string; service: string; family: string; settings: Record<string, unknown>; common?: string[]; artist?: { positive?: string; negative?: string } };
type Common = { prompt?: string[]; target?: string; targets?: string[] };
const storageKey = (work: string) => `atelierx-single-v2-${work}`;
const fresh = (): Draft => ({ positive: '', negative: '', service: 'comfyui', preset: '', settings: {
  comfyui: { family: 'anima', ...FAMILY_DEFAULTS.anima, seed: -1 }, novelai: {}, pixai: {},
} });
function readDraft(work: string): Draft {
  const fallback = fresh();
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey(work)) || 'null') as Draft | null;
    if (!saved || typeof saved.positive !== 'string' || typeof saved.negative !== 'string' || !['comfyui', 'novelai', 'pixai'].includes(saved.service)) return fallback;
    return { ...fallback, positive: saved.positive, negative: saved.negative, service: saved.service,
      preset: typeof saved.preset === 'string' ? saved.preset : '',
      settings: Object.fromEntries(Object.entries(fallback.settings).map(([key, value]) => [key, { ...value, ...saved.settings?.[key as Service] }])) as Draft['settings'] };
  } catch { return fallback; }
}
const clone = (draft: Draft): Draft => JSON.parse(JSON.stringify(draft));
const active = (run: SingleRun | undefined) => !!run && ['queued', 'running', 'cancelling'].includes(run.status);
const withoutNote = (value: string) => {
  const note = /(^|[\s,])#/.exec(value);
  return (note ? value.slice(0, note.index) : value).replaceAll('\\#', '#').trim();
};
const promptText = (value: string) => value.split(/\r?\n/).map(line => withoutNote(line)).filter(Boolean).join('\n');

export default function ImageSingle({ workId, openView }: { workId: string; openView: (view: ImageView) => void }) {
  const id = useId();
  const qc = useQueryClient();
  const [draft, setDraft] = useState(() => readDraft(workId));
  const [stored, setStored] = useState('');
  const [storageFailed, setStorageFailed] = useState(false);
  const [pending, setPending] = useState(false);
  const [runId, setRunId] = useState('');
  const [error, setError] = useState('');
  const [destination, setDestination] = useState<'tools' | 'lab' | null>(null);
  const services = useQuery<ImageServices>({ queryKey: ['image-services'], queryFn: () => get('/api/image/services') });
  const catalog = useCatalog();
  const presets = useQuery<Preset[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets') });
  const commons = useQuery<Record<string, Common>>({ queryKey: ['image-lib', 'common', workId], queryFn: () => get(`/api/image/library/common?work=${workId}`) });
  const runs = useQuery<SingleRuns>({ queryKey: ['image-single-runs', workId], queryFn: () => get(`/api/works/${workId}/image/single/runs`), refetchInterval: 1500 });
  const run = runs.data?.runs.find(r => r.id === runId) ?? runs.data?.runs[0];
  const busy = pending || active(run);
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
  const chosenPreset = servicePresets.find(preset => preset.id === draft.preset);
  const selectedCommon = (chosenPreset?.common ?? []).map(key => commons.data?.[key]).filter((item): item is Common => !!item);
  const commonTags = (target: string) => selectedCommon.filter(item => (item.target === 'negative' ? 'negative' : 'positive') === target)
    .flatMap(item => item.prompt ?? []).map(withoutNote).filter((tag, index, tags) => !!tag && tags.indexOf(tag) === index);
  const positive = [...commonTags('positive'), promptText(draft.positive), promptText(chosenPreset?.artist?.positive ?? '')].filter(Boolean).join(', ');
  const negative = [...commonTags('negative'), promptText(draft.negative), promptText(chosenPreset?.artist?.negative ?? '')].filter(Boolean).join(', ');
  const fail = (err: unknown) => setError(err instanceof ApiError ? tm(err.msg) : String(err));
  const refresh = () => qc.invalidateQueries({ queryKey: ['image-single-runs', workId] });
  async function enqueue(value = draft, repeatOk = false) {
    if (busy || !value.positive.trim()) return;
    setPending(true); setError(''); setDestination(null);
    try {
      const request = {
        positive: value.positive, negative: value.negative, service: value.service,
        preset_id: value.preset || undefined, settings: value.settings[value.service], repeat_ok: repeatOk,
      };
      let response: { job_id: string };
      try { response = await post(`/api/works/${workId}/image/single`, request); }
      catch (err) {
        if (!(err instanceof ApiError && err.msg.key === 'server.image.services.repeat' && confirm(tm(err.msg)))) throw err;
        response = await post(`/api/works/${workId}/image/single`, { ...request, repeat_ok: true });
      }
      setRunId(response.job_id);
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
    if (!run) return;
    setPending(true); setError('');
    try {
      const response = await post<{ job_id: string }>(`/api/image/jobs/${run.id}/retry`);
      setRunId(response.job_id);
      await post('/api/image/queue/resume');
      await refresh();
    } catch (err) { fail(err); }
    finally { setPending(false); }
  }
  function restore(selected: SingleRun) {
    if (!selected.actual) return;
    setDraft(current => ({ ...current, positive: selected.actual.positive, negative: selected.actual.negative,
      service: selected.service, preset: '',
      settings: { ...current.settings, [selected.service]: { ...selected.actual.settings, seed: selected.seed } },
    }));
  }
  async function regenerate() {
    if (!run?.actual) return;
    const value = clone(draft);
    value.positive = run.actual.positive; value.negative = run.actual.negative; value.service = run.service; value.preset = '';
    value.settings[run.service] = { ...run.actual.settings, seed: run.seed };
    setDraft(value);
    await enqueue(value, true);
  }
  async function handoffTools() {
    if (!run?.path) return;
    try {
      const response = await post<{ items: { id: string }[] }>('/api/image/tools/gallery', { paths: [run.path] });
      const item = response.items[0];
      if (!item) throw new Error(t('single.handoff_failed'));
      sendToTools(item.id);
      openView('tools');
    } catch (err) { fail(err); }
  }
  function handoffLab() {
    if (!run?.actual || !run.path || run.service !== 'comfyui') return;
    sendToLab({ positive: run.actual.positive, negative: run.actual.negative,
      settings: { ...run.actual.settings, seed: run.seed } as GenerationSettings, source: run.path });
    openView('lab');
  }
  return <section className="single-image" aria-label={t('image_menu.single')}>
    <header className="single-heading"><div><h2>{t('image_menu.single')}</h2><span className="faint">{t('single.subtitle')}</span></div>
      <div className="seg" aria-label={t('single.mode')}><button type="button" className="on" aria-pressed="true">{t('single.general')}</button><button type="button" disabled>{t('single.multi')}</button></div>
    </header>
    <div className="single-layout">
      <div className="single-form">
        <div className="single-service" role="group" aria-label={t('gen.service')}>
          {(['comfyui', 'novelai', 'pixai'] as Service[]).map(service => <button type="button" key={service} className={draft.service === service ? 'primary' : ''} aria-pressed={draft.service === service} onClick={() => update({ service, preset: '' })}>{SERVICE_NAMES[service]}</button>)}
        </div>
        {!ready && <p className="warn-text" role="alert">{draft.service === 'comfyui' ? t('gen.not_connected') : t('single.service_unavailable')}</p>}
        <label className="single-field"><span>{t('single.preset')}</span><select value={draft.preset} onChange={e => {
          const preset = servicePresets.find(p => p.id === e.target.value);
          setDraft(current => ({ ...current, preset: e.target.value,
            settings: preset ? { ...current.settings, [current.service]: { ...current.settings[current.service], ...preset.settings } } : current.settings }));
        }}>
          <option value="">{t('gen.no_preset')}</option>{servicePresets.map(preset => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
        </select></label>
        <label className="single-field" htmlFor={`${id}-positive`}><span>{t('single.positive')}</span><textarea id={`${id}-positive`} rows={6} value={draft.positive} placeholder={t('single.positive_hint')} onChange={e => update({ positive: e.target.value })} /></label>
        <label className="single-field" htmlFor={`${id}-negative`}><span>{t('single.negative')}</span><textarea id={`${id}-negative`} rows={3} value={draft.negative} placeholder={t('single.negative_hint')} onChange={e => update({ negative: e.target.value })} /></label>
        <div className="single-helpers"><button type="button" onClick={() => update({ positive: [draft.positive, 'a quiet lakeside, distant mountains, morning light'].filter(Boolean).join(', ') })}>{t('single.add_sample')}</button><span className="faint small">{t('single.sample_hint')}</span></div>
        <details className="single-details"><summary>{t('single.final_prompt')}</summary><h4>Positive</h4><pre>{positive || '—'}</pre><h4>Negative</h4><pre>{negative || '—'}</pre><p className="faint small">{t('single.final_note')}</p></details>
        <details className="single-details" open><summary>{t('single.settings')}</summary><p className="faint small">{t('single.settings_hint')}</p>
          {draft.service === 'comfyui' && <GenSettings value={settings as GenerationSettings} onChange={value => setSettings(value)} />}
          {draft.service === 'novelai' && <NovelAISettings value={settings} onChange={setSettings} />}
          {draft.service === 'pixai' && <PixAISettings value={settings} onChange={setSettings} />}
        </details>
        {storageFailed ? <p role="alert" className="warn-text">{t('single.storage_failed')} <button onClick={saveDraft}>{t('common.save')}</button></p> : <p className="faint small">{t('single.local_draft')}</p>}
        <div className="single-run"><button type="button" className="primary" disabled={busy || !ready || !draft.positive.trim()} onClick={() => enqueue()}>{t('single.run')}</button>
          {busy && run && active(run) && <button type="button" onClick={cancel}>{t('common.cancel')}</button>}
        </div>
      </div>
      <div className="single-result">
        <div className="single-result-head"><h3>{t('single.result')}</h3><span role="status" aria-live="polite">{t(`single.state.${pending && !run ? 'queued' : run?.status ?? 'idle'}`)}</span></div>
        {error && <div className="single-review" role="alert">{error}</div>}
        {run?.error && <div className="single-review" role="alert">{msgText(run.error)}</div>}
        {run && ['failed', 'cancelled', 'interrupted'].includes(run.status) && <button type="button" disabled={pending} onClick={retry}>{t('single.retry')}</button>}
        {busy && <progress aria-label={t('single.progress')} />}
        <div className="single-canvas">{run?.image_url ? <img src={run.image_url} alt={t('single.result')} /> : <div className="single-empty">{t('single.empty')}</div>}</div>
        {run && <>
          <p className="faint small">{SERVICE_NAMES[run.service] ?? run.service} · Seed {run.seed}</p>
          <div className="single-result-actions"><button type="button" disabled={busy || !run.actual} onClick={() => restore(run)}>{t('single.restore')}</button><button type="button" disabled={busy || !run.actual} onClick={regenerate}>{t('single.regenerate')}</button><button type="button" disabled={!run.path} onClick={() => setDestination('tools')}>{t('single.send_tools')}</button><button type="button" disabled={!run.path || run.service !== 'comfyui'} title={run.service !== 'comfyui' ? t('single.compare_comfy_only') : undefined} onClick={() => setDestination('lab')}>{t('single.compare')}</button></div>
          <details className="single-details"><summary>{t('single.result_settings')}</summary><pre>{JSON.stringify(run.actual, null, 2)}</pre></details>
        </>}
        {destination && <section className="single-handoff" aria-label={t('single.handoff')}><h4>{t(`image_menu.${destination}`)}</h4><p>{t('single.handoff_note')}</p><button type="button" onClick={destination === 'tools' ? handoffTools : handoffLab}>{t('single.open_existing')}</button><button type="button" onClick={() => setDestination(null)}>{t('common.close')}</button></section>}
        <div className="single-result-links"><button type="button" className="ghost" onClick={() => openView('gallery')}>{t('image_menu.gallery')}</button><button type="button" className="ghost" onClick={() => openView('queue')}>{t('image_menu.queue')}</button></div>
        {(runs.data?.runs.length ?? 0) > 1 && <div className="single-history"><h4>{t('single.history')}</h4>{runs.data!.runs.map(entry => <button key={entry.id} type="button" className={run?.id === entry.id ? 'on' : ''} onClick={() => { setRunId(entry.id); setDestination(null); }}>{entry.image_url ? <img src={entry.image_url} alt="" /> : null}<span>{entry.created_at} · {t(`single.state.${entry.status}`)}</span></button>)}</div>}
      </div>
    </div>
  </section>;
}
