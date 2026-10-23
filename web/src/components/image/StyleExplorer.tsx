import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import type { PoolDocument, PoolItem, PoolKind, SearchRules, StylePool, StylePools, StyleSession } from '../../imageTypes';
import { useUnsaved } from '../Unsaved';
import GenSettings, { useCatalog, type GenerationSettings } from './GenSettings';
import NovelAISettings, { type NovelAIInfo } from './NovelAISettings';
import ImageLab, { HANDOFF_KEY, hasLabHandoff } from './ImageLab';

const endpoint = '/api/image/explore';
const VOTES = ['a', 'b', 'tie', 'bad', 'skip'] as const;
const EMPTY: StylePools = { artists: [], models: [], loras: [] };
const SCENE =
  '1girl, adult woman, short black hair, blue eyes, white shirt, blue jacket, black pants, standing, upper body, front view, simple gray background';
const SAMPLES = [
  'kani_biimu',
  'ask_(askzy)',
  'mignon',
  'atdan',
  'sho_(sho_lwlw)',
  'wlop',
  'dairi',
  'mocha_(cotton)',
  'c.c.r',
  'ciloranko',
  'hiten_(hitenkei)',
  'ningen_mame',
];
const DEFAULTS: SearchRules = {
  artist_min: 1,
  artist_max: 3,
  lora_min: 0,
  lora_max: 2,
  artist_low: 0.8,
  artist_high: 1.2,
  artist_step: 0.1,
  lora_low: 0.4,
  lora_high: 1,
  lora_step: 0.1,
  split_clip: false,
  clip_low: 0.4,
  clip_high: 1,
  clip_step: 0.1,
};
const entries = (names: string[]): PoolItem[] =>
  [...new Set(names.map((n) => n.trim()).filter(Boolean))].map((name) => ({ name, mode: 'candidate' }));
const message = (e: unknown) => (e instanceof ApiError ? tm(e.msg) : String(e));

export default function ImageExperiments({ workId, active, openPresets }: { workId: string; active: boolean; openPresets: () => void }) {
  const [serviceTab, setServiceTab] = useState<'comfyui' | 'novelai'>('comfyui');
  const [tab, setTab] = useState<'lab' | 'explore'>(() => (hasLabHandoff() ? 'lab' : 'explore'));
  useEffect(() => {
    const take = () => setTab('lab');
    window.addEventListener(HANDOFF_KEY, take);
    return () => window.removeEventListener(HANDOFF_KEY, take);
  }, []);
  return (
    <>
      <nav className="row pad" aria-label={t('explore.tabs')}>
        <button className={tab === 'explore' ? 'primary' : ''} onClick={() => setTab('explore')}>
          {t('explore.title')}
        </button>
        <button className={tab === 'lab' ? 'primary' : ''} onClick={() => setTab('lab')}>
          {t('builder.advanced')}
        </button>
      </nav>
      <div hidden={tab !== 'explore'}>
        <nav className="row pad" aria-label={t('explore.service')}>
          {(['comfyui', 'novelai'] as const).map(v => <button key={v} aria-pressed={serviceTab === v} className={serviceTab === v ? 'primary' : ''} onClick={() => setServiceTab(v)}>{v === 'comfyui' ? 'ComfyUI' : 'NovelAI'}</button>)}
        </nav>
        {(['comfyui', 'novelai'] as const).map(v => <div hidden={serviceTab !== v} key={v}><StyleExplorer openPresets={openPresets} initialService={v} active={active && tab === 'explore' && serviceTab === v} /></div>)}
      </div>
      <div hidden={tab !== 'lab'}>
        <ImageLab workId={workId} active={active && tab === 'lab'} />
      </div>
    </>
  );
}

export function StyleExplorer({ openPresets, active = true, initialService = 'comfyui' }: { openPresets: () => void; active?: boolean; initialService?: 'comfyui' | 'novelai' }) {
  const qc = useQueryClient();
  const catalog = useCatalog();
  const pools = useQuery<PoolDocument>({ queryKey: ['style-pools'], queryFn: () => get(`${endpoint}/pools`) });
  const sessions = useQuery<Pick<StyleSession, 'id' | 'name' | 'service'>[]>({
    queryKey: ['style-sessions'],
    queryFn: () => get(`${endpoint}/sessions`),
  });
  const [sid, setSid] = useState('');
  const session = useQuery<StyleSession>({
    queryKey: ['style-session', sid],
    queryFn: () => get(`${endpoint}/sessions/${sid}`),
    enabled: !!sid && active,
    refetchOnWindowFocus: false,
  });
  const s = session.data;
  const [service, setService] = useState<'comfyui' | 'novelai'>(initialService);
  const [family, setFamily] = useState<'anima' | 'sdxl'>('anima');
  const [selected, setSelected] = useState<StylePools>(EMPTY);
  const [rules, setRules] = useState<SearchRules>({});
  const [settings, setSettings] = useState<Record<string, unknown>>({ seed: 104729, width: 1024, height: 1024 });
  const [positive, setPositive] = useState(SCENE),
    [negative, setNegative] = useState('extra people, duplicate');
  const [name, setName] = useState('');
  const [dirty, setDirty] = useState(false),
    [conditionsDirty, setConditionsDirty] = useState(false);
  const [editing, setEditing] = useState<PoolKind | null>(null);
  const [count, setCount] = useState(10),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [chosen, setChosen] = useState<string[]>([]),
    [presetName, setPresetName] = useState('');
  const [unknown, setUnknown] = useState(false),
    [deleteImages, setDeleteImages] = useState(false);
  useUnsaved(`style-explore-${initialService}`, dirty || conditionsDirty || busy);
  const [automatic, setAutomatic] = useState(true), [limit, setLimit] = useState(30);
  const [target, setTarget] = useState('all');
  useEffect(() => { if (s?.flow?.mode === 'refine' && s.refinement?.base) setChosen([s.refinement.base]); }, [s?.flow?.mode, s?.refinement?.base]);
  const [materialsOpen, setMaterialsOpen] = useState(true);
  useEffect(() => { setMaterialsOpen(!s?.candidates.length); }, [s?.id, !!s?.candidates.length]);
  const edits = useRef(false);
  edits.current = dirty || conditionsDirty;
  const owner = useRef(crypto.randomUUID());
  const working = useRef(false);
  const pendingHeartbeat = useRef<Promise<unknown> | null>(null);
  const loaded = useRef('');
  useEffect(() => {
    if (!active || !sid) return;
    let disposed = false;
    const beat = () => {
      if (disposed || working.current || pendingHeartbeat.current) return;
      pendingHeartbeat.current = post<StyleSession>(`${endpoint}/sessions/${sid}`, {action: 'heartbeat', owner: owner.current, hold: edits.current})
        .then(result => { if (!disposed) qc.setQueryData(['style-session', sid], result); })
        .catch(e => { if (!disposed) setError(message(e)); })
        .finally(() => { pendingHeartbeat.current = null; });
    };
    const leave = () => {
      disposed = true;
      void fetch(`${endpoint}/sessions/${sid}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, credentials: 'same-origin', keepalive: true,
        body: JSON.stringify({action: 'leave', owner: owner.current})}).catch(() => {});
    };
    const timer = window.setInterval(beat, 2000);
    window.addEventListener('pagehide', leave);
    return () => { clearInterval(timer); window.removeEventListener('pagehide', leave); leave(); };
  }, [active, sid, qc]);
  useEffect(() => {
    if (s && loaded.current !== s.id) {
      loaded.current = s.id;
      setService(s.service);
      setFamily(s.family);
      setSelected(s.pools);
      setRules(s.rules);
      setSettings(s.settings);
      setPositive(s.positive);
      setNegative(s.negative);
      setName(s.name);
      setDirty(false);
      setConditionsDirty(false);
      setChosen([]);
      setAutomatic(s.flow?.enabled ?? true);
      setLimit(s.flow?.limit ?? 30);
      setCount(s.flow?.count ?? 10);
    }
  }, [s]);
  const info = useQuery<NovelAIInfo>({
    queryKey: ['image-service-info', 'novelai'],
    queryFn: () => get('/api/image/services/novelai/info'),
    enabled: active && service === 'novelai',
    staleTime: Infinity,
  });
  async function run(fn: () => Promise<unknown>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    await pendingHeartbeat.current;
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.status === 409) await session.refetch();
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  async function act(action: string, extra: Record<string, unknown> = {}) {
    if (!s) return;
    const current = qc.getQueryData<StyleSession>(['style-session', s.id]) ?? s;
    const result = await post<StyleSession & { deleted?: boolean }>(`${endpoint}/sessions/${s.id}`, {
      revision: current.revision,
      action,
      ...extra,
    });
    if (result.deleted) {
      setSid('');
      loaded.current = '';
      await qc.invalidateQueries({ queryKey: ['style-sessions'] });
    } else qc.setQueryData(['style-session', s.id], result);
    return result;
  }
  function vote(choice: typeof VOTES[number]) {
    if (!active || busy || editing || !s?.pair) return;
    const pair = s.pair.join(':');
    void run(async () => {
      const current = qc.getQueryData<StyleSession>(['style-session', s.id]);
      if (current?.pair?.join(':') === pair) await act('evaluate', { choice });
    });
  }
  useEffect(() => {
    if (!active || !s?.pair || editing) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="dialog"], [role="textbox"]')) return;
      const choice = VOTES[Number(event.key) - 1];
      if (!choice) return;
      event.preventDefault();
      vote(choice);
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  });
  async function create() {
    const result = await post<StyleSession>(`${endpoint}/sessions`, {
      service,
      family,
      name,
      pools: service === 'novelai' ? { ...selected, loras: [] } : selected,
      rules: service === 'novelai' ? { ...rules, lora_min: 0, lora_max: 0 } : rules,
      settings,
      positive,
      negative,
    });
    loaded.current = result.id;
    setRules(result.rules);
    setSettings(result.settings);
    setSid(result.id);
    qc.setQueryData(['style-session', result.id], result);
    setDirty(false);
    setConditionsDirty(false);
    await qc.invalidateQueries({ queryKey: ['style-sessions'] });
    return result;
  }
  async function start() {
    let doc = !s || conditionsDirty ? await create() : (qc.getQueryData<StyleSession>(['style-session', s.id]) ?? s);
    const send = async (action: string, extra: Record<string, unknown> = {}) => {
      doc = await post<StyleSession>(`${endpoint}/sessions/${doc.id}`, {revision: doc.revision, action, ...extra});
      qc.setQueryData(['style-session', doc.id], doc);
    };
    if (dirty && !conditionsDirty && s) { await send('configure', {pools: selected, rules}); setDirty(false); }
    await send('automatic', {enabled: automatic, limit, count});
    await send('propose', {count});
    const n = doc.proposal?.candidates.length ?? 0;
    if (!n) { setError(t('builder.exhausted')); return; }
    if (!confirm(t('builder.confirm', {n, count, limit}) + '\n' + t('explore.cost'))) return;
    await send('generate', {allow_partial: true});
    await send('resume', {owner: owner.current});
  }
  const changePool = (kind: PoolKind, items: PoolItem[]) => {
    setSelected({ ...selected, [kind]: items });
    setDirty(true);
  };
  const kinds: PoolKind[] = service === 'novelai' ? ['artists'] : ['artists', 'models', 'loras'];
  const poolCards = kinds.map((kind) => (
    <div className="card col" style={{ flex: 1, minWidth: 180, padding: 12 }} key={kind}>
      <strong>
        {t(`explore.${kind}`)} · {selected[kind].filter((x) => x.mode !== 'exclude').length}
      </strong>
      <select
        aria-label={t(`explore.${kind}`)}
        value=""
        onChange={(e) => {
          const p = pools.data?.items.find((p) => p.id === e.target.value);
          if (p) changePool(kind, p.items);
        }}
      >
        <option value="">{t('explore.choose_pool')}</option>
        {pools.data?.items
          .filter((p) => p.kind === kind)
          .map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.items.length})
            </option>
          ))}
      </select>
      <button onClick={() => setEditing(kind)}>{t('explore.manage')}</button>
    </div>
  ));
  const conditionChanged = () => {
    setConditionsDirty(true);
  };
  const scores = s
    ? [...s.candidates].sort(
        (a, b) => Number(b.status === 'done') - Number(a.status === 'done') || s.scores[b.id].score - s.scores[a.id].score,
      )
    : [];
  return (
    <section className="pad col style-builder" style={{ gap: 16, maxWidth: 1320, margin: 'auto' }} aria-label={t('explore.title')}>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <h2 className="grow">{t('explore.title')}</h2>
        <select
          aria-label={t('explore.sessions')}
          value={sid}
          disabled={busy}
          onChange={(e) => {
            if ((dirty || conditionsDirty) && !confirm(t('explore.discard'))) return;
            setSid(e.target.value);
            if (!e.target.value) {
              loaded.current = '';
              setDirty(false);
              setConditionsDirty(false);
            }
          }}
        >
          <option value="">{t('explore.new')}</option>
          {sessions.data?.filter(x => x.service === service).map((x) => (
            <option key={x.id} value={x.id}>
              {x.service} · {x.name}
            </option>
          ))}
        </select>
      </div>
      <ol className="builder-steps" aria-label={t('builder.flow')}>
        <li aria-current={!s?.candidates.length ? 'step' : undefined}>{t('builder.materials')}</li>
        <li aria-current={s?.candidates.length && s.flow?.mode !== 'refine' ? 'step' : undefined}>{t('builder.explore')}</li>
        <li aria-current={s?.flow?.mode === 'refine' ? 'step' : undefined}>{t('builder.refine')}</li>
        <li>{t('explore.save_presets')}</li>
      </ol>
      {!s?.candidates.length && <p className="muted">{t(service === 'novelai' ? 'builder.nai_intro' : 'explore.intro')}</p>}
      {service === 'novelai' && <label>{t('explore.fixed_model')} <select aria-label={t('explore.fixed_model')} value={selected.models[0]?.name ?? ''} onChange={e => {changePool('models', entries([e.target.value])); conditionChanged();}}>
        <option value="">{t('explore.fixed_model')}</option>
        {info.data?.models?.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
      </select></label>}
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {(session.error || pools.error || sessions.error) && <p role="alert">{message(session.error || pools.error || sessions.error)}</p>}
      <details open={materialsOpen} onToggle={e => setMaterialsOpen(e.currentTarget.open)}>
        <summary>{t('builder.materials')}{s?.candidates.length ? ` · ${selected.artists.length} artist` : ''}</summary>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        {poolCards}
      </div>
      <details>
        <summary>
          {t('explore.conditions')} · {service} / {service === 'novelai' ? (selected.models[0]?.name ?? t('explore.fixed_model')) : family} · {String(settings.width ?? 1024)}×{String(settings.height ?? 1024)} · seed{' '}
          {String(settings.seed)}
        </summary>
        <div className="col" style={{ gap: 10, padding: 12 }}>
          <p>{t('explore.conditions_hint')}</p>
          <label>
            {t('explore.name')}{' '}
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                conditionChanged();
              }}
            />
          </label>
          <div className="row">
            {service === 'comfyui' && (
              <select
                aria-label={t('explore.family')}
                value={family}
                onChange={(e) => {
                  setFamily(e.target.value as typeof family);
                  conditionChanged();
                }}
              >
                <option value="anima">Anima</option>
                <option value="sdxl">SDXL</option>
              </select>
            )}
          </div>
          <label className="col">
            {t('explore.scene')}
            <textarea
              rows={3}
              value={positive}
              onChange={(e) => {
                setPositive(e.target.value);
                conditionChanged();
              }}
            />
          </label>
          <label className="col">
            {t('explore.negative')}
            <textarea
              value={negative}
              onChange={(e) => {
                setNegative(e.target.value);
                conditionChanged();
              }}
            />
          </label>
          {active && (service === 'comfyui' ? (
            <GenSettings
              value={{ ...settings, family } as GenerationSettings}
              onChange={(v) => {
                setSettings(v);
                setFamily(v.family ?? family);
                conditionChanged();
              }}
            />
          ) : (
            <NovelAISettings
              fixedModel
              value={{...settings, model: selected.models[0]?.name}}
              onChange={(v) => {
                setSettings(v);
                conditionChanged();
              }}
            />
          ))}
          <p className="muted">{t('explore.pool_override')}</p>
        </div>
      </details>
      <details>
        <summary>{t('explore.rules')}</summary>
        <div className="row" style={{ flexWrap: 'wrap', gap: 20, padding: 12 }}>
          {['artist', ...(service === 'comfyui' ? ['lora', ...(rules.split_clip ? ['clip'] : [])] : [])].map((kind) => (
            <fieldset key={kind}>
              <legend>{kind}</legend>
              <div className="col" style={{ gap: 6 }}>
                {(kind === 'clip' ? ['low', 'high', 'step'] : ['min', 'max', 'low', 'high', 'step']).map((key) => {
                  const k = `${kind}_${key}`;
                  const available = selected[kind === 'artist' ? 'artists' : 'loras'].filter((x) => x.mode !== 'exclude').length;
                  const fallback = key === 'min' || key === 'max' ? Math.min(Number(DEFAULTS[k]), available) : Number(DEFAULTS[k]);
                  return (
                    <label className="row" key={k}>
                      {t(`explore.${key}`)}
                      <input
                        style={{ width: 90 }}
                        aria-label={`${kind} ${t(`explore.${key}`)}`}
                        type="number"
                        step={key === 'min' || key === 'max' ? 1 : 'any'}
                        value={Number(rules[k] ?? fallback)}
                        onChange={(e) => {
                          setRules({ ...rules, [k]: Number(e.target.value) });
                          setDirty(true);
                        }}
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
          {service === 'comfyui' && (
            <label>
              <input
                type="checkbox"
                checked={!!rules.split_clip}
                onChange={(e) => {
                  setRules({ ...rules, split_clip: e.target.checked });
                  setDirty(true);
                }}
              />
              {t('explore.split_clip')}
            </label>
          )}
        </div>
        <p>{t('explore.limits')}</p>
      </details>
      {s && dirty && !conditionsDirty && <button disabled={busy} onClick={() => run(async () => {await act('configure', {pools: selected, rules}); setDirty(false);})}>{t('explore.apply')}</button>}
      </details>
      <div className="card pad col" style={{gap: 12}}>
        <div className="row" style={{flexWrap: 'wrap'}}>
          <label className="builder-check"><input type="checkbox" checked={automatic} onChange={e => setAutomatic(e.target.checked)} />{t('builder.auto')}</label>
          <label>{t('builder.limit')} <input type="number" min={1} max={5000} value={limit} style={{width: 85}} onChange={e => setLimit(Number(e.target.value))} /></label>
          <label>{t('builder.batch')} <input type="number" min={1} max={5000} value={count} style={{width: 75}} onChange={e => setCount(Number(e.target.value))} /></label>
          {s && <button disabled={busy} onClick={() => run(() => act('automatic', {enabled: automatic, limit, count}))}>{t('builder.apply_auto')}</button>}
        </div>
        <details><summary>{t('builder.criteria')}</summary><p className="muted">{t('builder.auto_hint')}</p></details>
        {s?.flow && <div role="status">
          {t('builder.progress', {round: s.rounds?.length ?? 0, used: s.flow.used, limit: s.flow.limit})} · {t(`builder.reason.${s.flow.reason}`)}
          {s.flow.mode === 'explore' && <> · {t('builder.coverage', {n: s.flow.readiness.covered, total: s.flow.readiness.total})}</>}
          {s.flow_error && <p role="alert">{typeof s.flow_error === 'string' ? s.flow_error : tm(s.flow_error)}</p>}
        </div>}
        <div className="row" style={{flexWrap: 'wrap'}}>
          <button className="primary" disabled={busy || !!s?.candidates.some(c => ['queued','running','cancelling'].includes(c.status)) || s?.flow?.mode === 'refine'} onClick={() => run(start)}>{t(s?.candidates.length ? 'builder.add_round' : 'builder.start')}</button>
          {!!s?.candidates.length && <>
            <button disabled={busy || dirty || conditionsDirty || s.flow?.reason === 'choose_base'} onClick={() => run(() => act(s.flow?.paused ? 'resume' : 'pause', {owner: owner.current}))}>{t(s.flow?.paused ? 'builder.resume' : 'builder.pause')}</button>
            <button disabled={busy || !s.events.some(e => !e.undone)} onClick={() => run(() => act('undo'))}>{t('explore.undo')}</button>
            <button disabled={busy} onClick={() => run(() => act('cancel'))}>{t('explore.cancel')}</button>
          </>}
        </div>
      </div>
      {s && s.candidates.length > 0 && (
        <>
          {s.pair && (
            <div className="col" style={{ gap: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 16 }}>
                {s.pair.map((id, i) => {
                  const c = s.candidates.find((c) => c.id === id)!;
                  return (
                    <article key={id}>
                      <strong>{i === 0 ? 'A' : 'B'}</strong>
                      {c.image_missing ? (
                        <p>{t('explore.missing')}</p>
                      ) : (
                        <button type="button" disabled={busy} aria-label={t(`explore.vote.${i === 0 ? 'a' : 'b'}`)} onClick={() => vote(i === 0 ? 'a' : 'b')} style={{ display: 'block', width: '100%', padding: 0 }}>
                          <img alt={i === 0 ? 'A' : 'B'} src={c.image_url} style={{ display: 'block', width: '100%', maxHeight: 'min(50vh,560px)', objectFit: 'contain' }} />
                        </button>
                      )}
                      <details>
                        <summary>{t('explore.combination')}</summary>
                        <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(c.config, null, 2)}</pre>
                      </details>
                    </article>
                  );
                })}
              </div>
              <div className="row builder-votes" style={{ justifyContent: 'center', flexWrap: 'wrap' }}>
                {VOTES.map((choice, index) => (
                  <button key={choice} disabled={busy} aria-keyshortcuts={String(index + 1)} onClick={() => vote(choice)}>
                    {index + 1}: {t(`explore.vote.${choice}`)}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!s.pair && <p className="builder-wait">{t(s.flow?.reason === 'generating' ? 'builder.wait' : 'builder.review_hint')}</p>}
          <details>
            <summary>{t('explore.ranking')}</summary>
            <p className="muted">{t('explore.ranking_hint')}</p>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%' }}>
                <thead>
                  <tr>
                    <th>{t('explore.select')}</th>
                    <th>{t('explore.candidate')}</th>
                    <th>Elo</th>
                    <th>{t('explore.evaluations')}</th>
                    <th>{t('explore.state')}</th>
                    <th>{t('explore.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {scores.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <input
                          aria-label={t('builder.candidate', {n: s.candidates.indexOf(c) + 1})}
                          type="checkbox"
                          checked={chosen.includes(c.id)}
                          onChange={(e) => setChosen(e.target.checked ? [...chosen, c.id] : chosen.filter((id) => id !== c.id))}
                        />
                      </td>
                      <td>
                        <details>
                          <summary>{t('builder.candidate', {n: s.candidates.indexOf(c) + 1})}</summary>
                          {c.image_url && !c.image_missing && <img src={c.image_url} alt="" width={100} loading="lazy" />}
                          <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(c.config, null, 2)}</pre>
                          <p>
                            {c.parent_id?.slice(0, 8)} · {c.change}
                          </p>
                        </details>
                      </td>
                      <td>{c.status === 'done' ? s.scores[c.id].score.toFixed(1) : '—'}</td>
                      <td>
                        {s.scores[c.id].count}
                        {s.scores[c.id].count < 3 ? ` · ${t('explore.insufficient')}` : ''} / {t('explore.bad_count')}: {s.scores[c.id].bad}
                      </td>
                      <td>
                        {t(`explore.status.${c.status}`)}
                        {c.image_missing && ` · ${t('explore.missing')}`}
                        {c.attempts.at(-1)?.error && <p>{tm(c.attempts.at(-1)!.error!)}</p>}
                        {(c.attempts.at(-1)?.prompt_id || c.attempts.at(-1)?.result_uncertain) && c.status !== 'done' && (
                          <p>{t('explore.unknown')}</p>
                        )}
                      </td>
                      <td>
                        <button
                          disabled={busy || !['failed', 'cancelled', 'interrupted'].includes(c.status)}
                          onClick={() => run(() => act('retry', { candidates: [c.id], confirmed_unknown: unknown }))}
                        >
                          {t('explore.retry')}
                        </button>
                        <label>
                          <input
                            type="checkbox"
                            checked={!!c.include_parent}
                            onChange={(e) => run(() => act('parent', { candidate: c.id, include: e.target.checked }))}
                          />
                          {t('explore.parent')}
                        </label>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
          {s.candidates.some(c=>['failed','interrupted','cancelled'].includes(c.status) && (c.attempts.at(-1)?.prompt_id || c.attempts.at(-1)?.result_uncertain)) && <label>
            <input type="checkbox" checked={unknown} onChange={(e) => setUnknown(e.target.checked)} />
            {t('explore.confirm_unknown')}
          </label>}
          <div className="card pad row" style={{flexWrap: 'wrap'}}>
            <label>{t('builder.base')} <select aria-label={t('builder.base')} value={chosen.length === 1 ? chosen[0] : ''} onChange={e => setChosen(e.target.value ? [e.target.value] : [])}>
              <option value="">{t('builder.choose')}</option>
              {scores.filter(c => c.status === 'done' && !c.image_missing).map(c => <option key={c.id} value={c.id}>{t('builder.candidate', {n: s.candidates.indexOf(c) + 1})} · Elo {s.scores[c.id].score.toFixed(0)}</option>)}
            </select></label>
            <select aria-label={t('builder.target')} value={target} onChange={e => setTarget(e.target.value)}>
              <option value="all">{t('builder.all_weights')}</option><option value="artist">Artist</option>{service === 'comfyui' && <option value="lora">LoRA</option>}
            </select>
            <button disabled={busy || chosen.length !== 1 || s.candidates.some(c => ['queued','running','cancelling'].includes(c.status))} onClick={() => run(async () => { await act('refine', {candidate: chosen[0], target}); await act('resume', {owner: owner.current}); if (!automatic) await act('refine_next'); })}>{t('builder.refine')}</button>
            {s.flow?.mode === 'refine' && <>
              <button disabled={busy || !!s.pair} onClick={() => run(() => act('refine_next'))}>{t('builder.next_weight')}</button>
              <button disabled={busy} onClick={() => run(() => act('explore'))}>{t('builder.back_explore')}</button>
            </>}
          </div>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <input
              aria-label={t('explore.preset_name')}
              placeholder={t('explore.preset_name')}
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
            />
            <button
              disabled={busy || !chosen.length}
              onClick={() => run(() => act('save_presets', { candidates: chosen, name: presetName }))}
            >
              {t('explore.save_presets')}
            </button>
            <button onClick={openPresets}>{t('explore.open_presets')}</button>
            {!!s.saved_presets?.length && <span role="status">{t('explore.saved', { n: s.saved_presets.length })}</span>}
          </div>
          <details>
            <summary>{t('explore.delete_session')}</summary>
            <label>
              <input type="checkbox" checked={deleteImages} onChange={(e) => setDeleteImages(e.target.checked)} />
              {t('explore.delete_images')}
            </label>
            <button
              disabled={busy}
              onClick={() => {
                if (confirm(t('explore.delete_confirm'))) run(() => act('delete', { delete_images: deleteImages }));
              }}
            >
              {t('explore.delete_session')}
            </button>
          </details>
        </>
      )}
      {editing && pools.data && (
        <PoolEditor
          kind={editing}
          initial={selected[editing]}
          document={pools.data}
          catalogNames={
            editing === 'models'
              ? service === 'novelai'
                ? (info.data?.models?.map((m) => m.id) ?? [])
                : (catalog.data?.models ?? [])
              : (catalog.data?.loras ?? [])
          }
          onDocument={(d) => qc.setQueryData(['style-pools'], d)}
          onApply={(items) => {
            changePool(editing, items);
            setEditing(null);
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}

export function PoolEditor({
  kind,
  initial,
  document,
  catalogNames,
  onDocument,
  onApply,
  onClose,
}: {
  kind: PoolKind;
  initial: PoolItem[];
  document: PoolDocument;
  catalogNames: string[];
  onDocument: (d: PoolDocument) => void;
  onApply: (items: PoolItem[]) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState(initial),
    [name, setName] = useState(''),
    [id, setId] = useState('');
  const [query, setQuery] = useState(''),
    [offset, setOffset] = useState(0),
    [bulk, setBulk] = useState(''),
    [error, setError] = useState(''),
    [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useUnsaved('style-pool', dirty || busy);
  const search = useQuery<{ items: string[]; total: number; available: boolean }>({
    queryKey: ['style-artists', query, offset],
    queryFn: () => get(`${endpoint}/artists?q=${encodeURIComponent(query)}&offset=${offset}`),
    enabled: kind === 'artists',
  });
  const names =
    kind === 'artists'
      ? (search.data?.items ?? [])
      : catalogNames.filter((n) => n.toLowerCase().includes(query.toLowerCase())).slice(offset, offset + 50);
  const total =
    kind === 'artists' ? (search.data?.total ?? 0) : catalogNames.filter((n) => n.toLowerCase().includes(query.toLowerCase())).length;
  function add(next: PoolItem[]) {
    setItems([...items, ...next.filter((n) => !items.some((x) => x.name === n.name))]);
    setDirty(true);
  }
  function load(p: StylePool) {
    if (dirty && !confirm(t('explore.discard'))) return;
    setItems(p.items);
    setName(p.name);
    setId(p.id);
    setDirty(false);
  }
  async function save(copy = false, remove = false) {
    setBusy(true);
    setError('');
    try {
      const d = await post<PoolDocument>(`${endpoint}/pools`, {
        revision: document.revision,
        id: copy ? undefined : id || undefined,
        kind,
        name,
        items,
        delete: remove,
      });
      onDocument(d);
      if (remove) {
        setId('');
        setName('');
      } else if (copy || !id) {
        setId(d.items.at(-1)!.id);
      }
      setDirty(false);
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.status === 409) onDocument(await get<PoolDocument>(`${endpoint}/pools`));
    } finally {
      setBusy(false);
    }
  }
  function close() {
    if (!busy && (!dirty || confirm(t('explore.discard')))) onClose();
  }
  return (
    <dialog
      ref={dialog}
      className="dialog"
      style={{ width: 900, minWidth: 0, maxWidth: '94vw', maxHeight: '90vh', overflow: 'auto' }}
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      aria-label={t('explore.manage')}
    >
      <div className="row">
        <h3 className="grow">
          {t('explore.manage')} · {t(`explore.${kind}`)}
        </h3>
        <button onClick={close}>{t('explore.close')}</button>
      </div>
      <fieldset disabled={busy} className="builder-pool-fields">
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <select
          aria-label={t('explore.choose_pool')}
          value={id}
          onChange={(e) => {
            const p = document.items.find((p) => p.id === e.target.value);
            if (p) load(p);
            else if (!dirty || confirm(t('explore.discard'))) {
              setId('');
              setName('');
              setItems([]);
              setDirty(false);
            }
          }}
        >
          <option value="">{t('explore.new')}</option>
          {document.items
            .filter((p) => p.kind === kind)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
        </select>
        <input
          aria-label={t('explore.pool_name')}
          placeholder={t('explore.pool_name')}
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setDirty(true);
          }}
        />
        <button disabled={busy || !name.trim()} onClick={() => save()}>
          {t('explore.save_pool')}
        </button>
        <button disabled={busy || !name.trim()} onClick={() => save(true)}>
          {t('explore.copy')}
        </button>
        <button
          disabled={busy || !id}
          onClick={() => {
            if (confirm(t('explore.delete_pool_confirm'))) save(false, true);
          }}
        >
          {t('explore.delete_pool')}
        </button>
      </div>
      {kind === 'artists' && (
        <p>
          {t('explore.dictionary_hint')}{' '}
          <button
            onClick={() => {
              add(entries(SAMPLES));
              setId('');
              setName(t('explore.sample'));
            }}
          >
            {t('explore.sample')}
          </button>
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {search.error && <p role="alert">{message(search.error)}</p>}
      <input
        aria-label={t('explore.search')}
        placeholder={t('explore.search')}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOffset(0);
        }}
      />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 16, marginTop: 12 }}>
        <div>
          <p>{t('explore.results', { n: total })}</p>
          <div className="col" style={{ maxHeight: 310, overflowY: 'auto' }}>
            {names.map((n) => (
              <label key={n} className="builder-check">
                <input
                  type="checkbox"
                  checked={items.some((x) => x.name === n)}
                  onChange={(e) => {
                    if (e.target.checked) add(entries([n]));
                    else {
                      setItems(items.filter((x) => x.name !== n));
                      setDirty(true);
                    }
                  }}
                />
                <span>{n}</span>
              </label>
            ))}
          </div>
          <div className="row">
            <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>
              {t('explore.previous')}
            </button>
            <span>{Math.floor(offset / 50) + 1}</span>
            <button disabled={offset + 50 >= total} onClick={() => setOffset(offset + 50)}>
              {t('explore.next')}
            </button>
          </div>
        </div>
        <div>
          <p>{t('explore.selected', { n: items.length })}</p>
          <div className="col" style={{ maxHeight: 310, overflowY: 'auto' }}>
            {items.map((x) => (
              <div className="row" key={x.name}>
                <span className="grow" style={{ overflowWrap: 'anywhere' }}>
                  {x.name}
                </span>
                <select
                  aria-label={x.name}
                  value={x.mode}
                  onChange={(e) => {
                    setItems(items.map((v) => (v.name === x.name ? { ...v, mode: e.target.value as PoolItem['mode'] } : v)));
                    setDirty(true);
                  }}
                >
                  {['always', 'candidate', 'exclude'].map((m) => (
                    <option key={m} value={m}>
                      {t(`explore.mode.${m}`)}
                    </option>
                  ))}
                </select>
                <button
                  aria-label={`${t('explore.remove')} ${x.name}`}
                  onClick={() => {
                    setItems(items.filter((v) => v.name !== x.name));
                    setDirty(true);
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>
      {kind === 'artists' && (
        <label className="col">
          {t('explore.bulk')}
          <textarea rows={3} value={bulk} onChange={(e) => setBulk(e.target.value)} />
          <button
            onClick={() => {
              add(entries(bulk.split(/\r?\n/)));
              setBulk('');
            }}
          >
            {t('explore.add')}
          </button>
        </label>
      )}
      <p>{t('explore.independent')}</p>
      <button className="primary" onClick={() => onApply(items)} disabled={busy}>
        {t('explore.use_pool')}
      </button>
      </fieldset>
    </dialog>
  );
}
