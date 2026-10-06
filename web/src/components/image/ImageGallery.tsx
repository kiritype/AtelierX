import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, get, post, put, q } from '../../api';
import { PRESET_ID, presetFromRecord } from '../../lib/presetFromRecord';
import { t, tm } from '../../i18n';
import { SERVICE_NAMES } from './serviceSettings';
import { useToast } from '../Toasts';
import { sendToLab } from './ImageLab';
import { DeploymentExport } from './DeploymentExport';
import { DeployUpload } from './DeployUpload';

export type GalleryItem = {
  path: string;
  filename: string;
  folder: string;
  kind: 'image' | 'lab' | 'tool' | 'other';
  image_url: string;
  thumbnail_url: string;
  has_record: boolean;
  work_id: string;
  character_id: string;
  outfit_id: string;
  expression_id: string;
  outfit_name: string;
  expression_name: string;
  rating: string;
  model_family: string;
  service?: string;
  seed?: number;
  postprocessed: boolean;
  created_at: string;
  sha256: string;
  human_status: 'pass' | 'fail' | 'unreviewed';
  note: string;
  auto_status: 'pending' | 'pass' | 'fail' | 'uncertain' | 'error';
  auto_reason: string;
  adopted: boolean;
};
type Page = {
  results: GalleryItem[];
  total: number;
  page: number;
  pages: number;
  snapshot: string;
  newer: number;
  paths?: string[];
};
type Tree = {
  works: {
    id: string;
    count: number;
    characters: {
      id: string;
      count: number;
      outfits: { id: string; name: string; count: number }[];
    }[];
  }[];
  expressions: { id: string; name: string; rating: string; count: number }[];
  folders: { path: string; count: number }[];
  revision: number;
};
type Round = {
  id: string;
  status: string;
  combo: string[];
  expression_name?: string;
  outfit_name?: string;
  regenerations: number;
  max_auto_regenerations: number;
  attempts: { verdict: string; evidence: any; path: string }[];
  error?: any;
};
type Scope = {
  work?: string;
  character?: string;
  outfit?: string;
  folder?: string;
};

const msg = (value: any) => (value && typeof value === 'object' ? tm(value) : String(value ?? ''));
const HUMAN_MARK: Record<string, string> = {
  pass: '✓',
  fail: '✗',
  unreviewed: '',
};
const OPEN_ROUNDS = ['waiting_generation', 'pending_review', 'reviewing'];
const REASONS = ['hands', 'face', 'outfit', 'composition', 'other'];

// Image menu → Gallery: browse by work / character / outfit, review (pass adopts), regenerate, export adopted images.
export default function ImageGallery({ workId, openLab, openTools, characterId, outfitId }: { workId: string; openLab: () => void; openTools: () => void; characterId?: string; outfitId?: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [scope, setScope] = useState<Scope>({ work: workId, character: characterId, outfit: outfitId });
  const [filters, setFilters] = useState({
    expression: '',
    rating: '',
    human_status: '',
    auto_status: '',
    adopted: false,
    latest: false,
    sort: 'newest',
  });
  const [page, setPage] = useState(1);
  const [snapshot, setSnapshot] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [showRounds, setShowRounds] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams({
      page: String(page),
      page_size: '60',
      sort: filters.sort,
    });
    for (const [k, v] of Object.entries({
      ...scope,
      expression: filters.expression,
      rating: filters.rating,
      human_status: filters.human_status,
      auto_status: filters.auto_status,
    }))
      if (v) p.set(k, v);
    if (filters.adopted) p.set('adopted', '1');
    if (filters.latest) p.set('latest', '1');
    if (snapshot) p.set('snapshot', snapshot);
    return p.toString();
  }, [scope, filters, page, snapshot]);

  const tree = useQuery<Tree>({
    queryKey: ['gallery-tree'],
    queryFn: () => get('/api/image/gallery/tree'),
    refetchInterval: 5000,
  });
  const list = useQuery<Page>({
    queryKey: ['gallery', params],
    queryFn: () => get(`/api/image/gallery?${params}`),
    placeholderData: (prev) => prev,
    refetchInterval: 5000,
  });
  const rounds = useQuery<{ rounds: Round[]; enabled: boolean }>({
    queryKey: ['review-rounds'],
    queryFn: () => get('/api/image/review/rounds'),
    refetchInterval: 4000,
  });
  const designs = useQuery<{ id: string; name: string }[]>({
    queryKey: ['image-designs', workId],
    queryFn: () => get(`/api/works/${workId}/image/designs`),
  });
  const names = useMemo(() => Object.fromEntries((designs.data ?? []).map((d) => [d.id, d.name])), [designs.data]);

  // The page keeps its snapshot so paging is stable; new images show as a refresh hint.
  useEffect(() => {
    // Placeholder data is the previous page and carries the old snapshot.
    if (list.data && !list.isPlaceholderData && !snapshot) setSnapshot(list.data.snapshot);
  }, [list.data, list.isPlaceholderData, snapshot]);
  const newer = list.data?.newer ?? 0;
  const refresh = () => {
    setSnapshot('');
    qc.invalidateQueries({ queryKey: ['gallery'] });
  };
  const changeScope = (next: Scope) => {
    setScope(next);
    setPage(1);
    setSnapshot('');
    setSelected(new Set());
  };
  const changeFilter = (patch: Partial<typeof filters>) => {
    setFilters({ ...filters, ...patch });
    setPage(1);
    setSnapshot('');
  };

  const fail = (err: unknown) =>
    toast({
      text: err instanceof ApiError ? tm(err.msg) : String(err),
      tone: 'error',
    });
  const reload = () => {
    qc.invalidateQueries({ queryKey: ['gallery'] });
    qc.invalidateQueries({ queryKey: ['gallery-detail'] });
    qc.invalidateQueries({ queryKey: ['review-rounds'] });
  };
  const review = useCallback(
    async (paths: string[], verdict: string, note?: string) => {
      try {
        const result = await post('/api/image/gallery/review', {
          verdict,
          items: paths.map((path) => ({ path })),
          ...(note !== undefined ? { note } : {}),
        });
        reload();
        return result;
      } catch (err) {
        fail(err);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const regenerate = async (paths: string[]) => {
    try {
      const result = await post('/api/image/gallery/regenerate', {
        items: paths,
      });
      toast({
        text: t('gallery.regenerated', { n: result.count }) + (result.warning ? ` ${msg(result.warning)}` : ''),
      });
      qc.invalidateQueries({ queryKey: ['image-queue'] });
    } catch (err) {
      fail(err);
    }
  };
  // Deleting moves images (with their records) to the output trash, where they can be restored.
  const remove = async (paths: string[]) => {
    if (!paths.length || !confirm(t('gallery.delete_confirm', { n: paths.length }))) return false;
    try {
      const result = await post('/api/image/gallery/delete', { paths });
      toast({ text: t('gallery.deleted', { n: result.deleted }), action: { label: t('gallery.trash'), run: () => setTrashOpen(true) } });
      setSelected(new Set());
      reload();
      qc.invalidateQueries({ queryKey: ['gallery-tree'] });
      qc.invalidateQueries({ queryKey: ['tool-items'] });
      return true;
    } catch (err) {
      fail(err);
      return false;
    }
  };
  const selectAllFiltered = async () => {
    const all = await get<Page>(`/api/image/gallery?${params}&paths_only=1`);
    setSelected(new Set(all.paths ?? []));
  };

  const results = list.data?.results ?? [];
  const chosen = [...selected];
  const toggle = (path: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(path);
    else next.delete(path);
    setSelected(next);
  };
  const openRounds = (rounds.data?.rounds ?? []).filter((r) => OPEN_ROUNDS.includes(r.status)).length;
  const attention = (rounds.data?.rounds ?? []).filter((r) => r.status === 'needs_attention' || r.status === 'limit_reached').length;

  return (
    <div className="gallery">
      <aside className="gallery-tree pad col">
        <button className={`tree-link ${!scope.work && !scope.folder ? 'on' : ''}`} onClick={() => changeScope({})}>
          {t('gallery.all_images')}
        </button>
        {(tree.data?.works ?? []).map((w) => (
          <div key={w.id} className="col" style={{ gap: 1 }}>
            <button className={`tree-link ${scope.work === w.id && !scope.character ? 'on' : ''}`} onClick={() => changeScope({ work: w.id })}>
              {w.id === workId ? t('gallery.this_work') : w.id} <span className="faint">{w.count}</span>
            </button>
            {w.characters.map((c) => (
              <div key={c.id} className="col" style={{ gap: 1, paddingLeft: 12 }}>
                <button
                  className={`tree-link ${scope.work === w.id && scope.character === c.id && !scope.outfit ? 'on' : ''}`}
                  onClick={() => changeScope({ work: w.id, character: c.id })}
                >
                  {(w.id === workId && names[c.id]) || c.id} <span className="faint">{c.count}</span>
                </button>
                {c.outfits.map((o) => (
                  <button
                    key={o.id}
                    style={{ paddingLeft: 24 }}
                    className={`tree-link ${scope.character === c.id && scope.outfit === o.id ? 'on' : ''}`}
                    onClick={() => changeScope({ work: w.id, character: c.id, outfit: o.id })}
                  >
                    {o.name || o.id} <span className="faint">{o.count}</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        ))}
        {(tree.data?.folders ?? []).length > 0 && <div className="section-title">{t('gallery.other_folders')}</div>}
        {(tree.data?.folders ?? []).map((f) => (
          <button
            key={f.path}
            className={`tree-link ${scope.folder === f.path ? 'on' : ''}`}
            style={{ paddingLeft: 4 + 12 * (f.path.split('/').length - 1) }}
            onClick={() => changeScope({ folder: f.path })}
          >
            {f.path.split('/').pop()} <span className="faint">{f.count}</span>
          </button>
        ))}
      </aside>

      <div className="gallery-main col">
        <div className="gallery-toolbar row">
          <select value={filters.expression} onChange={(e) => changeFilter({ expression: e.target.value })}>
            <option value="">{t('gallery.all_expressions')}</option>
            {(tree.data?.expressions ?? []).map((x) => (
              <option key={x.id} value={x.id}>
                {x.name || x.id} ({x.count})
              </option>
            ))}
          </select>
          <select value={filters.human_status} onChange={(e) => changeFilter({ human_status: e.target.value })}>
            <option value="">
              {t('gallery.my_verdict')}: {t('gallery.all')}
            </option>
            {['unreviewed', 'pass', 'fail'].map((s) => (
              <option key={s} value={s}>
                {t(`gallery.human.${s}`)}
              </option>
            ))}
          </select>
          <select value={filters.auto_status} onChange={(e) => changeFilter({ auto_status: e.target.value })}>
            <option value="">
              {t('gallery.vlm_verdict')}: {t('gallery.all')}
            </option>
            {['pending', 'pass', 'fail', 'uncertain', 'error'].map((s) => (
              <option key={s} value={s}>
                {t(`gallery.auto.${s}`)}
              </option>
            ))}
          </select>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={filters.adopted} onChange={(e) => changeFilter({ adopted: e.target.checked })} />
            {t('gallery.adopted_only')}
          </label>
          <label className="row" style={{ gap: 4 }} title={t('gallery.latest_hint')}>
            <input type="checkbox" checked={filters.latest} onChange={(e) => changeFilter({ latest: e.target.checked })} />
            {t('gallery.latest')}
          </label>
          <select value={filters.sort} onChange={(e) => changeFilter({ sort: e.target.value })}>
            {['newest', 'oldest', 'code'].map((s) => (
              <option key={s} value={s}>
                {t(`gallery.sort.${s}`)}
              </option>
            ))}
          </select>
          <span className="grow" />
          {newer > 0 && (
            <button className="primary" onClick={refresh}>
              {t('gallery.new_images', { n: newer })}
            </button>
          )}
          <button onClick={() => setShowRounds(!showRounds)} className={showRounds ? 'on' : ''}>
            {t('gallery.rounds')}
            {openRounds + attention > 0 && <span className="chip accent">{openRounds + attention}</span>}
          </button>
          <button onClick={() => setExporting(true)}>{t('gallery.export')}</button>
          <button onClick={() => setUploading(true)}>{t('deploy.upload_title')}</button>
          <button onClick={() => setTrashOpen(true)}>{t('gallery.trash')}</button>
        </div>

        <div className="gallery-toolbar row">
          <span className="faint">{t('gallery.count', { n: list.data?.total ?? 0 })}</span>
          <button className="ghost" onClick={() => setSelected(new Set([...selected, ...results.map((r) => r.path)]))}>
            {t('gallery.select_page')}
          </button>
          <button className="ghost" onClick={selectAllFiltered}>
            {t('gallery.select_all')}
          </button>
          {selected.size > 0 && (
            <>
              <strong>{t('gallery.selected', { n: selected.size })}</strong>
              <button onClick={() => review(chosen, 'pass')}>{t('gallery.pass')}</button>
              <button onClick={() => review(chosen, 'fail')}>{t('gallery.fail')}</button>
              <button onClick={() => review(chosen, 'unreviewed')}>{t('gallery.unreview')}</button>
              <button onClick={() => regenerate(chosen.slice(0, 200))}>{t('gallery.regenerate')}</button>
              <button
                onClick={async () => {
                  try {
                    const result = await post('/api/image/tools/gallery', { paths: chosen.slice(0, 500) });
                    toast({ text: t('gallery.sent_to_tools', { n: result.added.length }), action: { label: t('image_menu.tools'), run: openTools } });
                    qc.invalidateQueries({ queryKey: ['tool-items'] });
                  } catch (err) {
                    fail(err);
                  }
                }}
              >
                {t('gallery.send_to_tools')}
              </button>
              <button className="danger" onClick={() => remove(chosen)}>
                {t('gallery.delete')}
              </button>
              <button className="ghost" onClick={() => setSelected(new Set())}>
                {t('gallery.clear_selection')}
              </button>
            </>
          )}
        </div>

        <div className="gallery-scroll">
          {showRounds && <RoundsPanel data={rounds.data} names={names} onChange={reload} fail={fail} />}

          <div className="gallery-grid">
            {results.map((item, index) => (
              <div key={item.path} className={`gallery-cell ${selected.has(item.path) ? 'selected' : ''} human-${item.human_status}`}>
                <button className="gallery-open" onClick={() => setOpen(index)}>
                  <img src={item.thumbnail_url} alt="" loading="lazy" />
                  <span className="gallery-caption" title={item.path}>
                    {item.kind === 'image'
                      ? `${(item.work_id === workId && names[item.character_id]) || item.character_id} · ${item.expression_name || item.expression_id}`
                      : item.filename}
                  </span>
                </button>
                <input aria-label={item.path} type="checkbox" className="gallery-check" checked={selected.has(item.path)} onChange={(e) => toggle(item.path, e.target.checked)} />
                <div className="gallery-badges">
                  {item.service && item.service !== 'comfyui' && <span className="badge service">{SERVICE_NAMES[item.service] ?? item.service}</span>}
                  {item.adopted && (
                    <span className="badge adopted" title={t('gallery.adopted')}>
                      ★
                    </span>
                  )}
                  {HUMAN_MARK[item.human_status] && <span className={`badge human-${item.human_status}`}>{HUMAN_MARK[item.human_status]}</span>}
                  {item.auto_status !== 'pending' && (
                    <span className={`badge auto-${item.auto_status}`} title={`${t('gallery.vlm_verdict')}: ${t(`gallery.auto.${item.auto_status}`)}`}>
                      AI
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
          {results.length === 0 && !list.isLoading && <div className="empty">{t('gallery.empty')}</div>}
          {(list.data?.pages ?? 0) > 1 && (
            <div className="row" style={{ justifyContent: 'center', padding: 8 }}>
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
                ‹
              </button>
              <span>
                {page} / {list.data?.pages}
              </span>
              <button disabled={page >= (list.data?.pages ?? 1)} onClick={() => setPage(page + 1)}>
                ›
              </button>
            </div>
          )}
        </div>
      </div>

      {open !== null && results[open] && (
        <Detail
          item={results[open]}
          names={names}
          workId={workId}
          hasPrev={open > 0}
          hasNext={open < results.length - 1}
          move={(step) => setOpen(open + step)}
          close={() => setOpen(null)}
          review={review}
          regenerate={regenerate}
          openLab={openLab}
          remove={(paths) => remove(paths).then((done) => done && setOpen(null))}
        />
      )}
      {exporting && <DeploymentExport scope={scope} close={() => setExporting(false)} fail={fail} />}
      {uploading && <DeployUpload scope={scope} close={() => setUploading(false)} fail={fail} />}
      {trashOpen && <TrashDialog close={() => setTrashOpen(false)} fail={fail} onChange={reload} />}
    </div>
  );
}

function Detail({
  item,
  names,
  workId,
  hasPrev,
  hasNext,
  move,
  close,
  review,
  regenerate,
  openLab,
  remove,
}: {
  item: GalleryItem;
  names: Record<string, string>;
  workId: string;
  hasPrev: boolean;
  hasNext: boolean;
  move: (step: number) => void;
  close: () => void;
  review: (paths: string[], verdict: string, note?: string) => Promise<any>;
  regenerate: (paths: string[]) => void;
  openLab: () => void;
  remove: (paths: string[]) => void;
}) {
  const toast = useToast();
  const detail = useQuery<any>({
    queryKey: ['gallery-detail', item.path],
    queryFn: () => get(`/api/image/gallery/detail?path=${q(item.path)}`),
  });
  const [note, setNote] = useState<string | null>(null);
  const record = detail.data?.record;
  const data = detail.data ?? item;

  useEffect(() => setNote(null), [item.path]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['TEXTAREA', 'INPUT'].includes((e.target as HTMLElement)?.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === 'escape') close();
      else if (key === 'arrowleft' && hasPrev) move(-1);
      else if (key === 'arrowright' && hasNext) move(1);
      else if (key === '1' || key === 'p') review([item.path], 'pass');
      else if (key === '2' || key === 'f') review([item.path], 'fail');
      else if (key === '3' || key === 'u') review([item.path], 'unreviewed');
      else if (key === 'r' && item.has_record) regenerate([item.path]);
      else return;
      e.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [item.path, item.has_record, hasPrev, hasNext, move, close, review, regenerate]);

  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast({ text: t('gallery.copied') });
  };
  const settings = record?.settings ?? {};

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="gallery-detail">
        <div className="gallery-detail-image">
          <img src={item.image_url} alt="" />
          {hasPrev && (
            <button className="nav prev" onClick={() => move(-1)} title={t('gallery.prev')}>
              ‹
            </button>
          )}
          {hasNext && (
            <button className="nav next" onClick={() => move(1)} title={t('gallery.next')}>
              ›
            </button>
          )}
        </div>
        <div className="gallery-detail-side col pad">
          <div className="row">
            <strong className="grow">
              {item.kind === 'image'
                ? `${(item.work_id === workId && names[item.character_id]) || item.character_id} · ${item.outfit_name || item.outfit_id} · ${item.expression_name || item.expression_id}`
                : item.filename}
            </strong>
            <button className="ghost" onClick={close}>
              ×
            </button>
          </div>
          <div className="faint mono small">{item.path}</div>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {(['pass', 'fail', 'unreviewed'] as const).map((v, n) => (
              <button key={v} className={data.human_status === v ? 'primary' : ''} onClick={() => review([item.path], v)}>
                {t(`gallery.human.${v}`)} <span className="faint">{n + 1}</span>
              </button>
            ))}
            {record && (
              <button
                onClick={() => {
                  sendToLab({ positive: record.positive ?? '', negative: record.negative ?? '', settings: { ...record.settings, seed: -1 }, source: item.path });
                  openLab();
                }}
              >
                {t('gallery.open_in_lab')}
              </button>
            )}
            {record && (
              <button onClick={() => regenerate([item.path])}>
                {t('gallery.regenerate')} <span className="faint">R</span>
              </button>
            )}
            <button className="danger" onClick={() => remove([item.path])}>
              {t('gallery.delete')}
            </button>
          </div>
          {data.adopted ? (
            <div className="ok-text">★ {t('gallery.adopted_this')}</div>
          ) : (
            detail.data?.adopted_path && item.kind === 'image' && <div className="faint">{t('gallery.adopted_other')}</div>
          )}
          {data.auto_status !== 'pending' && (
            <div className={`auto-box auto-${data.auto_status}`}>
              <strong>
                {t('gallery.vlm_verdict')}: {t(`gallery.auto.${data.auto_status}`)}
              </strong>
              <div>{msg(data.auto_reason)}</div>
              <div className="faint small">{t('gallery.vlm_note')}</div>
            </div>
          )}
          {data.human_status === 'fail' && (
            <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>
              <span className="muted">{t('gallery.fail_reason')}</span>
              {REASONS.map((r) => (
                <button
                  key={r}
                  className="chip"
                  onClick={() => {
                    const current = note ?? data.note ?? '';
                    const label = t(`gallery.reason.${r}`);
                    review([item.path], 'fail', current.includes(label) ? current : [current, label].filter(Boolean).join(', '));
                  }}
                >
                  {t(`gallery.reason.${r}`)}
                </button>
              ))}
            </div>
          )}
          <label className="col" style={{ gap: 2 }}>
            <span className="muted">{t('gallery.note')}</span>
            <textarea rows={2} value={note ?? data.note ?? ''} onChange={(e) => setNote(e.target.value)} />
            {note !== null && note !== (data.note ?? '') && (
              <button style={{ alignSelf: 'flex-start' }} onClick={() => review([item.path], data.human_status, note).then(() => setNote(null))}>
                {t('common.save')}
              </button>
            )}
          </label>
          {!item.has_record && <div className="faint">{t('gallery.no_record')}</div>}
          {record && (
            <>
              <div className="section-title">{t('gallery.prompts')}</div>
              <div className="prompt-box mono small" onClick={() => copy(record.positive)} title={t('gallery.click_copy')}>
                {record.positive}
              </div>
              <div className="prompt-box mono small faint" onClick={() => copy(record.negative)} title={t('gallery.click_copy')}>
                − {record.negative}
              </div>
              <div className="section-title">{t('gallery.settings')}</div>
              <dl className="kv small">
                {[
                  ['gen.model', settings.model],
                  ['gen.family', settings.family],
                  ['gen.sampler', [settings.sampler, settings.scheduler].filter(Boolean).join(' · ')],
                  ['gen.steps', settings.steps],
                  ['CFG', settings.cfg],
                  ['gen.seed', record.seed],
                  ['gallery.size', record.image_size?.join(' × ')],
                  ['gen.loras', (settings.loras ?? []).map((l: any) => `${l.name} (${l.strength ?? l.model_strength ?? 1})`).join(', ')],
                  ['gen.preset', record.generation_preset?.name],
                  ['gallery.created', new Date(record.created_at ?? item.created_at).toLocaleString()],
                ]
                  .filter(([, v]) => v !== undefined && v !== null && v !== '')
                  .map(([k, v]) => (
                    <div key={k} className="row">
                      <dt>{k.includes('.') ? t(k) : k}</dt>
                      <dd className="mono">{String(v)}</dd>
                    </div>
                  ))}
              </dl>
              <div className="row">
                <a href={item.image_url.replace(/\.[^.]+$/, '.json')} target="_blank" rel="noreferrer">
                  {t('gallery.open_record')}
                </a>
              </div>
              <SavePreset key={item.path} record={record} />
            </>
          )}
          {(detail.data?.history ?? []).length > 0 && (
            <>
              <div className="section-title">{t('gallery.history')}</div>
              {detail.data.history
                .slice()
                .reverse()
                .map((h: any, i: number) => (
                  <div key={i} className="faint small">
                    {new Date(h.at).toLocaleString()} · {h.source === 'auto' ? 'AI ' : ''}
                    {h.source === 'auto' ? t(`gallery.auto.${h.from}`) : t(`gallery.human.${h.from}`)} →{' '}
                    {h.source === 'auto' ? t(`gallery.auto.${h.to}`) : t(`gallery.human.${h.to}`)}
                  </div>
                ))}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// Save this image's reusable settings as a generation preset (#52). The panel lists what goes in before saving.
function SavePreset({ record }: { record: any }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const presets = useQuery<{ id: string }[]>({ queryKey: ['image-presets'], queryFn: () => get('/api/image/presets'), enabled: open });
  if (!open) {
    return (
      <div>
        <button onClick={() => setOpen(true)}>{t('gallery.save_preset')}</button>
      </div>
    );
  }
  const draft = presetFromRecord(record);
  const s = draft.settings as Record<string, any>;
  const rows: [string, unknown][] = [
    ['gen.family', draft.family],
    ['gen.model', s.model],
    ['gen.sampler', [s.sampler, s.scheduler].filter(Boolean).join(' · ')],
    ['gen.steps', s.steps],
    ['CFG', s.cfg],
    ['gallery.size', s.width && s.height ? `${s.width} × ${s.height}` : undefined],
    ['gen.loras', (s.loras ?? []).map((l: any) => `${l.name} (${l.strength ?? l.model_strength ?? 1})`).join(', ')],
    ['gallery.preset_common', draft.common.join(', ')],
    ['gallery.preset_styles', draft.styles.join(', ')],
  ];
  const valid = PRESET_ID.test(id);
  async function save() {
    if ((presets.data ?? []).some((p) => p.id === id) && !confirm(t('gallery.preset_overwrite', { id }))) return;
    try {
      await put(`/api/image/presets/${encodeURIComponent(id)}`, {
        name: name.trim() || id,
        family: draft.family,
        settings: draft.settings,
        common: draft.common,
        styles: draft.styles,
      });
      qc.invalidateQueries({ queryKey: ['image-presets'] });
      toast({ text: t('gallery.preset_saved', { name: name.trim() || id }) });
      setOpen(false);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }
  return (
    <div className="col save-preset">
      <div className="section-title">{t('gallery.save_preset')}</div>
      <dl className="kv small">
        {rows
          .filter(([, v]) => v !== undefined && v !== null && v !== '')
          .map(([k, v]) => (
            <div key={k} className="row">
              <dt>{k.includes('.') ? t(k) : k}</dt>
              <dd className="mono">{String(v)}</dd>
            </div>
          ))}
      </dl>
      <p className="faint small">
        {t('gallery.preset_left_out')}
        {draft.droppedLoras.length > 0 && ` ${t('gallery.preset_left_loras', { names: draft.droppedLoras.join(', ') })}`}
      </p>
      <div className="row wrap">
        <input aria-label={t('gallery.preset_id')} placeholder={t('gallery.preset_id')} value={id} onChange={(e) => setId(e.target.value.trim())} style={{ width: 140 }} />
        <input aria-label={t('gallery.preset_name')} placeholder={t('gallery.preset_name')} value={name} onChange={(e) => setName(e.target.value)} className="grow" />
      </div>
      {id && !valid && <span className="error-text small">{t('gallery.preset_id_rule')}</span>}
      <div className="row">
        <button className="primary" disabled={!valid} onClick={save}>
          {t('common.save')}
        </button>
        <button className="ghost" onClick={() => setOpen(false)}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}

function RoundsPanel({
  data,
  names,
  onChange,
  fail,
}: {
  data?: { rounds: Round[]; enabled: boolean };
  names: Record<string, string>;
  onChange: () => void;
  fail: (err: unknown) => void;
}) {
  if (!data) return null;
  const act = async (url: string, body?: unknown) => {
    try {
      await post(url, body);
      onChange();
    } catch (err) {
      fail(err);
    }
  };
  const rounds = [...data.rounds].reverse();
  return (
    <div className="rounds-panel col">
      <div className="row">
        <strong className="grow">{t('gallery.rounds')}</strong>
        {!data.enabled && <span className="faint">{t('gallery.review_off')}</span>}
        <button className="ghost" onClick={() => act('/api/image/review/rounds/dismiss')}>
          {t('gallery.dismiss_rounds')}
        </button>
      </div>
      {rounds.length === 0 && <div className="faint">{t('gallery.no_rounds')}</div>}
      {rounds.slice(0, 100).map((r) => {
        const last = r.attempts[r.attempts.length - 1];
        return (
          <div key={r.id} className={`round-row round-${r.status}`}>
            <span className="chip">{t(`gallery.round.${r.status}`)}</span>
            <span className="grow">
              {names[r.combo[1]] ?? r.combo[1]} · {r.outfit_name ?? r.combo[2]} · {r.expression_name ?? r.combo[3]}
              <span className="faint">
                {' '}
                ·{' '}
                {t('gallery.regenerations', {
                  n: r.regenerations,
                  max: r.max_auto_regenerations,
                })}
              </span>
              {(r.error || last) && <div className="faint small">{msg(r.error ?? last?.evidence)}</div>}
            </span>
            {['needs_attention', 'limit_reached'].includes(r.status) && last && (
              <button className="ghost" onClick={() => act('/api/image/review/rounds/retry', { ids: [r.id] })}>
                {t('gallery.review_again')}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

type TrashEntry = { id: string; path: string; deleted_at: string; image_url: string; trash_path: string };

function TrashDialog({ close, fail, onChange }: { close: () => void; fail: (err: unknown) => void; onChange: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const trash = useQuery<{ entries: TrashEntry[] }>({ queryKey: ['output-trash'], queryFn: () => get('/api/image/trash') });
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const entries = trash.data?.entries ?? [];
  const act = async (action: 'restore' | 'purge', ids?: string[]) => {
    if (action === 'purge' && !confirm(ids ? t('gallery.purge_confirm', { n: ids.length }) : t('gallery.empty_trash_confirm'))) return;
    try {
      const result = await post(`/api/image/trash/${action}`, ids ? { ids } : {});
      toast({ text: action === 'restore' ? t('gallery.restored', { n: result.restored.length }) : t('gallery.purged', { n: result.purged }) });
      setPicked(new Set());
      qc.invalidateQueries({ queryKey: ['output-trash'] });
      qc.invalidateQueries({ queryKey: ['gallery-tree'] });
      onChange();
    } catch (err) {
      fail(err);
    }
  };
  const ids = [...picked];
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog col" style={{ width: 720, maxWidth: '94vw' }}>
        <div className="row">
          <h3 className="grow">{t('gallery.trash')}</h3>
          <button className="ghost" onClick={close}>
            ×
          </button>
        </div>
        <p className="faint">{t('gallery.trash_about')}</p>
        {entries.length === 0 && <div className="empty">{t('gallery.trash_empty')}</div>}
        <div className="gallery-grid" style={{ maxHeight: '50vh', overflow: 'auto', padding: 0 }}>
          {entries.map((e) => (
            <label key={e.id} className={`gallery-cell ${picked.has(e.id) ? 'selected' : ''}`} title={e.path}>
              <img src={`/api/image/gallery/thumbnail?path=${encodeURIComponent(e.trash_path)}`} alt="" loading="lazy" />
              <input
                type="checkbox"
                className="gallery-check"
                checked={picked.has(e.id)}
                onChange={(ev) => {
                  const next = new Set(picked);
                  if (ev.target.checked) next.add(e.id);
                  else next.delete(e.id);
                  setPicked(next);
                }}
              />
              <div className="gallery-caption">
                {e.path.split('/').slice(-3).join('/')} · {new Date(e.deleted_at).toLocaleDateString()}
              </div>
            </label>
          ))}
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button disabled={!ids.length} onClick={() => act('restore', ids)}>
            {t('gallery.restore', { n: ids.length })}
          </button>
          <button className="danger" disabled={!ids.length} onClick={() => act('purge', ids)}>
            {t('gallery.purge', { n: ids.length })}
          </button>
          <button className="danger" disabled={!entries.length} onClick={() => act('purge')}>
            {t('gallery.empty_trash')}
          </button>
        </div>
      </div>
    </div>
  );
}
