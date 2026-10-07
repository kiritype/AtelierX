import { useQuery } from '@tanstack/react-query';
import { type ComponentType, useEffect, useMemo, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { Dialog } from '../ui';
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

type Design = { id: string; name: string; path: string; has_design: boolean; trigger?: string; default_outfit?: string; outfits: { id: string; name: string }[] };
type LibItem = { id: string; name: string; rating?: string; target?: string; default?: boolean; group?: string; targets?: string[] };
type Preset = { id: string; name: string; family: 'anima' | 'sdxl'; settings: GenerationSettings; common: string[]; styles: string[] };
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
const PARTS = ['common', 'style', 'composition', 'trigger', 'appearance', 'expression', 'outfit', 'negative'];

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

// What check-nodes reports (#178): a sampler, scheduler or model patch ComfyUI lacks, and the pack that has it.
type MissingNode = {
  kind: 'sampler' | 'scheduler' | 'patch';
  name: string;
  pack?: { id: string; repo?: string | null; license?: string | null; installable: boolean; note?: string | null } | null;
};

export default function ImageGenerate({ workId, openQueue, openItem, openSettings, characterId, outfitId }: { workId: string; openQueue: () => void; openItem: (path: string) => void; openSettings?: () => void; characterId?: string; outfitId?: string }) {
  const toast = useToast();
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const lib = (kind: string) => ({ queryKey: ['image-lib', kind, workId], queryFn: () => get<Record<string, LibItem>>(`/api/image/library/${kind}?work=${workId}`) });
  const expressions = useQuery(lib('expressions'));
  const compositions = useQuery(lib('compositions'));
  const styles = useQuery(lib('styles'));
  const commons = useQuery(lib('common'));
  const rules = useQuery<{ ratings: { id: string; name: string }[] }>({ queryKey: ['image-lib-rules'], queryFn: () => get('/api/image/library/rules') });
  const presets = useQuery<Preset[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets') });
  const reviewSettings = useQuery<{ enabled: boolean }>({ queryKey: ['review-settings'], queryFn: () => get('/api/image/review/settings') });

  const [chars, setChars] = useState<Record<string, string[]>>({});
  const [exprs, setExprs] = useState<string[]>([]);
  const [composition, setComposition] = useState('');
  const [styleIds, setStyleIds] = useState<string[]>([]);
  const [commonIds, setCommonIds] = useState<string[] | null>(null);
  const [presetId, setPresetId] = useState('');
  const [settings, setSettings] = useState<GenerationSettings>({ family: 'anima', ...FAMILY_DEFAULTS.anima, seed: -1 });
  const [missing, setMissing] = useState<{ items: MissingNode[]; request: Record<string, unknown> } | null>(null);
  // Where the images are made (#41): ComfyUI on this PC or an internet service. Each keeps its own last settings.
  const services = useQuery<ImageServices>({ queryKey: ['image-services'], queryFn: () => get('/api/image/services') });
  const [service, setServiceState] = useState(() => lastService(workId));
  const [serviceSettings, setServiceSettings] = useState(lastServiceSettings);
  const internet = service !== 'comfyui';
  const serviceInfo = services.data?.services.find((s) => s.id === service);
  const chooseService = (id: string) => {
    setServiceState(id);
    rememberService(workId, id);
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
    style_ids: styleIds,
    common_ids: chosenCommons,
    composition_id: composition || undefined,
    ...(internet ? { settings: serviceSettings[service] ?? {} } : { preset_id: presetId || undefined, settings }),
    overrides: single ? overrides : {},
  });

  useEffect(() => setPreview(null), [chars, exprs, composition, styleIds, commonIds, settings, handed, service, serviceSettings]);

  async function send(request: Record<string, unknown>) {
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
  }

  async function sendWithout() {
    if (!missing) return;
    const request = missing.request as { settings?: GenerationSettings };
    setMissing(null);
    setBusy(true);
    try {
      await send({ ...request, settings: { ...request.settings, missing: 'skip' } });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  function applyPreset(id: string) {
    setPresetId(id);
    const preset = presets.data?.find((p) => p.id === id);
    if (!preset) return;
    setSettings({ ...preset.settings, family: preset.family, seed: preset.settings.seed ?? -1 });
    if (preset.common.length) setCommonIds(preset.common);
    setStyleIds(preset.styles);
  }

  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const toggle = (list: string[], id: string, on: boolean) => (on ? [...new Set([...list, id])] : list.filter((x) => x !== id));
  const notApplied = (item: Fragment) => (fits(item, target) ? null : <span className="warn-text small"> ({t('gen.not_applied')})</span>);
  const styleView = visibleFor(Object.values(styles.data ?? {}), target, styleIds, showOthers);
  const commonView = visibleFor(Object.values(commons.data ?? {}), target, chosenCommons, showOthers);
  const hiddenCount = styleView.hidden + commonView.hidden;
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
        <div className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lib.kind.styles')}</span>
          {byGroup(styleView.shown).map(({ group, items }) => (
            <div key={group || '-'} className="row" style={{ flexWrap: 'wrap' }}>
              {group && <span className="faint small lib-group-inline">{group}</span>}
              {items.map((s) => (
                <label key={s.id} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={styleIds.includes(s.id)} onChange={(e) => setStyleIds(toggle(styleIds, s.id, e.target.checked))} />
                  {s.name}
                  {notApplied(s)}
                </label>
              ))}
            </div>
          ))}
          {Object.keys(styles.data ?? {}).length === 0 && <span className="faint">{t('gen.none_in_library')}</span>}
        </div>
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
        {!internet && (
          <>
            <div className="row">
              <label className="col" style={{ gap: 2 }}>
                <span className="muted">{t('gen.preset')}</span>
                <select value={presetId} onChange={(e) => applyPreset(e.target.value)}>
                  <option value="">{t('gen.no_preset')}</option>
                  {(presets.data ?? []).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <GenSettings value={settings} onChange={setSettings} />
          </>
        )}
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
                if (!internet) {
                  // Custom nodes the settings need but ComfyUI lacks (#178): ask before queueing.
                  const check: { missing: MissingNode[] } = await post('/api/image/generate/check-nodes', request);
                  if (check.missing.length) {
                    setMissing({ items: check.missing, request });
                    return;
                  }
                }
                await send(request);
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
        {missing && (
          <Dialog
            title={t('gen.missing_title')}
            onClose={() => setMissing(null)}
            actions={
              <>
                {openSettings && missing.items.some((m) => m.pack?.installable) && <button onClick={openSettings}>{t('gen.missing_install')}</button>}
                <button className="primary" onClick={sendWithout}>
                  {t('gen.missing_skip')}
                </button>
              </>
            }
          >
            <p>{t('gen.missing_body')}</p>
            <ul className="col" style={{ gap: 4 }}>
              {missing.items.map((m) => (
                <li key={`${m.kind}:${m.name}`}>
                  <strong className="mono">{m.name}</strong> <span className="faint">({t(`gen.missing_kind.${m.kind}`)})</span>
                  {m.pack ? (
                    <div className="faint small">
                      {t(m.pack.installable ? 'gen.missing_pack_installable' : 'gen.missing_pack_user', { pack: m.pack.id, license: m.pack.license ?? '' })}
                      {m.pack.repo ? ` · ${m.pack.repo}` : ''}
                    </div>
                  ) : (
                    <div className="faint small">{t('gen.missing_pack_unknown')}</div>
                  )}
                </li>
              ))}
            </ul>
            <p className="faint small">{t('gen.missing_skip_hint')}</p>
          </Dialog>
        )}
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
