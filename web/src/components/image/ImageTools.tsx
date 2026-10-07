import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, get, post, put } from '../../api';
import { t, tm, msgText } from '../../i18n';
import { createMaskEditor, type MaskEditor } from '../../lib/maskEditor';
import { TAB_FEATURES, TAB_GROUPS, pickMethod, tabMethods, type Method, type ToolTab } from '../../lib/toolMethods';
import { MODEL_WORDS, splitTags } from '../../lib/tags';
import { useToast } from '../Toasts';
import { sendToLab } from './ImageLab';
import PromptConverter, { type PromptHandoff } from './PromptConverter';
import type { PostInfo, TaggerInfo, ToolInfo, ToolMethods } from '../../imageTypes';

type Mark = { source: string; updated_at: string };
export type ToolItem = {
  id: string;
  source: 'upload' | 'gallery';
  name: string;
  path: string;
  format: string;
  width: number;
  height: number;
  bytes?: number;
  parent?: string;
  op?: string;
  tags?: { tags: string[]; model: string; threshold: number; character_threshold: number };
  mask?: Mark;
  alpha_mask?: Mark;
  inpaint_mask?: Mark;
};
type Analysis = {
  item: ToolItem;
  prompt: { source: string; positive: string; negative: string; settings: Record<string, any> };
  comfy?: { models: Record<string, string>[] };
  has_alpha: boolean;
  has_workflow: boolean;
  text_keys: string[];
  exif: Record<string, string>;
  error?: string;
};
type Tab = ToolTab;
// What the server says about a ComfyUI tool: usable, or why not (ComfyUI not reachable, or nodes missing).
type OpenSettings = (section?: 'image' | 'install') => void;
type MaskKind = 'censor' | 'alpha' | 'inpaint';

const MASK: Record<MaskKind, { field: 'mask' | 'alpha_mask' | 'inpaint_mask'; color: [number, number, number]; preview: boolean }> = {
  censor: { field: 'mask', color: [255, 40, 60], preview: false },
  alpha: { field: 'alpha_mask', color: [40, 120, 255], preview: true },
  inpaint: { field: 'inpaint_mask', color: [40, 200, 90], preview: false },
};
const CENSOR_LABELS = ['nipples', 'pussy', 'penis', 'anus', 'testicles', 'x-ray', 'cross-section'];
const SOURCE_LABELS: Record<string, string> = { atelierx: 'tools.source.atelierx', parameters: 'tools.source.parameters', comfyui: 'tools.source.comfyui' };
const ACCEPT = '.png,.webp,.jpg,.jpeg,.zip';
// Tabs that run in ComfyUI. WebP conversion and prompt formats work without it.
const METHOD_KEY = 'atelierx.tools.method';
const COMFY_TABS: Tab[] = ['tag', 'post', 'censor', 'alpha', 'inpaint'];

function readMethods(): Partial<Record<Tab, Method>> {
  try {
    return JSON.parse(localStorage.getItem(METHOD_KEY) || '{}') || {};
  } catch {
    return {};
  }
}

// Translation with positional values ({0}, {1} …).
const tp = (key: string, ...values: unknown[]) => t(key, Object.fromEntries(values.map((v, i) => [String(i), v])));
const size = (n: number) => (n >= 1024 ** 2 ? `${(n / 1024 ** 2).toFixed(1)}MB` : `${Math.round(n / 1024)}KB`);
const norm = (tag: string) => tag.toLowerCase().replace(/_/g, ' ').replace(/^@/, '').trim();

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="col tool-field">
      <span className="muted">{label}</span>
      {children}
      {hint && <span className="faint small">{hint}</span>}
    </label>
  );
}

function Num({ value, onChange, ...attrs }: { value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number }) {
  return <input type="number" style={{ width: 96 }} value={value} onChange={(e) => onChange(Number(e.target.value))} {...attrs} />;
}

// Shown instead of a tool's form when ComfyUI or its nodes are missing: why, and where to fix it.
function ComfyNotice({ info, openSettings, recheck }: { info: ToolInfo; openSettings?: OpenSettings; recheck: () => void }) {
  const reason = info.reason === 'nodes' ? 'nodes' : 'offline';
  return (
    <div className="col tools-notice">
      <strong>{t(`tools.notice.${reason}.title`)}</strong>
      <span>{t(`tools.notice.${reason}.body`)}</span>
      {/* The connection error says what failed; for missing nodes the title says it all. */}
      {reason === 'offline' && info.error != null && <span className="faint small">{msgText(info.error)}</span>}
      <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
        {openSettings && (
          <button className="primary" onClick={() => openSettings(reason === 'nodes' ? 'install' : 'image')}>
            {t(`tools.notice.${reason}.action`)}
          </button>
        )}
        <button onClick={recheck}>{t('tools.notice.recheck')}</button>
      </div>
    </div>
  );
}

// Image menu → Image tools: a workspace of uploaded and gallery images, their metadata and tags, WebP conversion,
// post-processing (upscale, detailer), censor, background removal, inpaint and prompt-format conversion.
export default function ImageTools({ openLab, openSettings }: { openLab: () => void; openSettings?: OpenSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = useCallback((err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err instanceof Error ? err.message : err), tone: 'error' }), [toast]);
  const items = useQuery<{ items: ToolItem[] }>({ queryKey: ['tool-items'], queryFn: () => get('/api/image/tools/items'), refetchInterval: 3000 });
  const tagger = useQuery<TaggerInfo>({ queryKey: ['tool-tagger'], queryFn: () => get('/api/image/tools/tagger') });
  const postInfo = useQuery<PostInfo>({ queryKey: ['tool-post'], queryFn: () => get('/api/image/tools/postprocess') });
  const methods = useQuery<ToolMethods>({ queryKey: ['tool-methods'], queryFn: () => get('/api/image/tools/methods') });
  const list = items.data?.items ?? [];
  // A ComfyUI tab whose tool cannot run: dimmed, and its panel explains why instead of showing the form.
  const infoOf = (key: Tab): ToolInfo | undefined => (key === 'tag' ? tagger.data : COMFY_TABS.includes(key) ? postInfo.data : undefined);
  const blocked = (key: Tab) => {
    const info = infoOf(key);
    return !!info && !info.available;
  };
  const recheck = () => {
    qc.invalidateQueries({ queryKey: ['tool-tagger'] });
    qc.invalidateQueries({ queryKey: ['tool-post'] });
  };

  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [currentId, setCurrentId] = useState('');
  const [tab, setTab] = useState<Tab>('convert');
  // Where the tab's work runs (#151): this PC or an internet service; each tab keeps its last choice.
  const [remembered, setRemembered] = useState(readMethods);
  const method = pickMethod(tab, methods.data?.features, remembered);
  const chooseMethod = (next: Method) => {
    if (!tabMethods(tab, methods.data?.features).includes(next)) {
      toast({ text: t('tools.run_on.local_only') });
      return;
    }
    const saved = { ...remembered, [tab]: next };
    setRemembered(saved);
    try {
      localStorage.setItem(METHOD_KEY, JSON.stringify(saved));
    } catch {
      /* not remembered, still chosen */
    }
  };
  const [uploadStatus, setUploadStatus] = useState('');
  const [dragging, setDragging] = useState(false);
  const [handoff, setHandoff] = useState<PromptHandoff | null>(null);
  const editor = useRef<MaskEditor | null>(null);
  const [, setTick] = useState(0);
  const rerender = () => setTick((n) => n + 1);
  const fileInput = useRef<HTMLInputElement>(null);

  const current = list.find((i) => i.id === currentId);
  const chosenIds = list.filter((i) => chosen.has(i.id)).map((i) => i.id);
  const analysis = useQuery<Analysis>({
    queryKey: ['tool-analyze', currentId],
    queryFn: () => get(`/api/image/tools/analyze?id=${currentId}`),
    enabled: !!currentId,
  });

  useEffect(() => {
    if (!currentId && list.length) setCurrentId(list[list.length - 1].id);
    const known = new Set(list.map((i) => i.id));
    if ([...chosen].some((id) => !known.has(id))) setChosen(new Set([...chosen].filter((id) => known.has(id))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items.data]);

  const reload = () => qc.invalidateQueries({ queryKey: ['tool-items'] });
  const leaveEditor = () => {
    if (!editor.current?.isDirty()) return true;
    if (!confirm(t('tools.unsaved_mask'))) return false;
    editor.current = null;
    return true;
  };
  const show = (id: string) => {
    if (id !== currentId && !leaveEditor()) return;
    setCurrentId(id);
  };
  const toggle = (id: string, on: boolean) => {
    const next = new Set(chosen);
    if (on) next.add(id);
    else next.delete(id);
    setChosen(next);
  };

  async function upload(files: File[]) {
    if (!files.length) return;
    let added = 0;
    const problems: string[] = [];
    for (const [index, file] of files.entries()) {
      setUploadStatus(tp('tools.uploading', index + 1, files.length, file.name));
      try {
        const response = await fetch('/api/image/tools/upload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) },
          body: file,
          credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok) throw new Error(msgText(data.error) || t('tools.upload_failed'));
        added += data.added.length;
        for (const skip of data.skipped ?? []) problems.push(`${skip.name}: ${msgText(skip.error)}`);
      } catch (error) {
        problems.push(`${file.name}: ${error instanceof Error ? error.message : error}`);
      }
    }
    if (fileInput.current) fileInput.current.value = '';
    setUploadStatus(tp('tools.added', added, problems.length ? tp('tools.skipped', problems.length) : ''));
    if (problems.length) toast({ text: problems.slice(0, 3).join(' / '), tone: 'error' });
    reload();
  }

  async function removeChosen() {
    if (!chosenIds.length || !confirm(tp('tools.remove_confirm', chosenIds.length))) return;
    try {
      await post('/api/image/tools/remove', { ids: chosenIds });
      if (chosenIds.includes(currentId)) setCurrentId('');
      setChosen(new Set());
      reload();
    } catch (err) {
      fail(err);
    }
  }

  const switchTab = (next: Tab) => {
    if (next !== tab && !leaveEditor()) return;
    setTab(next);
  };

  return (
    <div className="tools-wrap">
      <div className="tools">
        <aside
          className={`tools-list pad col ${dragging ? 'dragging' : ''}`}
          onDragOver={(e) => (e.preventDefault(), setDragging(true))}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            upload([...(e.dataTransfer?.files ?? [])]);
          }}
        >
          <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>
            <button className="primary" onClick={() => fileInput.current?.click()}>
              {t('tools.upload_files')}
            </button>
            <input ref={fileInput} type="file" accept={ACCEPT} multiple hidden onChange={(e) => upload([...(e.target.files ?? [])])} />
            <button onClick={() => setChosen(chosen.size === list.length ? new Set() : new Set(list.map((i) => i.id)))}>
              {chosen.size === list.length && list.length ? t('gallery.clear_selection') : t('tools.select_all')}
            </button>
            <button disabled={!chosenIds.length} onClick={removeChosen}>
              {t('tools.remove_from_list')}
            </button>
            <a className={`button ${!chosenIds.length ? 'disabled' : ''}`} href={chosenIds.length ? `/api/image/tools/zip?ids=${chosenIds.join(',')}` : undefined}>
              {tp('tools.download_zip', chosenIds.length)}
            </a>
          </div>
          {uploadStatus && <div className="faint small">{uploadStatus}</div>}
          {!list.length && <div className="empty">{t('tools.drop_hint')}</div>}
          <div className="tools-grid">
            {list.map((item) => (
              <div key={item.id} className={`tools-card ${item.id === currentId ? 'current' : ''}`} title={`${item.name} · ${item.width}×${item.height} · ${item.format}`}>
                <img src={`/api/image/tools/thumbnail?id=${item.id}`} alt="" loading="lazy" onClick={() => show(item.id)} />
                <div className="row tools-caption">
                  <input type="checkbox" checked={chosen.has(item.id)} onChange={(e) => toggle(item.id, e.target.checked)} />
                  <span className="grow ellipsis">{item.name.split('/').pop()}</span>
                  <span className={`chip small ${item.source === 'gallery' ? 'scope-work' : ''}`}>{item.source === 'gallery' ? t('tools.from_gallery') : t('tools.upload')}</span>
                  {item.tags && <span className="chip small">{t('tools.tags')}</span>}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <div className="tools-detail pad col">
          {tab === 'prompt' ? (
            <PromptConverter handoff={handoff} openLab={openLab} />
          ) : !current ? (
            <div className="faint">{t('tools.choose_an_image')}</div>
          ) : (tab === 'censor' || tab === 'alpha' || tab === 'inpaint') && !blocked(tab) ? (
            <MaskPane key={`${tab}:${current.id}:${current[MASK[tab].field]?.updated_at ?? ''}`} item={current} kind={tab} editor={editor} onChange={rerender} onSaved={reload} />
          ) : (
            <Detail
              item={current}
              parent={list.find((i) => i.id === current.parent)}
              analysis={analysis.data}
              excluded={new Set((tagger.data?.exclude ?? []).map(norm))}
              toLab={(draft) => (sendToLab(draft), openLab())}
              toConverter={(h) => (setHandoff(h), setTab('prompt'))}
            />
          )}
        </div>

        <aside className="tools-panel pad col">
          <div className="tools-tabs">
            {TAB_GROUPS.map((group) => (
              <div key={group.id} className="tools-tab-group" role="group" aria-label={t(`tools.group.${group.id}`)}>
                <span className="faint small">{t(`tools.group.${group.id}`)}</span>
                <div className="tools-tab-row">
                  {group.tabs.map((key) => (
                    <button
                      key={key}
                      className={`${tab === key ? 'on' : ''} ${blocked(key) ? 'unavailable' : ''}`}
                      title={blocked(key) ? t(`tools.notice.${infoOf(key)?.reason === 'nodes' ? 'nodes' : 'offline'}.title`) : undefined}
                      onClick={() => switchTab(key)}
                    >
                      {t(`tools.tab.${key}`)}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {TAB_FEATURES[tab] && (
            <div className="row tools-method">
              <span className="muted small">{t('tools.run_on')}</span>
              <div className="service-switch" role="radiogroup" aria-label={t('tools.run_on')}>
                {(methods.data?.methods ?? ['local']).map((m) => {
                  const supported = tabMethods(tab, methods.data?.features).includes(m);
                  return (
                    <button
                      key={m}
                      role="radio"
                      aria-checked={method === m}
                      aria-disabled={!supported}
                      className={`${method === m ? 'on' : ''} ${supported ? '' : 'unavailable'}`}
                      title={supported ? undefined : t('tools.run_on.local_only')}
                      onClick={() => chooseMethod(m)}
                    >
                      {t(`tools.run_on.${m}`)}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {tab !== 'prompt' && !blocked(tab) && <div className="faint small">{tp('tools.selected', chosenIds.length)}</div>}
          {blocked(tab) && <ComfyNotice info={infoOf(tab)!} openSettings={openSettings} recheck={recheck} />}
          {tab === 'convert' && <ConvertForm ids={chosenIds} fail={fail} />}
          {tab === 'tag' && !blocked(tab) && <TagForm ids={chosenIds} list={list} info={tagger.data} fail={fail} onExcludes={() => qc.invalidateQueries({ queryKey: ['tool-tagger'] })} />}
          {tab === 'post' && !blocked(tab) && <PostForm ids={chosenIds} info={postInfo.data} method={method} fail={fail} openSettings={openSettings} />}
          {(tab === 'censor' || tab === 'alpha' || tab === 'inpaint') && !blocked(tab) && (
            <MaskForm
              kind={tab}
              item={current}
              list={list}
              ids={chosenIds}
              info={postInfo.data}
              method={method}
              analysis={analysis.data}
              editor={editor}
              fail={fail}
              reload={reload}
              rerender={rerender}
            />
          )}
        </aside>
      </div>
    </div>
  );
}

function Detail({
  item,
  parent,
  analysis,
  excluded,
  toLab,
  toConverter,
}: {
  item: ToolItem;
  parent?: ToolItem;
  analysis?: Analysis;
  excluded: Set<string>;
  toLab: (draft: any) => void;
  toConverter: (h: PromptHandoff) => void;
}) {
  const toast = useToast();
  const [view, setView] = useState<'side' | 'slider'>('side');
  const [slider, setSlider] = useState(50);
  const found = analysis?.prompt;
  const tags = item.tags ? item.tags.tags.filter((tag) => !excluded.has(norm(tag))) : null;
  const copy = async (text: string) => {
    await navigator.clipboard.writeText(text);
    toast({ text: t('gallery.copied') });
  };
  const src = (i: ToolItem) => `/api/image/tools/image?id=${i.id}`;
  return (
    <>
      <figure className="tools-figure">
        {parent ? (
          <div className="col">
            <div className="row">
              <div className="seg">
                {(['side', 'slider'] as const).map((v) => (
                  <button key={v} className={view === v ? 'on' : ''} onClick={() => setView(v)}>
                    {t(`lab.view.${v}`)}
                  </button>
                ))}
              </div>
              <span className="faint small">{tp('tools.original_of', parent.name)}</span>
            </div>
            {view === 'slider' ? (
              <div className="lab-slider">
                <div className="lab-frame">
                  <img src={src(parent)} alt="" />
                  <img src={src(item)} alt="" style={{ clipPath: `inset(0 0 0 ${slider}%)` }} />
                  <div className="lab-line" style={{ left: `${slider}%` }} />
                </div>
                <input type="range" min={0} max={100} value={slider} onChange={(e) => setSlider(Number(e.target.value))} />
              </div>
            ) : (
              <div className="lab-pair">
                <img src={src(parent)} alt="" />
                <img src={src(item)} alt="" />
              </div>
            )}
          </div>
        ) : (
          <img src={src(item)} alt="" />
        )}
        <figcaption className="faint small">
          {item.name} · {item.width}×{item.height} · {item.format} · {size(item.bytes ?? 0)}
        </figcaption>
      </figure>
      {!analysis ? (
        <div className="faint">{t('tools.reading_metadata')}</div>
      ) : (
        <div className="col tools-info">
          <div className="row">
            <h4 className="grow">{found?.source ? tp('tools.prompt_from', t(SOURCE_LABELS[found.source] ?? found.source)) : t('tools.no_prompt_record')}</h4>
            {found?.positive && (
              <>
                <button
                  className="ghost"
                  onClick={() =>
                    toLab({
                      positive: found.positive,
                      negative: found.negative || '',
                      settings: found.source === 'atelierx' ? { ...found.settings, seed: -1 } : { family: 'anima', seed: -1 },
                      source: item.source === 'gallery' ? item.path : null,
                    })
                  }
                >
                  {t('gallery.open_in_lab')}
                </button>
                <button
                  className="ghost"
                  onClick={() =>
                    toConverter({ positive: found.positive, negative: found.negative || '', settings: found.source === 'atelierx' ? found.settings : null, label: item.name })
                  }
                >
                  {t('tools.open_in_converter')}
                </button>
              </>
            )}
          </div>
          {found?.positive && (
            <>
              <div className="prompt-box mono small" onClick={() => copy(found.positive)} title={t('gallery.click_copy')}>
                {found.positive}
              </div>
              {found.negative && (
                <div className="prompt-box mono small faint" onClick={() => copy(found.negative)}>
                  − {found.negative}
                </div>
              )}
              <dl className="kv small">
                {Object.entries(found.settings ?? {})
                  .filter(([, v]) => typeof v !== 'object')
                  .map(([k, v]) => (
                    <div key={k} className="row">
                      <dt>{k}</dt>
                      <dd className="mono">{String(v)}</dd>
                    </div>
                  ))}
              </dl>
            </>
          )}
          {(analysis.comfy?.models ?? []).length > 0 && (
            <>
              <div className="section-title">{t('tools.models_used')}</div>
              {analysis.comfy!.models.map((m, i) => (
                <div key={i} className="mono small">
                  {Object.values(m).join(': ')}
                </div>
              ))}
            </>
          )}
          <div className="faint small">
            {[
              analysis.has_alpha ? t('tools.has_transparency') : t('tools.no_transparency'),
              analysis.has_workflow ? t('tools.has_workflow') : '',
              analysis.text_keys.length ? tp('tools.text_entries', analysis.text_keys.join(', ')) : t('tools.no_text_entries'),
            ]
              .filter(Boolean)
              .join(' · ')}
          </div>
          {Object.keys(analysis.exif ?? {}).length > 0 && (
            <details>
              <summary className="small">EXIF ({Object.keys(analysis.exif).length})</summary>
              <dl className="kv small">
                {Object.entries(analysis.exif).map(([k, v]) => (
                  <div key={k} className="row">
                    <dt>{k}</dt>
                    <dd className="mono">{v}</dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
          <div className="row">
            <h4 className="grow">{t('tools.wd14_tags')}</h4>
            {tags && (
              <>
                <button className="ghost" onClick={() => copy(tags.join(', '))}>
                  {t('tools.copy_tags')}
                </button>
                <button className="ghost" onClick={() => toLab({ positive: tags.join(', '), negative: '', settings: { family: 'anima', seed: -1 }, source: null })}>
                  {t('tools.tags_to_lab')}
                </button>
              </>
            )}
          </div>
          {tags ? (
            <>
              {item.tags!.tags.length - tags.length > 0 && <div className="faint small">{tp('tools.excluded_hidden', item.tags!.tags.length - tags.length)}</div>}
              <div className="faint small">{tp('tools.tagger_used', item.tags!.model, item.tags!.threshold, item.tags!.character_threshold)}</div>
              <TagReview tags={tags} prompt={found?.positive ?? ''} />
            </>
          ) : (
            <div className="faint small">{t('tools.not_tagged')}</div>
          )}
        </div>
      )}
    </>
  );
}

// Tagger tags against the prompt: in both, only in the image, and prompt tags the tagger did not see.
function TagReview({ tags, prompt }: { tags: string[]; prompt: string }) {
  const inPrompt = new Set(splitTags(prompt).map(norm));
  const seen = new Set(tags.map(norm));
  const groups: [string, string[], string][] = prompt
    ? [
        ['tools.tags_both', tags.filter((x) => inPrompt.has(norm(x))), 'both'],
        ['tools.tags_image_only', tags.filter((x) => !inPrompt.has(norm(x))), 'seen'],
        ['tools.tags_prompt_only', splitTags(prompt).filter((x) => !seen.has(norm(x)) && !MODEL_WORDS.test(x) && !x.startsWith('@') && !/\s\S+\s\S+\s/.test(x)), 'missing'],
      ]
    : [['tools.tags_read', tags, 'seen']];
  return (
    <div className="col">
      {groups
        .filter(([, list]) => list.length)
        .map(([key, list, cls]) => (
          <div key={key} className="col" style={{ gap: 2 }}>
            <span className="small muted">
              {t(key)} {list.length}
            </span>
            <div className="row" style={{ flexWrap: 'wrap', gap: 3 }}>
              {list.map((tag) => (
                <span key={tag} className={`chip small tag-${cls}`}>
                  {tag}
                </span>
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

function MaskPane({
  item,
  kind,
  editor,
  onChange,
  onSaved,
}: {
  item: ToolItem;
  kind: MaskKind;
  editor: React.MutableRefObject<MaskEditor | null>;
  onChange: () => void;
  onSaved: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const spec = MASK[kind];
    const saved = item[spec.field];
    const created = createMaskEditor({
      imageUrl: `/api/image/tools/image?id=${item.id}`,
      maskUrl: saved ? `/api/image/tools/mask?id=${item.id}&kind=${kind}&v=${encodeURIComponent(saved.updated_at)}` : null,
      width: item.width,
      height: item.height,
      color: spec.color,
      preview: spec.preview,
      onSave: async (blob) => {
        const response = await fetch(`/api/image/tools/mask?id=${item.id}&kind=${kind}`, { method: 'PUT', body: blob, credentials: 'same-origin' });
        if (!response.ok) {
          const data = await response.json().catch(() => null);
          throw new Error(msgText(data?.error) || String(response.status));
        }
        onSaved();
      },
      onChange,
    });
    if (!saved) created.setStatus(t(`tools.no_mask_hint.${kind}`));
    editor.current = created;
    host.current?.replaceChildren(created.element);
    return () => {
      if (editor.current === created) editor.current = null;
    };
    // The key on this component remounts it when the image, kind or saved mask changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="col">
      <div ref={host} />
      <div className="faint small">{t(`tools.mask_hint.${kind}`)}</div>
    </div>
  );
}

function ConvertForm({ ids, fail }: { ids: string[]; fail: (e: unknown) => void }) {
  const [form, setForm] = useState({ quality: 95, lossless: false, keep_metadata: false, long_side: 0, suffix: '' });
  const [taskId, setTaskId] = useState('');
  const task = useQuery<any>({
    queryKey: ['convert-task', taskId],
    queryFn: () => get(`/api/image/tools/convert/task?id=${taskId}`),
    enabled: !!taskId,
    refetchInterval: (q) => ((q.state.data as any)?.status === 'running' ? 800 : false),
  });
  const data = task.data;
  const before = (data?.results ?? []).reduce((s: number, r: any) => s + (r.source_bytes || 0), 0);
  const after = (data?.results ?? []).reduce((s: number, r: any) => s + r.bytes, 0);
  return (
    <div className="col">
      <Field label={t('tools.quality')} hint={t('tools.quality_hint')}>
        <div className="row">
          <input type="range" min={1} max={100} disabled={form.lossless} value={form.quality} onChange={(e) => setForm({ ...form, quality: Number(e.target.value) })} />
          <span className="mono">{form.quality}</span>
        </div>
      </Field>
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={form.lossless} onChange={(e) => setForm({ ...form, lossless: e.target.checked })} />
        {t('tools.lossless')}
      </label>
      <label className="row" style={{ gap: 4 }} title={t('tools.keep_metadata_hint')}>
        <input type="checkbox" checked={form.keep_metadata} onChange={(e) => setForm({ ...form, keep_metadata: e.target.checked })} />
        {t('tools.keep_metadata')}
      </label>
      <span className="faint small">{t('tools.keep_metadata_off')}</span>
      <Field label={t('tools.long_side')} hint={t('tools.long_side_hint')}>
        <Num value={form.long_side} min={0} max={8192} step={16} onChange={(v) => setForm({ ...form, long_side: Math.max(0, v || 0) })} />
      </Field>
      <Field label={t('tools.suffix')} hint={t('tools.saved_in_tools')}>
        <input placeholder="_web" value={form.suffix} onChange={(e) => setForm({ ...form, suffix: e.target.value })} />
      </Field>
      <button
        className="primary"
        disabled={!ids.length || data?.status === 'running'}
        onClick={async () => {
          try {
            const result = await post('/api/image/tools/convert', { ...form, ids });
            setTaskId(result.task.id);
          } catch (err) {
            fail(err);
          }
        }}
      >
        {tp('tools.convert_selected', ids.length)}
      </button>
      {data && (
        <div className="col compose-card">
          <div>
            {data.status === 'running' ? t('tools.converting') : t('tools.done')} {data.done}/{data.total}
          </div>
          {data.results.length > 0 && (
            <div className="faint small">
              {size(before)} → {size(after)} ({before ? Math.round((after / before) * 100) : 0}%)
            </div>
          )}
          {data.errors.map((e: any) => (
            <div key={e.item_id} className="error-text small">
              {e.name}: {msgText(e.error)}
            </div>
          ))}
          {data.status !== 'running' && data.results.length > 0 && <a href={`/api/image/tools/convert/zip?id=${data.id}`}>{tp('tools.download_zip', data.results.length)}</a>}
        </div>
      )}
    </div>
  );
}

function TagForm({ ids, list, info, fail, onExcludes }: { ids: string[]; list: ToolItem[]; info?: TaggerInfo; fail: (e: unknown) => void; onExcludes: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState({ model: '', threshold: 0.35, character_threshold: 0.85 });
  const [exclude, setExclude] = useState<string | null>(null);
  if (!info) return <div className="faint">{t('tools.reading_tagger')}</div>;
  if (!info.available) return <div className="error-text">{msgText(info.error)}</div>;
  const model = form.model || info.defaults.model;
  const tagged = list.filter((i) => ids.includes(i.id) && i.tags);
  return (
    <div className="col">
      <Field label={t('gen.model')} hint={t('tools.tagger_download_hint')}>
        <select value={model} onChange={(e) => setForm({ ...form, model: e.target.value })}>
          {info.models.map((m: string) => (
            <option key={m}>{m}</option>
          ))}
        </select>
      </Field>
      <Field label={t('tools.general_threshold')}>
        <Num value={form.threshold} min={0} max={1} step={0.05} onChange={(v) => setForm({ ...form, threshold: v })} />
      </Field>
      <Field label={t('tools.character_threshold')}>
        <Num value={form.character_threshold} min={0} max={1} step={0.05} onChange={(v) => setForm({ ...form, character_threshold: v })} />
      </Field>
      <button
        className="primary"
        disabled={!ids.length}
        onClick={async () => {
          try {
            await post('/api/image/tools/tag', { ...form, model, ids });
            toast({ text: tp('tools.queued_tagging', ids.length) });
            qc.invalidateQueries({ queryKey: ['image-queue'] });
          } catch (err) {
            fail(err);
          }
        }}
      >
        {tp('tools.tag_selected', ids.length)}
      </button>
      <span className="faint small">{t('tools.shares_queue')}</span>
      <div className="section-title">{t('tools.excluded_tags')}</div>
      <textarea rows={3} placeholder="simple background, white background" value={exclude ?? (info.exclude ?? []).join(', ')} onChange={(e) => setExclude(e.target.value)} />
      <button
        disabled={exclude === null}
        onClick={async () => {
          try {
            await put('/api/image/settings/tags', { exclude: splitTags(exclude ?? '').join('\n') });
            setExclude(null);
            onExcludes();
            toast({ text: t('tools.excluded_saved') });
          } catch (err) {
            fail(err);
          }
        }}
      >
        {t('common.save')}
      </button>
      <span className="faint small">{t('tools.excluded_hint')}</span>
      <div className="section-title">{t('tools.export_tags')}</div>
      <div className="row">
        {(['txt', 'json'] as const).map((format) => (
          <a
            key={format}
            className={`button ${!tagged.length ? 'disabled' : ''}`}
            href={tagged.length ? `/api/image/tools/tags/export?format=${format}&ids=${tagged.map((i) => i.id).join(',')}` : undefined}
          >
            {tp(`tools.export_${format}`, tagged.length)}
          </a>
        ))}
      </div>
      <span className="faint small">{t('tools.export_txt_hint')}</span>
    </div>
  );
}

function PostForm({ ids, info, method, fail, openSettings }: { ids: string[]; info?: PostInfo; method: Method; fail: (e: unknown) => void; openSettings?: OpenSettings }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [op, setOp] = useState('upscale');
  const [upscale, setUpscale] = useState({ model: '', scale: 2 });
  const [detail, setDetail] = useState({ face: true, eye: true, mouth: false, hand: true, denoise: 0.4, steps: 20 });
  if (!info) return <div className="faint">{t('tools.checking_nodes')}</div>;
  if (!info.available) return <div className="error-text">{msgText(info.error)}</div>;
  const ops = Object.entries(info.ops).filter(([key]) => !['detect', 'alpha', 'inpaint'].includes(key));
  const model = upscale.model || info.upscale_models[0] || '';
  return (
    <div className="col">
      <Field label={t('tools.operation')}>
        <select value={op} onChange={(e) => setOp(e.target.value)}>
          {ops.map(([key, label]) => (
            <option key={key} value={key}>
              {msgText(label)}
            </option>
          ))}
        </select>
      </Field>
      {!info.ops.detail && (
        <div className="row faint small" style={{ flexWrap: 'wrap', gap: 6 }}>
          <span>{t('tools.notice.detail')}</span>
          {openSettings && (
            <button className="ghost small" onClick={() => openSettings('install')}>
              {t('tools.notice.nodes.action')}
            </button>
          )}
        </div>
      )}
      {op === 'detail' ? (
        <>
          <Field label={t('tools.areas_to_redraw')} hint={t('tools.detail_order')}>
            <div className="row" style={{ flexWrap: 'wrap' }}>
              {(['face', 'eye', 'mouth', 'hand'] as const).map((key) => (
                <label key={key} className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={detail[key]} onChange={(e) => setDetail({ ...detail, [key]: e.target.checked })} />
                  {t(`tools.area.${key}`)}
                </label>
              ))}
            </div>
          </Field>
          <Field label={t('tools.denoise')} hint={t('tools.detail_denoise_hint')}>
            <Num value={detail.denoise} min={0.05} max={1} step={0.05} onChange={(v) => setDetail({ ...detail, denoise: v })} />
          </Field>
          <Field label={t('gen.steps')}>
            <Num value={detail.steps} min={1} max={60} onChange={(v) => setDetail({ ...detail, steps: v })} />
          </Field>
          <span className="faint small">{t('tools.detail_needs_record')}</span>
        </>
      ) : (
        <>
          <Field label={t('gen.model')}>
            <select value={model} onChange={(e) => setUpscale({ ...upscale, model: e.target.value })}>
              {info.upscale_models.map((m: string) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </Field>
          <Field label={t('tools.final_scale')} hint={t('tools.final_scale_hint')}>
            <Num value={upscale.scale} min={0.25} max={8} step={0.25} onChange={(v) => setUpscale({ ...upscale, scale: v })} />
          </Field>
          <span className="warn-text small">{t('tools.upscale_alpha')}</span>
        </>
      )}
      <button
        className="primary"
        disabled={!ids.length}
        onClick={async () => {
          try {
            const result = await post('/api/image/tools/postprocess', { ids, op, method, options: op === 'detail' ? detail : { ...upscale, model } });
            toast({ text: tp('tools.queued_post', result.jobs.length) });
            qc.invalidateQueries({ queryKey: ['image-queue'] });
          } catch (err) {
            fail(err);
          }
        }}
      >
        {tp('tools.process_selected', ids.length)}
      </button>
      <span className="faint small">{t('tools.shares_queue')}</span>
      <span className="faint small">{t('tools.where_saved')}</span>
    </div>
  );
}

function MaskForm({
  kind,
  item,
  list,
  ids,
  info,
  method,
  analysis,
  editor,
  fail,
  reload,
  rerender,
}: {
  kind: MaskKind;
  item?: ToolItem;
  list: ToolItem[];
  ids: string[];
  info?: PostInfo;
  method: Method;
  analysis?: Analysis;
  editor: React.MutableRefObject<MaskEditor | null>;
  fail: (e: unknown) => void;
  reload: () => void;
  rerender: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [censor, setCensor] = useState({ treatment: 'mosaic', intensity: 15, color: '#ffffff', opacity: 100, grow: 0, feather: 0, confidence: 0.35, labels: [] as string[] });
  const [alpha, setAlpha] = useState({ method: 'isnet', confidence: 0.35, grow: 0, feather: 1 });
  const [inpaint, setInpaint] = useState({ positive: '', negative: '', denoise: 0.6, steps: 0, grow: 8, feather: 8, area: 'crop', padding: 64, for: '' });
  const field = MASK[kind].field;
  const dirty = !!editor.current?.isDirty();
  const unavailable = !info?.available;
  const found = analysis && analysis.item?.id === item?.id ? analysis.prompt : undefined;
  const recorded = found?.source === 'atelierx' && !!found.positive;

  useEffect(() => {
    if (kind === 'inpaint' && item && analysis?.item?.id === item.id && inpaint.for !== item.id)
      setInpaint({ ...inpaint, for: item.id, positive: recorded ? found!.positive : '', negative: recorded ? found!.negative || '' : '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, item?.id, analysis]);

  const saveMask = async () => {
    try {
      await editor.current?.save();
      toast({ text: t('tools.mask_saved') });
      rerender();
    } catch (err) {
      fail(err);
    }
  };
  const flush = async () => {
    if (editor.current?.isDirty()) await editor.current.save();
  };
  const queue = async (op: string, options: any, targetIds: string[], done: string) => {
    try {
      await flush();
      const result = await post('/api/image/tools/postprocess', { ids: targetIds, op, method, options });
      toast({ text: tp(done, result.jobs.length) });
      qc.invalidateQueries({ queryKey: ['image-queue'] });
    } catch (err) {
      fail(err);
    }
  };
  const confirmOverwrite = (targetIds: string[]) => {
    const masked = list.filter((i) => targetIds.includes(i.id) && i[field]).length;
    return !masked || confirm(tp('tools.overwrite_masks', masked));
  };
  const bodyOf = () =>
    kind === 'censor'
      ? { treatment: censor.treatment, intensity: censor.intensity, color: censor.color, opacity: censor.opacity, grow: censor.grow, feather: censor.feather }
      : { grow: alpha.grow, feather: alpha.feather };
  const applyOne = async () => {
    try {
      await flush();
      await post(`/api/image/tools/${kind}`, { id: item!.id, ...bodyOf() });
      toast({ text: t(`tools.applied.${kind}`) });
      reload();
    } catch (err) {
      fail(err);
    }
  };
  const withMask = list.filter((i) => ids.includes(i.id) && i[field]);
  const applyChosen = async () => {
    try {
      await flush();
    } catch (err) {
      return fail(err);
    }
    let done = 0;
    for (const target of withMask) {
      try {
        await post(`/api/image/tools/${kind}`, { id: target.id, ...bodyOf() });
        done += 1;
      } catch (err) {
        fail(err);
      }
    }
    toast({ text: tp('tools.applied_chosen', done, ids.length - withMask.length) });
    reload();
  };
  const markText = item?.[field] ? tp('tools.mask_state', item[field]!.source === 'detected' ? t('tools.detected') : t('tools.edited_by_hand')) : t('tools.no_mask');
  const step2 = (
    <>
      <div className="section-title">{t(kind === 'inpaint' ? 'tools.step.area' : 'tools.step.fix')}</div>
      <span className="faint small">{markText}</span>
      <button disabled={!item || !dirty} onClick={saveMask}>
        {t('tools.save_mask')}
      </button>
    </>
  );
  const shape = (value: { grow: number; feather: number }, set: (v: any) => void) => (
    <>
      <Field label={t('tools.grow')} hint={t('tools.grow_hint')}>
        <Num value={value.grow} min={-64} max={64} onChange={(v) => set({ ...value, grow: v })} />
      </Field>
      <Field label={t('tools.feather')}>
        <Num value={value.feather} min={0} max={64} onChange={(v) => set({ ...value, feather: v })} />
      </Field>
    </>
  );

  if (kind === 'censor')
    return (
      <div className="col">
        <div className="section-title">{t('tools.step.detect')}</div>
        <Field label={t('tools.areas_to_cover')}>
          <div className="row" style={{ flexWrap: 'wrap' }}>
            {CENSOR_LABELS.map((label) => (
              <label key={label} className="row" style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={!censor.labels.length || censor.labels.includes(label)}
                  onChange={(e) => {
                    const base = censor.labels.length ? censor.labels : CENSOR_LABELS;
                    setCensor({ ...censor, labels: e.target.checked ? [...new Set([...base, label])] : base.filter((l) => l !== label) });
                  }}
                />
                {label}
              </label>
            ))}
          </div>
        </Field>
        <Field label={t('tools.confidence')}>
          <Num value={censor.confidence} min={0} max={1} step={0.05} onChange={(v) => setCensor({ ...censor, confidence: v })} />
        </Field>
        <button
          disabled={!ids.length || unavailable || !info?.ops?.detect}
          onClick={() =>
            confirmOverwrite(ids) && queue('detect', { confidence: censor.confidence, ...(censor.labels.length ? { labels: censor.labels } : {}) }, ids, 'tools.queued_detect')
          }
        >
          {tp('tools.detect_selected', ids.length)}
        </button>
        {unavailable && info && <span className="error-text small">{msgText(info.error)}</span>}
        <span className="faint small">{t('tools.paint_instead')}</span>
        {step2}
        <div className="section-title">{t('tools.step.apply')}</div>
        <Field label={t('tools.method')}>
          <select value={censor.treatment} onChange={(e) => setCensor({ ...censor, treatment: e.target.value })}>
            {['mosaic', 'blur', 'color'].map((m) => (
              <option key={m} value={m}>
                {t(`tools.treatment.${m}`)}
              </option>
            ))}
          </select>
        </Field>
        {censor.treatment === 'color' ? (
          <>
            <Field label={t('tools.color')}>
              <input type="color" value={censor.color} onChange={(e) => setCensor({ ...censor, color: e.target.value })} />
            </Field>
            <Field label={t('tools.opacity')}>
              <Num value={censor.opacity} min={0} max={100} step={5} onChange={(v) => setCensor({ ...censor, opacity: v })} />
            </Field>
          </>
        ) : (
          <Field label={t(censor.treatment === 'mosaic' ? 'tools.block_size' : 'tools.blur_radius')}>
            <Num value={censor.intensity} min={1} max={256} onChange={(v) => setCensor({ ...censor, intensity: v })} />
          </Field>
        )}
        {shape(censor, setCensor)}
        <button className="primary" disabled={!item || (!item[field] && !dirty)} onClick={applyOne}>
          {t('tools.apply_this')}
        </button>
        <button disabled={!withMask.length} onClick={applyChosen}>
          {tp('tools.apply_chosen', withMask.length)}
        </button>
        <span className="faint small">{t('tools.censor_keeps_original')}</span>
        <span className="faint small">{t('tools.where_saved')}</span>
      </div>
    );

  if (kind === 'alpha')
    return (
      <div className="col">
        <div className="section-title">{t('tools.step.split')}</div>
        <Field label={t('tools.method')}>
          <select value={alpha.method} onChange={(e) => setAlpha({ ...alpha, method: e.target.value })}>
            <option value="isnet">{t('tools.alpha.isnet')}</option>
            <option value="person">{t('tools.alpha.person')}</option>
          </select>
        </Field>
        {alpha.method === 'person' && (
          <Field label={t('tools.confidence')}>
            <Num value={alpha.confidence} min={0} max={1} step={0.05} onChange={(v) => setAlpha({ ...alpha, confidence: v })} />
          </Field>
        )}
        <button
          disabled={!ids.length || unavailable || !info?.ops?.alpha}
          onClick={() => confirmOverwrite(ids) && queue('alpha', { method: alpha.method, confidence: alpha.confidence }, ids, 'tools.queued_split')}
        >
          {tp('tools.split_selected', ids.length)}
        </button>
        {unavailable && info && <span className="error-text small">{msgText(info.error)}</span>}
        {step2}
        <div className="section-title">{t('tools.step.apply')}</div>
        {shape(alpha, setAlpha)}
        <button className="primary" disabled={!item || (!item[field] && !dirty)} onClick={applyOne}>
          {t('tools.apply_this')}
        </button>
        <button disabled={!withMask.length} onClick={applyChosen}>
          {tp('tools.apply_chosen', withMask.length)}
        </button>
        <span className="faint small">{t('tools.alpha_result')}</span>
        <span className="faint small">{t('tools.where_saved')}</span>
      </div>
    );

  return (
    <div className="col">
      {step2}
      <div className="section-title">{t('tools.step.prompt')}</div>
      <Field label="positive" hint={t('tools.inpaint_prompt_hint')}>
        <textarea rows={4} className="mono" value={inpaint.positive} onChange={(e) => setInpaint({ ...inpaint, positive: e.target.value })} />
      </Field>
      <Field label="negative">
        <textarea rows={2} className="mono" value={inpaint.negative} onChange={(e) => setInpaint({ ...inpaint, negative: e.target.value })} />
      </Field>
      <div className="section-title">{t('tools.step.redraw')}</div>
      <Field label={t('tools.inpaint_area')} hint={t('tools.inpaint_area_hint')}>
        <select value={inpaint.area} onChange={(e) => setInpaint({ ...inpaint, area: e.target.value })}>
          <option value="crop">{t('tools.inpaint_crop')}</option>
          <option value="full">{t('tools.inpaint_full')}</option>
        </select>
      </Field>
      {inpaint.area === 'crop' && (
        <Field label={t('tools.padding')} hint={t('tools.padding_hint')}>
          <Num value={inpaint.padding} min={0} max={512} step={16} onChange={(v) => setInpaint({ ...inpaint, padding: v })} />
        </Field>
      )}
      <Field label={t('tools.denoise')} hint={t('tools.inpaint_denoise_hint')}>
        <Num value={inpaint.denoise} min={0.05} max={1} step={0.05} onChange={(v) => setInpaint({ ...inpaint, denoise: v })} />
      </Field>
      <Field label={t('gen.steps')} hint={t('tools.inpaint_steps_hint')}>
        <Num value={inpaint.steps} min={0} max={60} onChange={(v) => setInpaint({ ...inpaint, steps: v })} />
      </Field>
      {shape(inpaint, setInpaint)}
      <button
        className="primary"
        disabled={!item || !recorded || (!item.inpaint_mask && !dirty) || unavailable || !info?.ops?.inpaint}
        onClick={() => {
          const { for: filledFor, ...options } = inpaint;
          const body: any = { ...options };
          // Prompts not yet filled from this image's record are left to the server (it uses the record).
          if (filledFor !== item!.id) {
            delete body.positive;
            delete body.negative;
          }
          queue('inpaint', body, [item!.id], 'tools.queued_inpaint');
        }}
      >
        {t('tools.inpaint_this')}
      </button>
      {item && analysis && !recorded && <span className="error-text small">{t('tools.inpaint_needs_record')}</span>}
      {unavailable && info && <span className="error-text small">{msgText(info.error)}</span>}
      <span className="faint small">{t('tools.inpaint_about')}</span>
      <span className="faint small">{t('tools.where_saved')}</span>
    </div>
  );
}
