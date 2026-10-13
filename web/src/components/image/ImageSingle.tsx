import { useEffect, useId, useState } from 'react';
import { t } from '../../i18n';
import type { ImageView } from '../../types';
import { useUnsaved } from '../Unsaved';
import GenSettings, { type GenerationSettings } from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { SERVICE_NAMES } from './serviceSettings';
import { COMFY_PREVIEW_DEFAULTS, NOVELAI_PREVIEW_DEFAULTS, PIXAI_PREVIEW_DEFAULTS } from './singlePreviewSettings';
import './ImageSingle.css';

type Service = 'comfyui' | 'novelai' | 'pixai';
type Draft = { positive: string; negative: string; service: Service; settings: Record<Service, Record<string, unknown>>; preset: string };
type Result = { draft: Draft; seed: number };
type State = 'idle' | 'queued' | 'running' | 'done' | 'cancelled' | 'failed';
const storageKey = (work: string) => `atelierx-single-ui-v1-${work}`;
const fresh = (): Draft => ({ positive: '', negative: '', service: 'comfyui', preset: '', settings: {
  comfyui: { ...COMFY_PREVIEW_DEFAULTS }, novelai: { ...NOVELAI_PREVIEW_DEFAULTS }, pixai: { ...PIXAI_PREVIEW_DEFAULTS },
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

// UI review only: all settings use local fixtures, and generation never calls an API.
export default function ImageSingle({ workId, openView }: { workId: string; openView: (view: ImageView) => void }) {
  const id = useId();
  const [draft, setDraft] = useState(() => readDraft(workId));
  const [stored, setStored] = useState('');
  const [storageFailed, setStorageFailed] = useState(false);
  const [state, setState] = useState<State>('idle');
  const [request, setRequest] = useState<Draft | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [failNext, setFailNext] = useState(false);
  const [requestFails, setRequestFails] = useState(false);
  const [destination, setDestination] = useState<'tools' | 'lab' | null>(null);
  const busy = state === 'queued' || state === 'running';
  const serialized = JSON.stringify(draft);
  function saveDraft(): boolean {
    try { localStorage.setItem(storageKey(workId), serialized); setStored(serialized); setStorageFailed(false); return true; }
    catch { setStorageFailed(true); return false; }
  }
  useEffect(() => { saveDraft(); }, [serialized, workId]);
  useUnsaved('single-ui-draft', stored !== serialized || busy, async () => saveDraft() && !busy);
  useEffect(() => {
    if (!busy || !request) return;
    const timer = window.setTimeout(() => {
      if (state === 'queued') setState('running');
      else if (requestFails) setState('failed');
      else {
        const requestedSeed = Number(request.settings[request.service].seed ?? -1);
        setResult({ draft: clone(request), seed: requestedSeed >= 0 ? requestedSeed : Math.floor(Math.random() * 2147483647) });
        setState('done');
      }
    }, state === 'queued' ? 450 : 1200);
    return () => window.clearTimeout(timer);
  }, [state, request, requestFails, busy]);
  const update = (patch: Partial<Draft>) => setDraft(current => ({ ...current, ...patch }));
  const settings = draft.settings[draft.service];
  const setSettings = (value: Record<string, unknown>) => setDraft(current => ({ ...current, settings: { ...current.settings, [current.service]: value } }));
  const presetTags = draft.preset === 'soft' ? 'soft lighting, pastel colors' : draft.preset === 'ink' ? 'ink drawing, monochrome' : '';
  const positive = [draft.positive.trim(), presetTags].filter(Boolean).join(', ');
  function run(value = draft) {
    if (busy || !value.positive.trim()) return;
    setRequest(clone(value)); setRequestFails(failNext); setDestination(null); setState('queued');
  }
  function restore() {
    if (!result) return;
    const restored = clone(result.draft);
    restored.settings[restored.service].seed = result.seed;
    setDraft(restored);
  }
  return <section className="single-image" aria-label={t('image_menu.single')}>
    <div className="single-review" role="note"><strong>{t('single.review')}</strong><span>{t('single.review_detail')}</span></div>
    <header className="single-heading"><div><h2>{t('image_menu.single')}</h2><span className="faint">{t('single.subtitle')}</span></div>
      <div className="seg" aria-label={t('single.mode')}><button type="button" className="on" aria-pressed="true">{t('single.general')}</button><button type="button" disabled>{t('single.multi')}</button></div>
    </header>
    <div className="single-layout">
      <div className="single-form">
        <div className="single-service" role="group" aria-label={t('gen.service')}>
          {(['comfyui', 'novelai', 'pixai'] as Service[]).map(service => <button type="button" key={service} className={draft.service === service ? 'primary' : ''} aria-pressed={draft.service === service} onClick={() => update({ service })}>{SERVICE_NAMES[service]}</button>)}
        </div>
        <label className="single-field"><span>{t('single.preset')}</span><select value={draft.preset} onChange={e => update({ preset: e.target.value })}>
          <option value="">{t('gen.no_preset')}</option><option value="soft">{t('single.preset_soft')}</option><option value="ink">{t('single.preset_ink')}</option>
        </select></label>
        <label className="single-field" htmlFor={`${id}-positive`}><span>{t('single.positive')}</span><textarea id={`${id}-positive`} rows={6} value={draft.positive} placeholder={t('single.positive_hint')} onChange={e => update({ positive: e.target.value })} /></label>
        <label className="single-field" htmlFor={`${id}-negative`}><span>{t('single.negative')}</span><textarea id={`${id}-negative`} rows={3} value={draft.negative} placeholder={t('single.negative_hint')} onChange={e => update({ negative: e.target.value })} /></label>
        <div className="single-helpers"><button type="button" onClick={() => update({ positive: [draft.positive, 'a quiet lakeside, distant mountains, morning light'].filter(Boolean).join(', ') })}>{t('single.add_sample')}</button><span className="faint small">{t('single.sample_hint')}</span></div>
        <details className="single-details"><summary>{t('single.final_prompt')}</summary><h4>Positive</h4><pre>{positive || '—'}</pre><h4>Negative</h4><pre>{draft.negative || '—'}</pre><p className="faint small">{t('single.final_note')}</p></details>
        <details className="single-details" open><summary>{t('single.settings')}</summary><p className="faint small">{t('single.settings_hint')}</p>
          {draft.service === 'comfyui' && <GenSettings preview value={settings as GenerationSettings} onChange={value => setSettings(value)} />}
          {draft.service === 'novelai' && <NovelAISettings preview value={settings} onChange={setSettings} />}
          {draft.service === 'pixai' && <PixAISettings preview value={settings} onChange={setSettings} />}
        </details>
        {storageFailed ? <p role="alert" className="warn-text">{t('single.storage_failed')} <button onClick={saveDraft}>{t('common.save')}</button></p> : <p className="faint small">{t('single.local_draft')}</p>}
        <div className="single-run"><label><input type="checkbox" checked={failNext} onChange={e => setFailNext(e.target.checked)} /> {t('single.try_failure')}</label>
          <button type="button" className="primary" disabled={busy || !draft.positive.trim()} onClick={() => run()}>{t('single.run')}</button>
          {busy && <button type="button" onClick={() => setState('cancelled')}>{t('common.cancel')}</button>}
        </div>
      </div>
      <div className="single-result">
        <div className="single-result-head"><h3>{t('single.result')}</h3><span role="status" aria-live="polite">{t(`single.state.${state}`)}</span></div>
        {state === 'failed' && <div className="single-review" role="alert">{t('single.failed')}<button type="button" onClick={() => { setRequestFails(false); setState('queued'); }}>{t('single.retry')}</button></div>}
        {busy && <progress aria-label={t('single.progress')} />}
        <div className="single-canvas">
          {result ? <><svg viewBox="0 0 640 420" role="img" aria-label={t('single.sample_alt')}><rect width="640" height="420" fill="#e2edf1" /><circle cx="468" cy="106" r="43" fill="#e7c77c" /><path d="M0 265 170 110 320 275 455 160 640 278V420H0Z" fill="#7f999b" /><path d="M0 305 218 182 410 322 540 237 640 314V420H0Z" fill="#506e72" /><path d="M0 333Q320 299 640 333V420H0Z" fill="#bacfd2" /></svg><span className="single-watermark">{t('single.sample_label')}</span></> : <div className="single-empty">{t('single.empty')}</div>}
        </div>
        {result && <>
          <p className="faint small">{SERVICE_NAMES[result.draft.service]} · Seed {result.seed} · {t('single.not_generated')}</p>
          <div className="single-result-actions"><button type="button" disabled={busy} onClick={restore}>{t('single.restore')}</button><button type="button" disabled={busy} onClick={() => { const value = clone(result.draft); value.settings[value.service].seed = result.seed; setDraft(value); run(value); }}>{t('single.regenerate')}</button><button type="button" onClick={() => setDestination('tools')}>{t('single.send_tools')}</button><button type="button" onClick={() => setDestination('lab')}>{t('single.compare')}</button></div>
          <details className="single-details"><summary>{t('single.result_settings')}</summary><pre>{JSON.stringify(result.draft, null, 2)}</pre></details>
        </>}
        {destination && <section className="single-handoff" aria-label={t('single.handoff')}><h4>{t(`image_menu.${destination}`)}</h4><p>{t('single.handoff_note')}</p><button type="button" onClick={() => openView(destination)}>{t('single.open_existing')}</button><button type="button" onClick={() => setDestination(null)}>{t('common.close')}</button></section>}
        <div className="single-result-links"><button type="button" className="ghost" onClick={() => openView('gallery')}>{t('image_menu.gallery')}</button><button type="button" className="ghost" onClick={() => openView('queue')}>{t('image_menu.queue')}</button></div>
      </div>
    </div>
  </section>;
}
