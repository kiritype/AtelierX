import { useQuery, useQueryClient } from '@tanstack/react-query';
import LabImport from './LabImport';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, get, post, put } from '../../api';
import { t, tm, msgText } from '../../i18n';
import { useToast } from '../Toasts';
import GenSettings, { FAMILY_DEFAULTS, useCatalog, type GenerationSettings } from './GenSettings';

type Cell = {
  row: number;
  column: number;
  seed: number;
  status: string;
  lab_variant?: any;
  image_url?: string;
  path?: string;
  error?: any;
};
type Run = { id: string; created_at: string; sweep?: string; source?: string; source_url?: string; rows: number; columns: number; cells: Cell[] };
type Preset = { id: string; name: string; service: string; family: 'anima' | 'sdxl'; settings: GenerationSettings };
type Draft = { positive: string; negative: string; settings: GenerationSettings; source?: string | null; compareFiles?: string[] };
type Side = { url: string; label: string; path?: string };

const DRAFT_KEY = 'atelierx-lab-draft';
const HANDOFF_KEY = 'atelierx-lab-handoff';
const SWEEPS = ['cfg', 'steps', 'sampler', 'scheduler', 'clip_skip', 'lora_strength', 'lora_file', 'artist'] as const;
const MAX_JOBS = 48;

function readStore(store: Storage, key: string) {
  try {
    const raw = store.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
function writeStore(store: Storage, key: string, value: unknown) {
  try {
    if (value === null) store.removeItem(key);
    else store.setItem(key, JSON.stringify(value));
  } catch {
    // Storage may be unavailable; the screen still works without it.
  }
}

// Other screens (gallery) hand a prompt and settings over, then open the lab view.
// An open lab tab takes it from the event; a lab opened later reads it from session storage.
export function sendToLab(draft: Draft) {
  writeStore(sessionStorage, HANDOFF_KEY, draft);
  window.dispatchEvent(new CustomEvent(HANDOFF_KEY));
}

export function compareLorasInLab(files: string[], positive: string, model: string) {
  const saved = readStore(localStorage, DRAFT_KEY);
  sendToLab({
    positive, negative: saved?.negative ?? '',
    settings: { ...FAMILY_DEFAULTS.anima, ...(saved?.settings?.family === 'anima' ? saved.settings : {}), family: 'anima', model, loras: [] },
    compareFiles: files,
  });
}

// Image menu → Generate & compare: one prompt with several seeds, or one changing value compared side by side.
export default function ImageLab({ workId }: { workId?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const catalog = useCatalog();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const [importing, setImporting] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(() => {
    const handoff = readStore(sessionStorage, HANDOFF_KEY);
    writeStore(sessionStorage, HANDOFF_KEY, null);
    return handoff ?? readStore(localStorage, DRAFT_KEY) ?? { positive: '', negative: '', settings: { family: 'anima', ...FAMILY_DEFAULTS.anima, seed: -1 } };
  });
  const [mode, setMode] = useState<'single' | 'compare'>(draft.compareFiles ? 'compare' : 'single');
  const [count, setCount] = useState(draft.compareFiles ? 1 : 4);
  const [sweepKey, setSweepKey] = useState<(typeof SWEEPS)[number]>(draft.compareFiles ? 'lora_file' : 'cfg');
  const [files, setFiles] = useState<string[]>(draft.compareFiles ?? []);
  const [fileSearch, setFileSearch] = useState('');
  const [values, setValues] = useState('4\n5\n6');
  const [baseline, setBaseline] = useState(true);
  const [loraIndex, setLoraIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState('');
  const [reference, setReference] = useState<Side | null>(null);
  const [result, setResult] = useState<Side | null>(null);
  const [view, setView] = useState<'side' | 'slider'>('side');
  const [slider, setSlider] = useState(50);
  const [tagReport, setTagReport] = useState<string | null>(null);

  useEffect(() => writeStore(localStorage, DRAFT_KEY, { ...draft, source: null, compareFiles: undefined }), [draft]);
  useEffect(() => {
    const take = () => {
      const handoff = readStore(sessionStorage, HANDOFF_KEY);
      writeStore(sessionStorage, HANDOFF_KEY, null);
      if (handoff) {
        setDraft(handoff);
        if (handoff.compareFiles) {
          setMode('compare'); setSweepKey('lora_file'); setFiles(handoff.compareFiles); setCount(1); setLoraIndex(0);
        }
      }
    };
    window.addEventListener(HANDOFF_KEY, take);
    return () => window.removeEventListener(HANDOFF_KEY, take);
  }, []);

  const presets = useQuery<Preset[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets') });
  const runs = useQuery<{ runs: Run[] }>({ queryKey: ['lab-runs'], queryFn: () => get('/api/image/lab/runs'), refetchInterval: 2000 });
  const run = runs.data?.runs.find((r) => r.id === runId) ?? runs.data?.runs[0];

  // A new run starts with its reference image (the gallery original) and its first finished cell.
  useEffect(() => {
    if (!run) return;
    const done = run.cells.filter((c) => c.image_url);
    setReference((current) => current ?? (run.source_url ? { url: run.source_url, label: t('lab.original') } : done[0] ? side(done[0]) : null));
    const candidate = !run.source_url && run.cells.length > 1 ? done[1] : done[0];
    setResult((current) => current ?? (candidate ? side(candidate) : null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.cells.filter((c) => c.image_url).length]);

  const valueList = useMemo(() => {
    if (sweepKey === 'lora_file') return files;
    const list = values
      .split('\n')
      .map((v) => v.trim())
      .filter(Boolean);
    return sweepKey === 'artist' && baseline ? ['', ...list] : list;
  }, [values, sweepKey, baseline, files]);
  const columns = mode === 'compare' ? valueList.length : 1;
  const total = count * columns;
  const availableFiles = (catalog.data?.loras ?? []).filter((file) => {
    const family = catalog.data?.families?.loras?.[file];
    return !family || family === (draft.settings.family ?? 'anima');
  });
  const visibleFiles = [...new Set([...files, ...availableFiles])].filter(
    (file) => files.includes(file) || file.toLowerCase().includes(fileSearch.toLowerCase()),
  );

  async function runLab() {
    setBusy(true);
    try {
      const body: any = { positive: draft.positive, negative: draft.negative, settings: draft.settings, count, source: draft.source ?? undefined };
      if (mode === 'compare') body.sweep = { key: sweepKey, values: valueList, lora_index: loraIndex };
      const queued = await post('/api/image/lab', body);
      toast({ text: t('lab.queued', { n: queued.count }) });
      setRunId(queued.lab_group);
      setReference(null);
      setResult(null);
      qc.invalidateQueries({ queryKey: ['lab-runs'] });
      qc.invalidateQueries({ queryKey: ['image-queue'] });
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function checkTags() {
    try {
      const tags = draft.positive
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean);
      const checked = await post('/api/image/tags/check', { tags });
      const odd = checked.tags.filter((x: any) => x.status !== 'ok');
      setTagReport(odd.length ? odd.map((x: any) => (x.status === 'alias' ? `${x.tag} → ${x.alias_of.tag}` : `${x.tag} ?`)).join(', ') : t('lab.tags_ok'));
    } catch (err) {
      fail(err);
    }
  }

  async function useRecord(path: string) {
    try {
      const detail = await get(`/api/image/gallery/detail?path=${encodeURIComponent(path)}`);
      const record = detail.record;
      if (!record) throw new Error(t('lab.no_record'));
      setDraft({ ...draft, positive: record.positive ?? '', negative: record.negative ?? '', settings: { ...record.settings } });
      toast({ text: t('lab.loaded_result') });
    } catch (err) {
      fail(err);
    }
  }

  async function savePreset() {
    const id = prompt(t('lab.preset_id'));
    if (!id) return;
    try {
      // Saving over a style preset keeps its artist tags, tags and common picks (#169).
      const existing = presets.data?.find((p) => p.id === id);
      await put(`/api/image/presets/${encodeURIComponent(id)}`, { ...existing, name: existing?.name ?? id, service: 'comfyui', family: draft.settings.family ?? 'anima', settings: { ...draft.settings, seed: -1 } });
      qc.invalidateQueries({ queryKey: ['image-presets'] });
      toast({ text: t('lab.preset_saved', { id }) });
    } catch (err) {
      fail(err);
    }
  }

  const side = (cell: Cell): Side => ({
    url: cell.image_url!,
    path: cell.path,
    label: cell.lab_variant ? `${msgText(cell.lab_variant) || t('lab.baseline')} · ${t('lab.seed_n', { seed: cell.seed })}` : t('lab.seed_n', { seed: cell.seed }),
  });

  return (
    <div className="lab-wrap">
      <div className="lab">
        <div className="lab-form pad col">
          <div className="seg" style={{ alignSelf: 'flex-start' }}>
            {(['single', 'compare'] as const).map((m) => (
              <button key={m} className={mode === m ? 'on' : ''} onClick={() => setMode(m)}>
                {t(`lab.mode.${m}`)}
              </button>
            ))}
          </div>
          {draft.source && (
            <div className="row faint small">
              {t('lab.from_gallery')}: <span className="mono">{draft.source}</span>
              <button className="ghost" onClick={() => setDraft({ ...draft, source: null })}>
                ×
              </button>
            </div>
          )}
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('lab.positive')}</span>
            <textarea rows={5} className="mono" value={draft.positive} onChange={(e) => setDraft({ ...draft, positive: e.target.value })} />
          </label>
          <div className="row">
            <button className="ghost" onClick={checkTags}>
              {t('lab.check_tags')}
            </button>
            {tagReport && <span className="faint small">{tagReport}</span>}
          </div>
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('lab.negative')}</span>
            <textarea rows={3} className="mono" value={draft.negative} onChange={(e) => setDraft({ ...draft, negative: e.target.value })} />
          </label>
          <div className="row">
            <select
              value=""
              onChange={(e) => {
                const preset = presets.data?.find((p) => p.id === e.target.value);
                if (preset) setDraft({ ...draft, settings: { ...preset.settings, family: preset.family, seed: draft.settings.seed ?? -1 } });
              }}
            >
              <option value="">{t('lab.load_preset')}</option>
              {(presets.data ?? [])
                .filter((p) => p.service === 'comfyui')
                .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button className="ghost" onClick={savePreset}>
              {t('lab.save_preset')}
            </button>
          </div>
          <GenSettings value={draft.settings} onChange={(settings) => setDraft({ ...draft, settings })} />
          <div className="section-title">{mode === 'compare' ? t('lab.compare_values') : t('lab.seeds')}</div>
          {mode === 'compare' && (
            <>
              <label className="row" style={{ gap: 4 }}>
                <span className="muted">{t('lab.value_to_vary')}</span>
                <select value={sweepKey} onChange={(e) => setSweepKey(e.target.value as any)}>
                  {SWEEPS.map((k) => (
                    <option key={k} value={k}>
                      {t(`lab.sweep.${k}`)}
                    </option>
                  ))}
                </select>
                {(sweepKey === 'lora_strength' || sweepKey === 'lora_file') && (
                  <select aria-label={t('lab.lora_slot')} value={loraIndex} onChange={(e) => setLoraIndex(Number(e.target.value))}>
                    {(draft.settings.loras ?? []).map((l, i) => (
                      <option key={i} value={i}>
                        {l.name}
                      </option>
                    ))}
                    {sweepKey === 'lora_file' && <option value={draft.settings.loras?.length ?? 0}>{t('lab.lora_new_slot')}</option>}
                  </select>
                )}
              </label>
              {sweepKey === 'lora_file' ? (
                <div className="col">
                  <span className="faint small">{t('lab.lora_files_hint')}</span>
                  <input aria-label={t('lab.lora_search')} placeholder={t('lab.lora_search')} value={fileSearch} onChange={(e) => setFileSearch(e.target.value)} />
                  <div className="col" style={{ maxHeight: 180, overflowY: 'auto', gap: 4 }}>
                    {visibleFiles.map((file) => (
                      <label key={file} className="row small" style={{ gap: 4 }}>
                        <input type="checkbox" checked={files.includes(file)} onChange={(e) => setFiles(e.target.checked ? [...files, file] : files.filter((f) => f !== file))} />
                        {file}
                      </label>
                    ))}
                  </div>
                </div>
              ) : <label className="col" style={{ gap: 2 }}>
                <span className="faint small">{sweepKey === 'artist' ? t('lab.artist_hint') : t('lab.values_hint')}</span>
                <textarea rows={4} className="mono" value={values} onChange={(e) => setValues(e.target.value)} />
              </label>}
              {sweepKey === 'artist' && (
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={baseline} onChange={(e) => setBaseline(e.target.checked)} />
                  {t('lab.include_baseline')}
                </label>
              )}
            </>
          )}
          <div className="row" style={{ alignItems: 'flex-end' }}>
            <label className="col" style={{ gap: 2 }}>
              <span className="muted">{t('lab.seed_count')}</span>
              <input type="number" min={1} max={16} style={{ width: 72 }} value={count} onChange={(e) => setCount(Number(e.target.value))} />
            </label>
            <span className={`grow small ${total > MAX_JOBS ? 'error-text' : 'faint'}`}>
              {mode === 'compare' ? t('lab.total_compare', { seeds: count, values: columns, n: total }) : t('lab.total_single', { n: total })}
              {(draft.settings.seed ?? -1) !== -1 && ` · ${t('lab.fixed_seed_note')}`}
            </span>
            <button className="primary" disabled={busy || !draft.positive.trim() || total > MAX_JOBS || (mode === 'compare' && (columns < 2 || columns > 12))} onClick={runLab}>
              {t('lab.run')}
            </button>
          </div>
        </div>

        <div className="lab-view pad col">
          <div className="row">
            <select value={run?.id ?? ''} onChange={(e) => (setRunId(e.target.value), setReference(null), setResult(null))}>
              {!runs.data?.runs.length && <option value="">{t('lab.no_runs')}</option>}
              {(runs.data?.runs ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {new Date(r.created_at).toLocaleString()} · {t('lab.run_size', { n: r.cells.length })}
                  {r.sweep ? ` · ${t(`lab.sweep.${r.sweep}`)}` : ''}
                </option>
              ))}
            </select>
            <span className="grow" />
            <div className="seg">
              {(['side', 'slider'] as const).map((v) => (
                <button key={v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>
                  {t(`lab.view.${v}`)}
                </button>
              ))}
            </div>
          </div>

          {view === 'slider' && reference && result ? (
            <div className="lab-slider">
              <div className="lab-frame">
                <img src={reference.url} alt="" />
                <img src={result.url} alt="" className="lab-over" style={{ clipPath: `inset(0 0 0 ${slider}%)` }} />
                <div className="lab-line" style={{ left: `${slider}%` }} />
              </div>
              <input type="range" min={0} max={100} value={slider} onChange={(e) => setSlider(Number(e.target.value))} aria-label={t('lab.slider_label')} />
              <div className="faint small">{t('lab.slider_caption', { left: reference.label, right: result.label })}</div>
            </div>
          ) : (
            <div className="lab-pair">
              {[
                [reference, t('lab.reference')],
                [result, t('lab.result')],
              ].map(([s, title]: any) => (
                <figure key={title} className="lab-figure">
                  {s ? <img src={s.url} alt="" /> : <div className="lab-empty">{t('lab.pick_hint')}</div>}
                  <figcaption>
                    {title} · {s?.label ?? '—'}
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
          <div className="row">
            {result?.path && (
              <button className="ghost" onClick={() => useRecord(result.path!)}>
                {t('lab.use_result_settings')}
              </button>
            )}
            {result?.path && workId && (
              <button className="ghost" onClick={() => setImporting(importing === result.path ? null : result.path!)}>
                {t('lab.import_title')}
              </button>
            )}
            {reference && result && (
              <button className="ghost" onClick={() => (setReference(result), setResult(reference))}>
                {t('lab.swap')}
              </button>
            )}
          </div>

          {importing && workId && <LabImport key={importing} workId={workId} path={importing} onDone={() => setImporting(null)} />}

          {run && (
            <div className="lab-grid" style={{ gridTemplateColumns: `72px repeat(${run.columns}, minmax(110px, 1fr))` }}>
              <div className="lab-head faint">{t('lab.seed_column')}</div>
              {Array.from({ length: run.columns }, (_, column) => {
                const any = run.cells.find((c) => c.column === column);
                return (
                  <div key={column} className="lab-head">
                    {run.columns > 1 ? msgText(any?.lab_variant) || t('lab.baseline') : ''}
                  </div>
                );
              })}
              {Array.from({ length: run.rows }, (_, row) => {
                const rowCells = run.cells.filter((c) => c.row === row);
                return [
                  <div key={`s${row}`} className="lab-head faint mono small">
                    {rowCells[0]?.seed ?? ''}
                  </div>,
                  ...Array.from({ length: run.columns }, (_, column) => {
                    const cell = rowCells.find((c) => c.column === column);
                    if (!cell) return <div key={`${row}-${column}`} className="lab-cell empty" />;
                    const picked = result?.url === cell.image_url;
                    const isRef = reference?.url === cell.image_url;
                    return (
                      <div key={`${row}-${column}`} className={`lab-cell ${picked ? 'picked' : ''} ${isRef ? 'ref' : ''}`}>
                        {cell.image_url ? (
                          <img src={cell.image_url} alt="" loading="lazy" onClick={() => setResult(side(cell))} />
                        ) : (
                          <div className="lab-empty small" title={msgText(cell.error)}>
                            {t(`queue.status.${cell.status}`)}
                          </div>
                        )}
                        {cell.image_url && (
                          <button className="ghost small" onClick={() => setReference(side(cell))}>
                            {t('lab.set_reference')}
                          </button>
                        )}
                      </div>
                    );
                  }),
                ];
              })}
            </div>
          )}
          <p className="faint small">{t('lab.grid_hint')}</p>
        </div>
      </div>
    </div>
  );
}
