import { useQuery } from '@tanstack/react-query';
import { type ComponentType, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import { byGroup, fits, visibleFor, type Fragment } from '../../lib/fragments';
import type { ImageServices } from '../ImageServiceSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { SERVICE_NAMES, lastService, lastServiceSettings, rememberService, rememberServiceSettings, type ServicePanelProps } from './serviceSettings';

// Each internet service's settings panel (#42 NovelAI, #43 PixAI).
const SERVICE_PANELS: Record<string, ComponentType<ServicePanelProps>> = { novelai: NovelAISettings, pixai: PixAISettings };
import { useToast } from '../Toasts';
import RunLlmSelector, { type LlmOverride } from '../RunLlmSelector';
import GenSettings, { FAMILY_DEFAULTS, type GenerationSettings } from './GenSettings';
import { PRESET_HANDOFF } from '../../lib/presetHandoff';

type Design = { id: string; name: string; path: string; has_design: boolean; trigger?: string; default_outfit?: string; outfits: { id: string; name: string }[] };
type LibItem = { id: string; name: string; rating?: string; target?: string; default?: boolean; group?: string; targets?: string[] };
// A style preset (#169): settings and artist tags for one service (and, on ComfyUI, one model family).
export type Artist = { positive: string; negative: string };
type Preset = { id: string; name: string; service: string; family: string; tags: string[]; settings: GenerationSettings & Record<string, unknown>; common: string[]; artist: Artist };
type Composed = {
  character_id: string;
  outfit_name: string;
  expression_name: string;
  composition_name?: string | null;
  outfit_hidden?: boolean;
  parts: Record<string, string>;
  positive: string;
  negative: string;
  warnings: any[];
};
const PARTS = ['common', 'artist', 'composition', 'trigger', 'appearance', 'expression', 'outfit', 'negative'];

// Image menu → Generate: characters × outfits × expressions with the library, a preset and generation settings.
export type Target = { character_id: string; outfit_id: string; expression_id: string };
const HANDOFF_KEY = 'atelierx-generate-targets';

// The completeness board (#45) hands over exact combinations; an open generate tab takes them from the event, one opened
// later reads them from session storage.
export function sendToGenerate(targets: Target[]) {
  try {
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify(targets));
  } catch {
    // Storage may be unavailable; the event still reaches an open tab.
  }
  window.dispatchEvent(new CustomEvent(HANDOFF_KEY, { detail: targets }));
}

function takeHanded(): Target[] | null {
  try {
    const raw = sessionStorage.getItem(HANDOFF_KEY);
    sessionStorage.removeItem(HANDOFF_KEY);
    const list = raw ? JSON.parse(raw) : null;
    return Array.isArray(list) && list.length ? list : null;
  } catch {
    return null;
  }
}

export default function ImageGenerate({ workId, openQueue, openItem, openSettings, characterId, outfitId }: { workId: string; openQueue: () => void; openItem: (path: string) => void; openSettings?: () => void; characterId?: string; outfitId?: string }) {
  const toast = useToast();
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const lib = (kind: string) => ({ queryKey: ['image-lib', kind, workId], queryFn: () => get<Record<string, LibItem>>(`/api/image/library/${kind}?work=${workId}`) });
  const expressions = useQuery(lib('expressions'));
  const compositions = useQuery(lib('compositions'));
  const commons = useQuery(lib('common'));
  const rules = useQuery<{ ratings: { id: string; name: string }[] }>({ queryKey: ['image-lib-rules'], queryFn: () => get('/api/image/library/rules') });
  const presets = useQuery<Preset[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets') });
  const reviewSettings = useQuery<{ enabled: boolean }>({ queryKey: ['review-settings'], queryFn: () => get('/api/image/review/settings') });

  const [chars, setChars] = useState<Record<string, string[]>>({});
  const [exprs, setExprs] = useState<string[]>([]);
  const [composition, setComposition] = useState('');
  const [artist, setArtist] = useState<Artist>({ positive: '', negative: '' });
  const [commonIds, setCommonIds] = useState<string[] | null>(null);
  const [presetId, setPresetId] = useState('');
  const [settings, setSettings] = useState<GenerationSettings>({ family: 'anima', ...FAMILY_DEFAULTS.anima, seed: -1 });
  // Where the images are made (#41): ComfyUI on this PC or an internet service. Each keeps its own last settings.
  const services = useQuery<ImageServices>({ queryKey: ['image-services'], queryFn: () => get('/api/image/services') });
  const [service, setServiceState] = useState(() => lastService(workId));
  const [serviceSettings, setServiceSettings] = useState(lastServiceSettings);
  const internet = service !== 'comfyui';
  const serviceInfo = services.data?.services.find((s) => s.id === service);
  const chooseService = (id: string) => {
    setServiceState(id);
    rememberService(workId, id);
    // A style preset is made for one service.
    if (presets.data?.find((p) => p.id === presetId)?.service !== id) setPresetId('');
  };
  const changeServiceSettings = (value: Record<string, unknown>) => {
    const next = { ...serviceSettings, [service]: value };
    setServiceSettings(next);
    rememberServiceSettings(next);
  };
  const ServicePanel = SERVICE_PANELS[service];
  const [count, setCount] = useState(1);
  const [reviewLlm, setReviewLlm] = useState<LlmOverride | undefined>();
  const [preview, setPreview] = useState<Composed[] | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [showOthers, setShowOthers] = useState(false);
  const [scopeLoaded, setScopeLoaded] = useState(false);
  const [handed, setHanded] = useState<Target[] | null>(() => takeHanded());
  useEffect(() => {
    const take = (event: Event) => {
      takeHanded();
      setHanded((event as CustomEvent<Target[]>).detail);
    };
    window.addEventListener(HANDOFF_KEY, take);
    return () => window.removeEventListener(HANDOFF_KEY, take);
  }, []);
  useEffect(() => {
    if (!characterId || scopeLoaded || !designs.data) return;
    const design = designs.data.find((d) => d.id === characterId);
    if (design?.has_design) setChars({ [characterId]: [outfitId ?? design.default_outfit ?? design.outfits[0]?.id].filter(Boolean) });
    setScopeLoaded(true);
  }, [characterId, outfitId, designs.data, scopeLoaded]);

  const target = internet ? service : settings.family;
  // Common prompts on by default, of those written for this target (#80): switching service changes the defaults.
  const commonDefault = useMemo(() => Object.values(commons.data ?? {}).filter((c) => c.default !== false && fits(c, target)).map((c) => c.id), [commons.data, target]);
  const chosenCommons = commonIds ?? commonDefault;
  const targets = useMemo(
    () =>
      handed ??
      Object.entries(chars).flatMap(([character_id, outfits]) =>
        outfits.flatMap((outfit_id) => exprs.map((expression_id) => ({ character_id, outfit_id, expression_id }))),
      ),
    [chars, exprs, handed],
  );
  const single = targets.length === 1;
  const options = () => ({
    targets,
    service,
    artist,
    common_ids: chosenCommons,
    composition_id: composition || undefined,
    preset_id: presetId || undefined,
    settings: internet ? (serviceSettings[service] ?? {}) : settings,
    overrides: single ? overrides : {},
  });

  useEffect(() => setPreview(null), [chars, exprs, composition, artist, commonIds, settings, handed, service, serviceSettings]);

  function applyPreset(id: string) {
    setPresetId(id);
    const preset = presets.data?.find((p) => p.id === id);
    if (!preset) return;
    // A preset sent from the style preset screen may be for another service: switch to it.
    if (preset.service !== service) {
      setServiceState(preset.service);
      rememberService(workId, preset.service);
    }
    if (preset.service === 'comfyui') setSettings({ ...preset.settings, family: preset.family as 'anima' | 'sdxl', seed: preset.settings.seed ?? -1 });
    else {
      const next = { ...serviceSettings, [preset.service]: { ...(serviceSettings[preset.service] ?? {}), ...preset.settings } };
      setServiceSettings(next);
      rememberServiceSettings(next);
    }
    if (preset.common.length) setCommonIds(preset.common);
    setArtist(preset.artist);
  }
  const servicePresets = (presets.data ?? []).filter((p) => p.service === service);
  // A preset sent from the style preset screen: read on opening, or announced when this screen is already open.
  const applyLatest = useRef(applyPreset);
  applyLatest.current = applyPreset;
  useEffect(() => {
    const handed = sessionStorage.getItem(PRESET_HANDOFF);
    if (!handed || !presets.data) return;
    sessionStorage.removeItem(PRESET_HANDOFF);
    applyLatest.current(handed);
  }, [presets.data]);
  useEffect(() => {
    const take = (event: Event) => {
      sessionStorage.removeItem(PRESET_HANDOFF);
      applyLatest.current((event as CustomEvent<string>).detail);
    };
    window.addEventListener(PRESET_HANDOFF, take);
    return () => window.removeEventListener(PRESET_HANDOFF, take);
  }, []);

  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const toggle = (list: string[], id: string, on: boolean) => (on ? [...new Set([...list, id])] : list.filter((x) => x !== id));
  const notApplied = (item: Fragment) => (fits(item, target) ? null : <span className="warn-text small"> ({t('gen.not_applied')})</span>);
  const commonView = visibleFor(Object.values(commons.data ?? {}), target, chosenCommons, showOthers);
  const hiddenCount = commonView.hidden;
  const byRating = (rules.data?.ratings ?? []).map((r) => ({ ...r, items: Object.values(expressions.data ?? {}).filter((e) => e.rating === r.id) }));

  return (
    <div className="image-gen">
      <div className="image-gen-pick pad col">
        {handed && (
          <div className="col handed-targets">
            <div className="section-title">{t('gen.handed', { n: handed.length })}</div>
            <div className="mono small faint" style={{ maxHeight: 160, overflow: 'auto', whiteSpace: 'pre-line' }}>
              {handed.map((x) => `${x.character_id} · ${x.outfit_id} · ${x.expression_id}`).join('\n')}
            </div>
            <button onClick={() => setHanded(null)}>{t('gen.handed_clear')}</button>
          </div>
        )}
        <div className="col" hidden={!!handed}>
        <div className="section-title">{t('gen.characters')}</div>
        {(designs.data ?? []).length === 0 && <div className="faint">{t('gen.no_characters')}</div>}
        {(designs.data ?? []).map((d) => (
          <div key={d.id} className="col gen-char">
            <label className="row" style={{ gap: 4 }}>
              <input
                type="checkbox"
                disabled={!d.has_design}
                checked={!!chars[d.id]}
                onChange={(e) => {
                  const next = { ...chars };
                  if (e.target.checked) next[d.id] = [d.default_outfit ?? d.outfits[0]?.id].filter(Boolean) as string[];
                  else delete next[d.id];
                  setChars(next);
                }}
              />
              <strong>{d.name}</strong> <span className="faint mono">{d.id}</span>
              {!d.has_design && (
                <a href="#" onClick={(e) => (e.preventDefault(), openItem(d.path))} className="faint">
                  {t('gen.no_design')}
                </a>
              )}
            </label>
            {chars[d.id] && (
              <div className="row" style={{ flexWrap: 'wrap', paddingLeft: 20 }}>
                {d.outfits.map((o) => (
                  <label key={o.id} className="row" style={{ gap: 4 }}>
                    <input type="checkbox" checked={chars[d.id].includes(o.id)} onChange={(e) => setChars({ ...chars, [d.id]: toggle(chars[d.id], o.id, e.target.checked) })} />
                    {o.name}
                  </label>
                ))}
              </div>
            )}
          </div>
        ))}
        <div className="section-title">{t('gen.expressions')}</div>
        {byRating.map((group) => (
          <div key={group.id} className="col" style={{ gap: 2 }}>
            <label className="row faint" style={{ gap: 4 }}>
              <input
                type="checkbox"
                checked={group.items.length > 0 && group.items.every((e) => exprs.includes(e.id))}
                onChange={(e) => setExprs(e.target.checked ? [...new Set([...exprs, ...group.items.map((x) => x.id)])] : exprs.filter((x) => !group.items.some((i) => i.id === x)))}
              />
              {group.name}
            </label>
            <div className="row" style={{ flexWrap: 'wrap', paddingLeft: 20 }}>
              {group.items.map((e) => (
                <label key={e.id} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={exprs.includes(e.id)} onChange={(ev) => setExprs(toggle(exprs, e.id, ev.target.checked))} />
                  {e.name}
                </label>
              ))}
            </div>
          </div>
        ))}
        </div>
        <div className="section-title">{t('gen.extras')}</div>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lib.composition')}</span>
          <select value={composition} onChange={(e) => setComposition(e.target.value)}>
            <option value="">{t('gen.composition_auto')}</option>
            {Object.values(compositions.data ?? {}).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {fits(c, target) ? '' : ` (${t('gen.not_applied')})`}
              </option>
            ))}
          </select>
        </label>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('gen.artist')}</span>
          <textarea rows={2} value={artist.positive} placeholder={t('gen.artist_hint')} onChange={(e) => setArtist({ ...artist, positive: e.target.value })} />
        </label>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('gen.artist_negative')}</span>
          <textarea rows={1} value={artist.negative} onChange={(e) => setArtist({ ...artist, negative: e.target.value })} />
        </label>
        <div className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lib.kind.common')}</span>
          {byGroup(commonView.shown).map(({ group, items }) => (
            <div key={group || '-'} className="row" style={{ flexWrap: 'wrap' }}>
              {group && <span className="faint small lib-group-inline">{group}</span>}
              {items.map((c) => (
                <label key={c.id} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={chosenCommons.includes(c.id)} onChange={(e) => setCommonIds(toggle(chosenCommons, c.id, e.target.checked))} />
                  {c.name}
                  {c.target === 'negative' && <span className="faint">(−)</span>}
                  {notApplied(c)}
                </label>
              ))}
            </div>
          ))}
        </div>
        {(hiddenCount > 0 || showOthers) && (
          <button className="ghost small" style={{ alignSelf: 'flex-start' }} onClick={() => setShowOthers(!showOthers)}>
            {showOthers ? t('gen.hide_other_targets') : t('gen.other_targets', { n: hiddenCount })}
          </button>
        )}
      </div>
      <div className="image-gen-run pad col">
        <div className="row">
          <span className="muted">{t('gen.service')}</span>
          <div className="service-switch" role="radiogroup" aria-label={t('gen.service')}>
            <button role="radio" aria-checked={!internet} className={internet ? '' : 'on'} onClick={() => chooseService('comfyui')}>
              {SERVICE_NAMES.comfyui}
            </button>
            {(services.data?.services ?? []).map((s) => (
              <button
                key={s.id}
                role="radio"
                aria-checked={service === s.id}
                className={service === s.id ? 'on' : ''}
                disabled={!s.supported}
                title={!s.supported ? t('image_services.not_supported') : s.connected ? undefined : t('gen.service_needs_key')}
                onClick={() => chooseService(s.id)}
              >
                {s.name}
              </button>
            ))}
          </div>
        </div>
        {internet && serviceInfo && !serviceInfo.connected && (
          <div className="warn-text row">
            {t('gen.service_needs_key')}
            {openSettings && <button className="ghost small" onClick={openSettings}>{t('gen.open_settings')}</button>}
          </div>
        )}
        <div className="row">
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('gen.preset')}</span>
            <select value={presetId} onChange={(e) => applyPreset(e.target.value)}>
              <option value="">{t('gen.no_preset')}</option>
              {servicePresets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.service === 'comfyui' ? ` · ${p.family === 'sdxl' ? 'SDXL·IL' : 'Anima'}` : ''}
                  {p.tags.length ? ` · ${p.tags.join(', ')}` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
        {!internet && <GenSettings value={settings} onChange={setSettings} />}
        {internet && (ServicePanel ? <ServicePanel value={serviceSettings[service] ?? {}} onChange={changeServiceSettings} /> : <p className="faint">{t('gen.service_no_settings')}</p>)}
        {internet && <p className="faint small">{t('gen.service_no_lora')}</p>}
        {reviewSettings.data?.enabled && <RunLlmSelector task="image_review" value={reviewLlm} onChange={setReviewLlm} />}
        <div className="row" style={{ alignItems: 'flex-end' }}>
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('gen.count')}</span>
            <input type="number" min={1} max={50} style={{ width: 72 }} value={count} onChange={(e) => setCount(Number(e.target.value))} />
          </label>
          <span className="grow faint">
            {t('gen.total', { targets: targets.length, n: targets.length * count })}
            {internet && services.data && (services.data.max_images_per_run ? ` · ${t('gen.limit', { limit: services.data.max_images_per_run })}` : ` · ${t('gen.no_limit')}`)}
          </span>
          <button
            disabled={!targets.length || busy}
            onClick={async () => {
              try {
                setPreview(await post(`/api/works/${workId}/image/compose`, options()));
              } catch (err) {
                fail(err);
              }
            }}
          >
            {t('gen.preview')}
          </button>
          <button
            className="primary"
            disabled={!targets.length || busy || (internet && !serviceInfo?.connected)}
            onClick={async () => {
              if (internet && !confirm(t('gen.confirm_internet', { n: targets.length * count, service: serviceInfo?.name ?? service }))) return;
              setBusy(true);
              try {
                const request = {
                  ...options(),
                  count,
                  ...(reviewSettings.data?.enabled ? { llm: reviewLlm } : {}),
                };
                let result;
                try {
                  result = await post(`/api/works/${workId}/image/jobs`, request);
                } catch (err) {
                  // The same request went to a paid service a moment ago (#42): ask before sending it again.
                  if (!(err instanceof ApiError && err.msg.key === 'server.image.services.repeat') || !confirm(tm(err.msg))) throw err;
                  result = await post(`/api/works/${workId}/image/jobs`, { ...request, repeat_ok: true });
                }
                toast({ text: t('gen.queued', { n: result.count }), action: { label: t('image_menu.queue'), run: openQueue } });
                setHanded(null); // the board's combinations are queued now; queuing them again would double them
              } catch (err) {
                fail(err);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t('gen.enqueue')}
          </button>
        </div>
        {preview && (
          <div className="col">
            {preview.map((p, n) => (
              <div key={n} className="compose-card">
                <div className="row">
                  <strong>
                    {p.character_id} · {p.outfit_name} · {p.expression_name}
                  </strong>
                  {p.outfit_hidden && <span className="chip small">{t('gen.outfit_hidden', { name: p.composition_name ?? '' })}</span>}
                </div>
                {p.warnings.map((w, i) => (
                  <div key={i} className="warn-text">
                    {tm(w)}
                  </div>
                ))}
                {single ? (
                  PARTS.map((part) => (
                    <label key={part} className="row compose-part">
                      <span className="faint">{t(`gen.part.${part}`)}</span>
                      <textarea
                        rows={part === 'negative' || part === 'appearance' ? 2 : 1}
                        value={overrides[part] ?? p.parts[part] ?? ''}
                        onChange={(e) => setOverrides({ ...overrides, [part]: e.target.value })}
                      />
                    </label>
                  ))
                ) : (
                  <>
                    <div className="mono small">{p.positive}</div>
                    <div className="mono small faint">− {p.negative}</div>
                  </>
                )}
              </div>
            ))}
            {targets.length > preview.length && <div className="faint">{t('gen.more', { n: targets.length - preview.length })}</div>}
          </div>
        )}
      </div>
    </div>
  );
}
