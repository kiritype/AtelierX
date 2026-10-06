import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, del, get, post, put } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';
import { useCatalog } from './GenSettings';
import { compareLorasInLab } from './ImageLab';
import { unfinished } from '../../lib/lifecycle';
import { useUnsaved } from '../Unsaved';

type Design = { id: string; name: string; has_design: boolean; trigger?: string; outfits: { id: string; name: string }[] };
type Candidate = { path: string; outfit_id: string; expression_id: string; expression_name: string; human_status: string; adopted: boolean; thumbnail_url: string };
type DatasetItem = { image: { path: string; sha256: string }; outfit_id: string; expression_id: string; caption: string; edited: boolean };
type Dataset = { id: string; name: string; outfits: string[]; triggers: { character: string; outfit: string }; items: DatasetItem[] };
type Run = {
  id: string;
  status: string;
  phase?: string | null;
  dataset: string;
  dataset_name?: string;
  output_name: string;
  base_model: string;
  settings: { method: string; epochs: number; save_every: number; learning_rate: string };
  created_at: string;
  finished_at?: string;
  error?: any;
  outputs: { epoch: number; file: { path: string; size: number } }[];
  progress: { step?: number; total_steps?: number; epoch?: number; total_epochs?: number; loss?: number };
  active: boolean;
};
type Model = {
  id: string;
  name: string;
  file: string;
  strength: number;
  auto_apply: boolean;
  apply_to: 'character' | 'outfit';
  outfit_id?: string;
  model_family: string;
  enabled: boolean;
  source?: { run?: string; epoch?: number; external?: boolean };
};
type Overview = { datasets: Dataset[]; runs: Run[]; models: Model[]; busy: boolean };

const msg = (value: any) => (value && typeof value === 'object' ? tm(value) : String(value ?? ''));

// Image menu → LoRA: per character, a dataset of adopted images with captions, training runs, and the LoRAs it uses.
export default function ImageLora({ workId, openLab, initialCharacterId, initialOutfitId }: { workId: string; openLab?: () => void; initialCharacterId?: string; initialOutfitId?: string }) {
  const designs = useQuery<Design[]>({ queryKey: ['image-designs', workId], queryFn: () => get(`/api/works/${workId}/image/designs`) });
  const [characterId, setCharacterId] = useState(initialCharacterId ?? '');
  const [tab, setTab] = useState<'dataset' | 'train' | 'models'>('dataset');
  const list = (designs.data ?? []).filter((d) => d.has_design);
  const design = list.find((d) => d.id === characterId);
  useEffect(() => {
    if (!characterId && list.length) setCharacterId(list[0].id);
  }, [list, characterId]);
  const base = `/api/works/${workId}/image/lora/${characterId}`;
  const overview = useQuery<Overview>({
    queryKey: ['lora', workId, characterId],
    queryFn: () => get(base),
    enabled: !!characterId,
    refetchInterval: (q) => ((q.state.data as Overview | undefined)?.runs.some((r) => unfinished(r.status)) ? 2000 : 10000),
  });

  return (
    <div className="lora">
      <aside className="lora-chars pad col">
        <div className="section-title">{t('gen.characters')}</div>
        {list.length === 0 && <div className="faint small">{t('lora.no_characters')}</div>}
        {list.map((d) => (
          <button key={d.id} className={`tree-link ${d.id === characterId ? 'on' : ''}`} onClick={() => setCharacterId(d.id)}>
            {d.name} <span className="faint">{d.id}</span>
          </button>
        ))}
      </aside>
      <div className="lora-main pad col">
        {!design ? (
          <div className="faint">{t('lora.choose_character')}</div>
        ) : (
          <>
            <div className="seg" style={{ alignSelf: 'flex-start' }}>
              {(['dataset', 'train', 'models'] as const).map((k) => (
                <button key={k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>
                  {t(`lora.tab.${k}`)}
                  {k === 'train' && overview.data?.runs.some((r) => unfinished(r.status)) ? ' ●' : ''}
                </button>
              ))}
            </div>
            {overview.data && tab === 'dataset' && <DatasetTab key={base} base={base} design={design} datasets={overview.data.datasets} initialOutfitId={characterId === initialCharacterId ? initialOutfitId : undefined} />}
            {overview.data && tab === 'train' && <TrainTab key={base} base={base} data={overview.data} openLab={openLab} />}
            {overview.data && tab === 'models' && <ModelsTab key={base} base={base} design={design} models={overview.data.models} />}
          </>
        )}
      </div>
    </div>
  );
}

function useAct() {
  const qc = useQueryClient();
  const toast = useToast();
  return async <T,>(fn: () => Promise<T>, done?: string): Promise<T | undefined> => {
    try {
      const result = await fn();
      if (done) toast({ text: done });
      await qc.invalidateQueries({ queryKey: ['lora'] });
      return result;
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
      return undefined;
    }
  };
}

function DatasetTab({ base, design, datasets, initialOutfitId }: { base: string; design: Design; datasets: Dataset[]; initialOutfitId?: string }) {
  const act = useAct();
  const [datasetId, setDatasetId] = useState((initialOutfitId ? datasets.find((dataset) => dataset.outfits.length === 1 && dataset.outfits[0] === initialOutfitId) : datasets[0])?.id ?? '');
  const current = datasets.find((d) => d.id === datasetId);
  const [outfits, setOutfits] = useState<string[]>([]);
  const [name, setName] = useState('');
  const [triggers, setTriggers] = useState({ character: '', outfit: '' });
  const [picked, setPicked] = useState<Set<string> | null>(null);
  const [captions, setCaptions] = useState<Record<string, string>>({});

  // Switching datasets loads its outfits, triggers and images into the form.
  useEffect(() => {
    setOutfits(current?.outfits ?? (initialOutfitId ? [initialOutfitId] : design.outfits[0] ? [design.outfits[0].id] : []));
    setName(current?.name ?? '');
    setTriggers(current?.triggers ?? { character: '', outfit: '' });
    setPicked(current ? new Set(current.items.map((i) => i.image.path)) : null);
    setCaptions({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [datasetId, current?.items.length]);

  const candidates = useQuery<Candidate[]>({
    queryKey: ['lora-candidates', base, outfits.join(',')],
    queryFn: () => get(`${base}/candidates?outfits=${outfits.join(',')}`),
    enabled: outfits.length > 0,
  });
  const pool = candidates.data ?? [];
  const chosen = picked ?? new Set(pool.filter((c) => c.adopted).map((c) => c.path));
  const toggle = (path: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(path);
    else next.delete(path);
    setPicked(next);
  };
  const outfitName = (id: string) => design.outfits.find((o) => o.id === id)?.name ?? id;
  const changed = Object.keys(captions).length > 0;
  useUnsaved('lora-captions', changed);

  return (
    <div className="col">
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lora.dataset')}</span>
          <select value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
            <option value="">{t('lora.new_dataset')}</option>
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id} · {d.name} ({d.items.length})
              </option>
            ))}
          </select>
        </label>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lib.name')}</span>
          <input value={name} placeholder={outfits.map(outfitName).join(', ')} onChange={(e) => setName(e.target.value)} />
        </label>
        {current && (
          <button
            className="danger"
            onClick={() => confirm(t('lora.delete_dataset_confirm', { id: current.id })) && act(() => del(`${base}/datasets/${current.id}`)).then((saved) => saved !== undefined && setDatasetId(''))}
          >
            {t('lora.delete_dataset')}
          </button>
        )}
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <span className="muted">{t('lora.outfits')}</span>
        {design.outfits.map((o) => (
          <label key={o.id} className="row" style={{ gap: 4 }}>
            <input
              type="checkbox"
              checked={outfits.includes(o.id)}
              onChange={(e) => (setOutfits(e.target.checked ? [...outfits, o.id] : outfits.filter((x) => x !== o.id)), setPicked(null))}
            />
            {o.name}
          </label>
        ))}
      </div>
      <div className="row" style={{ flexWrap: 'wrap' }}>
        <label className="col" style={{ gap: 2 }} title={t('lora.character_trigger_hint')}>
          <span className="muted">{t('lora.character_trigger')}</span>
          <input className="mono" value={triggers.character} placeholder={design.trigger ?? ''} onChange={(e) => setTriggers({ ...triggers, character: e.target.value })} />
        </label>
        <label className="col" style={{ gap: 2 }} title={t('lora.outfit_trigger_hint')}>
          <span className="muted">{t('lora.outfit_trigger')}</span>
          <input
            className="mono"
            value={triggers.outfit}
            placeholder={t('lora.outfit_trigger_placeholder')}
            onChange={(e) => setTriggers({ ...triggers, outfit: e.target.value })}
          />
        </label>
      </div>
      <div className="row">
        <span className="faint small grow">{t('lora.pick_hint', { n: chosen.size, total: pool.length })}</span>
        <button className="ghost" onClick={() => setPicked(new Set(pool.filter((c) => c.adopted).map((c) => c.path)))}>
          {t('lora.adopted_only')}
        </button>
        <button className="ghost" onClick={() => setPicked(new Set(pool.filter((c) => c.human_status === 'pass').map((c) => c.path)))}>
          {t('lora.all_passed')}
        </button>
        <button
          className="primary"
          disabled={!chosen.size}
          onClick={async () => {
            const saved = await act(
              () =>
                post<Dataset>(`${base}/datasets`, {
                  id: current?.id,
                  name: name || undefined,
                  outfits,
                  triggers: triggers.character || triggers.outfit ? triggers : undefined,
                  paths: [...chosen],
                }),
              t('lora.dataset_saved'),
            );
            if (saved) setDatasetId(saved.id);
          }}
        >
          {current ? t('lora.update_dataset') : t('lora.create_dataset')}
        </button>
      </div>
      {outfits.length > 0 && pool.length === 0 && !candidates.isLoading && <div className="faint">{t('lora.no_images')}</div>}
      <div className="gallery-grid" style={{ padding: 0 }}>
        {pool.map((c) => (
          <label key={c.path} className={`gallery-cell ${chosen.has(c.path) ? 'selected' : ''}`} title={c.path}>
            <img src={c.thumbnail_url} alt="" loading="lazy" />
            <input type="checkbox" className="gallery-check" checked={chosen.has(c.path)} onChange={(e) => toggle(c.path, e.target.checked)} />
            <div className="gallery-badges">
              {c.adopted && <span className="badge adopted">★</span>}
              {c.human_status === 'pass' && <span className="badge human-pass">✓</span>}
              {c.human_status === 'fail' && <span className="badge human-fail">✗</span>}
            </div>
            <div className="gallery-caption">
              {outfitName(c.outfit_id)} · {c.expression_name || c.expression_id}
            </div>
          </label>
        ))}
      </div>

      {current && (
        <>
          <div className="row">
            <div className="section-title grow">{t('lora.captions', { n: current.items.length })}</div>
            <button className="ghost" onClick={() => act(() => post(`${base}/datasets/${current.id}/captions`, { rebuild: true, triggers }), t('lora.captions_rebuilt'))}>
              {t('lora.rebuild_captions')}
            </button>
            <button
              className="primary"
              disabled={!changed}
              onClick={async () => {
                const submitted = { ...captions };
                const saved = await act(() => post(`${base}/datasets/${current.id}/captions`, { items: submitted }), t('lora.captions_saved'));
                if (saved !== undefined) {
                  setCaptions((latest) => Object.fromEntries(Object.entries(latest).filter(([path, text]) => submitted[path] !== text)));
                }
              }}
            >
              {t('lora.save_captions')}
            </button>
          </div>
          <span className="faint small">{t('lora.captions_hint')}</span>
          <div className="col">
            {current.items.map((item) => (
              <div key={item.image.path} className="row lora-caption">
                <img src={`/api/image/gallery/thumbnail?path=${encodeURIComponent(item.image.path)}`} alt="" />
                <div className="col grow" style={{ gap: 2 }}>
                  <span className="faint small">
                    {outfitName(item.outfit_id)} · {item.expression_id}
                    {item.edited && <span className="chip small">{t('lora.edited')}</span>}
                  </span>
                  <textarea
                    rows={2}
                    className="mono small"
                    value={captions[item.image.path] ?? item.caption}
                    onChange={(e) => setCaptions({ ...captions, [item.image.path]: e.target.value })}
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function TrainTab({ base, data, openLab }: { base: string; data: Overview; openLab?: () => void }) {
  const act = useAct();
  const status = useQuery<any>({ queryKey: ['training-status'], queryFn: () => get('/api/image/training/status') });
  const [form, setForm] = useState({ dataset_id: data.datasets[0]?.id ?? '', method: 'atelierx_tlora', base: '', epochs: 40, save_every: 10, learning_rate: '1e-4' });
  const [logFor, setLogFor] = useState('');
  const log = useQuery<{ text: string }>({ queryKey: ['lora-log', base, logFor], queryFn: () => get(`${base}/runs/${logFor}/log`), enabled: !!logFor, refetchInterval: 3000 });
  const s = status.data;
  const problems = s
    ? [
        !s.trainer_found && t('lora.problem.trainer'),
        s.trainer_found && !s.patched && t('lora.problem.patch'),
        s.trainer_found && !s.python_found && t('lora.problem.python'),
        !s.lora_dir_found && t('lora.problem.lora_dir'),
        !s.bases.length && t('lora.problem.models'),
      ].filter(Boolean)
    : [];
  const baseId = form.base || s?.bases[0]?.id || '';
  return (
    <div className="col">
      {problems.length > 0 && (
        <div className="compose-card">
          <strong className="warn-text">{t('lora.setup_needed')}</strong>
          {problems.map((p) => (
            <div key={p as string} className="small">
              · {p}
            </div>
          ))}
          <span className="faint small">{t('lora.setup_hint')}</span>
        </div>
      )}
      <div className="row" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lora.dataset')}</span>
          <select value={form.dataset_id} onChange={(e) => setForm({ ...form, dataset_id: e.target.value })}>
            {data.datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.id} · {d.name} ({d.items.length})
              </option>
            ))}
          </select>
        </label>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lora.method')}</span>
          <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
            {(s?.methods ?? []).map((m: any) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lora.base_model')}</span>
          <select value={baseId} onChange={(e) => setForm({ ...form, base: e.target.value })}>
            {(s?.bases ?? []).map((b: any) => (
              <option key={b.id} value={b.id}>
                {msg(b.label)}
              </option>
            ))}
          </select>
        </label>
        {(['epochs', 'save_every'] as const).map((k) => (
          <label key={k} className="col" style={{ gap: 2 }}>
            <span className="muted">{t(`lora.${k}`)}</span>
            <input type="number" min={1} style={{ width: 80 }} value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} />
          </label>
        ))}
        <label className="col" style={{ gap: 2 }}>
          <span className="muted">{t('lora.learning_rate')}</span>
          <input className="mono" style={{ width: 90 }} value={form.learning_rate} onChange={(e) => setForm({ ...form, learning_rate: e.target.value })} />
        </label>
        <button
          className="primary"
          disabled={!form.dataset_id || data.busy || problems.length > 0}
          onClick={() =>
            act(
              () =>
                post(`${base}/runs`, {
                  dataset_id: form.dataset_id,
                  params: { method: form.method, base: baseId, epochs: form.epochs, save_every: form.save_every, learning_rate: form.learning_rate },
                }),
              t('lora.started'),
            )
          }
        >
          {t('lora.start')}
        </button>
      </div>
      <span className="faint small">{t('lora.train_hint')}</span>
      {data.datasets.length === 0 && <div className="faint">{t('lora.no_datasets')}</div>}
      <div className="section-title">{t('lora.runs')}</div>
      {data.runs.length === 0 && <div className="faint small">{t('lora.no_runs')}</div>}
      {data.runs.map((run) => (
        <RunCard key={run.id} base={base} run={run} act={act} openLab={openLab} dataset={data.datasets.find((d) => d.id === run.dataset)} showLog={() => setLogFor(logFor === run.id ? '' : run.id)} logOpen={logFor === run.id} log={log.data?.text} />
      ))}
    </div>
  );
}

function RunCard({ base, run, act, openLab, dataset, showLog, logOpen, log }: { base: string; run: Run; act: ReturnType<typeof useAct>; openLab?: () => void; dataset?: Dataset; showLog: () => void; logOpen: boolean; log?: string }) {
  const catalog = useCatalog();
  const compare = () => act(async () => {
    const latest = await catalog.refetch();
    const resolve = (path: string, choices: string[]) => {
      const normalized = path.replaceAll('\\', '/');
      const matches = choices.filter((name) => normalized.split('/').pop() === name.replaceAll('\\', '/').split('/').pop());
      if (matches.length !== 1) throw new Error(t('lora.compare_missing', { file: path }));
      return matches[0];
    };
    const files = run.outputs.map((o) => resolve(o.file.path, latest.data?.loras ?? []));
    const model = resolve(`${run.base_model}.safetensors`, latest.data?.models ?? []);
    const prompt = dataset?.items[0]?.caption ?? [dataset?.triggers.character, dataset?.triggers.outfit].filter(Boolean).join(', ');
    compareLorasInLab(files, prompt, model);
    openLab?.();
  });
  const [auto, setAuto] = useState(true);
  const p = run.progress ?? {};
  const percent = p.total_steps && p.step ? Math.round((p.step / p.total_steps) * 100) : null;
  return (
    <div className={`compose-card run-${run.status}`}>
      <div className="row">
        <strong>{run.id}</strong>
        <span className={`chip ${run.status === 'done' ? 'status-new' : run.status === 'failed' ? 'type-mismatch' : ''}`}>{t(`lora.status.${run.phase ?? run.status}`)}</span>
        <span className="faint small grow">
          {run.dataset_name ?? run.dataset} · {run.base_model} · {run.settings.method} · {run.settings.epochs} ep · lr {run.settings.learning_rate}
        </span>
        <button className="ghost" onClick={showLog}>
          {t('lora.log')}
        </button>
        {unfinished(run.status) && run.active && (
          <button className="danger" onClick={() => confirm(t('lora.cancel_confirm')) && act(() => post(`${base}/runs/${run.id}/cancel`))}>
            {t('common.cancel')}
          </button>
        )}
      </div>
      {unfinished(run.status) && (
        <div className="col" style={{ gap: 2 }}>
          {percent !== null && <progress max={100} value={percent} />}
          <span className="faint small">
            {p.step ? t('lora.progress', { step: p.step, total: p.total_steps ?? '?', epoch: p.epoch ?? '?', loss: p.loss?.toFixed?.(4) ?? '–' }) : t(`lora.status.${run.phase ?? run.status}`)}
          </span>
        </div>
      )}
      {run.error && <div className="error-text small">{msg(run.error)}</div>}
      {run.outputs.length > 0 && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <span className="muted small">{t('lora.outputs')}</span>
          {openLab && run.outputs.length >= 2 && <button onClick={compare}>{t('lora.compare_epochs')}</button>}
          {run.outputs.map((o) => (
            <button key={o.epoch} onClick={() => act(() => post(`${base}/models`, { run_id: run.id, epoch: o.epoch, auto_apply: auto }), t('lora.registered', { epoch: o.epoch }))}>
              {t('lora.register_epoch', { epoch: o.epoch })}
            </button>
          ))}
          <label className="row small" style={{ gap: 4 }}>
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            {t('lora.auto_on_register')}
          </label>
        </div>
      )}
      {logOpen && <pre className="lora-log mono small">{log || '…'}</pre>}
    </div>
  );
}

function ModelsTab({ base, design, models }: { base: string; design: Design; models: Model[] }) {
  const act = useAct();
  const catalog = useCatalog();
  const [edits, setEdits] = useState<Record<string, Partial<Model>>>({});
  useUnsaved('lora-models', Object.values(edits).some(Boolean));
  const [external, setExternal] = useState('');
  const loras = useMemo(() => catalog.data?.loras ?? [], [catalog.data]);
  const value = <K extends keyof Model>(m: Model, k: K): Model[K] => (edits[m.id]?.[k] ?? m[k]) as Model[K];
  const edit = (m: Model, patch: Partial<Model>) => setEdits({ ...edits, [m.id]: { ...edits[m.id], ...patch } });
  return (
    <div className="col">
      <span className="faint small">{t('lora.models_hint')}</span>
      {models.length === 0 && <div className="faint">{t('lora.no_models')}</div>}
      {models.map((m) => (
        <div key={m.id} className="compose-card">
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <input value={value(m, 'name')} onChange={(e) => edit(m, { name: e.target.value })} />
            <span className="faint mono small grow">{m.file}</span>
            {m.source?.run && (
              <span className="chip small">
                {m.source.run} · e{m.source.epoch}
              </span>
            )}
            {m.source?.external && <span className="chip small">{t('lora.external')}</span>}
          </div>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            <label className="row" style={{ gap: 4 }}>
              <span className="muted">{t('gen.lora_strength')}</span>
              <input type="number" step={0.05} style={{ width: 72 }} value={value(m, 'strength')} onChange={(e) => edit(m, { strength: Number(e.target.value) })} />
            </label>
            <label className="row" style={{ gap: 4 }}>
              <input type="checkbox" checked={value(m, 'auto_apply')} onChange={(e) => edit(m, { auto_apply: e.target.checked })} />
              {t('lora.auto_apply')}
            </label>
            <select value={value(m, 'apply_to')} onChange={(e) => edit(m, { apply_to: e.target.value as Model['apply_to'] })}>
              <option value="character">{t('lora.apply.character')}</option>
              <option value="outfit">{t('lora.apply.outfit')}</option>
            </select>
            {value(m, 'apply_to') === 'outfit' && (
              <select value={value(m, 'outfit_id') ?? ''} onChange={(e) => edit(m, { outfit_id: e.target.value })}>
                <option value="">—</option>
                {design.outfits.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            )}
            <select value={value(m, 'model_family')} onChange={(e) => edit(m, { model_family: e.target.value })}>
              {['anima', 'sdxl', 'shared'].map((f) => (
                <option key={f} value={f}>
                  {t(`lora.family.${f}`)}
                </option>
              ))}
            </select>
            <label className="row" style={{ gap: 4 }}>
              <input type="checkbox" checked={value(m, 'enabled')} onChange={(e) => edit(m, { enabled: e.target.checked })} />
              {t('lora.enabled')}
            </label>
            <span className="grow" />
            <button
              className="primary"
              disabled={!edits[m.id]}
              onClick={() => act(() => put(`${base}/models/${m.id}`, edits[m.id]), t('common.saved')).then((r) => r && setEdits({ ...edits, [m.id]: undefined as any }))}
            >
              {t('common.save')}
            </button>
            <button className="danger" onClick={() => confirm(t('lora.remove_confirm', { name: m.name })) && act(() => del(`${base}/models/${m.id}`))}>
              {t('lora.remove')}
            </button>
          </div>
        </div>
      ))}
      <div className="section-title">{t('lora.add_external')}</div>
      <div className="row">
        <select value={external} onChange={(e) => setExternal(e.target.value)}>
          <option value="">{t('lora.choose_file')}</option>
          {loras.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <button disabled={!external} onClick={() => act(() => post(`${base}/models`, { file: external }), t('lora.added')).then((saved) => saved !== undefined && setExternal(''))}>
          {t('lora.add')}
        </button>
      </div>
      <span className="faint small">{t('lora.external_hint')}</span>
    </div>
  );
}
