import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, get, post, put, q } from '../api';
import { t, tm } from '../i18n';
import { KINDS, type Item, type Kind, type WorkInfo } from '../types';
import { measure } from '../count';
import CodeEditor from './LazyCodeEditor';
import MessageMarkdown from './MessageMarkdown';
import ImageDesign from './ImageDesign';
import ImageGallery from './image/ImageGallery';
import EditorLlmTools from './EditorLlmTools';
import type { ImageView } from '../types';
import JsxWorkbench from './JsxWorkbench';
import { createSaver } from '../lib/exampleSaver';
import { useToast } from './Toasts';
import { ChipsInput } from './ui';
import { KindIcon } from './icons';
import { useUnsaved } from './Unsaved';

// What the status bar shows of the open item. Unsaved changes go to the register (Unsaved.tsx), not here.
export type EditorStatus = {
  size: number;
  unit: 'bytes' | 'chars' | 'tokens';
  estimated: boolean;
  kind: Kind;
};

const FORM_KEYS = ['schema_version', 'id', 'kind', 'enabled', 'keywords', 'priority', 'always', 'default_props'];

export default function ItemEditor({
  workId,
  path,
  info,
  onStatus,
  onReview,
  onRenamed,
  onOpen,
  onImage,
}: {
  workId: string;
  path: string;
  info: WorkInfo;
  onStatus: (status: EditorStatus) => void;
  onReview: (draft: string) => void;
  onRenamed?: (from: string, to: string) => void;
  onOpen?: (path: string) => void;
  onImage?: (view: ImageView, characterId: string, outfitId?: string) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const settings = useQuery({ queryKey: ['settings'], queryFn: () => get('/api/settings') });
  const item = useQuery<Item>({ queryKey: ['item', workId, path], queryFn: () => get(`/api/works/${workId}/file?path=${q(path)}`) });
  const [meta, setMeta] = useState<Record<string, any>>({});
  const [body, setBody] = useState('');
  const [dirty, setDirty] = useState(false);
  const [imageDirty, setImageDirty] = useState(false);
  const [jsxDirty, setJsxDirty] = useState(false);
  // JSX examples autosave through one saver per open item, so leaving the preview tab never cancels or loses a write.
  const jsxSaver = useMemo(
    () =>
      createSaver<{ jsx: string; name: string }>(
        async (key, text) => {
          const response = await fetch(`/api/works/${workId}/jsx/${q(key.jsx)}/props/${q(key.name)}`, { method: 'PUT', body: text });
          if (!response.ok) throw new ApiError(response.status, (await response.json()).error);
          return response.json();
        },
        {
          onChange: setJsxDirty,
          onSaved: (key, saved, clean) => clean && qc.setQueryData(['jsx-props', workId, key.jsx], saved),
          onError: (err) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }),
        },
      ),
    [workId, path], // eslint-disable-line react-hooks/exhaustive-deps
  );
  // Closing the item without saving (the user chose to discard) writes nothing more.
  useEffect(() => {
    jsxSaver.activate();
    return () => jsxSaver.dispose();
  }, [jsxSaver]);
  const [inner, setInner] = useState('body');
  const [error, setError] = useState('');
  const baseHash = useRef<string | null>(null);
  const saving = useRef(false);
  const [saveCycle, setSaveCycle] = useState(0);
  const latestEdit = useRef({ body, meta });
  latestEdit.current = { body, meta };
  // The server resolves old or missing kind values (e.g. greeting → start); an unknown value falls back the same way.
  const kind: Kind = KINDS.includes(meta.kind) ? meta.kind : (item.data?.kind ?? (path.endsWith('.jsx') ? 'jsx' : 'lorebook'));
  const suggest = useQuery({
    queryKey: ['suggest-id', workId, kind],
    queryFn: () => get(`/api/works/${workId}/suggest-id?kind=${kind}`),
    enabled: kind !== 'note',
  });

  useEffect(() => {
    if (item.data && !dirty) {
      setMeta(item.data.meta);
      setBody(item.data.body);
      baseHash.current = item.data.hash;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.data]);

  // The parent passes a fresh callback each render; keep the latest in a ref so the effect only follows content.
  const statusRef = useRef(onStatus);
  statusRef.current = onStatus;
  const countMode = info.effective.values.count;
  const saveRef = useRef<() => Promise<boolean>>(async () => true);
  useEffect(() => {
    const m = measure(body, countMode);
    statusRef.current({ size: m.amount, unit: m.unit, estimated: m.estimated, kind });
  }, [body, kind, countMode]);
  // The text, form and JSX examples, saved together (also by "Save all and leave").
  useUnsaved('text', dirty || jsxDirty, () => saveRef.current());

  const save = useCallback(async () => {
    if (saving.current) return false;
    if (jsxSaver.dirty) {
      try {
        if (!(await jsxSaver.flush()).clean) return false;
      } catch (err) {
        setError(err instanceof ApiError ? tm(err.msg) : String(err));
        return false;
      }
    }
    if (!dirty) return true;
    saving.current = true;
    try {
      const metaChanges: Record<string, any> = { ...meta };
      if (!metaChanges.id && kind !== 'note' && suggest.data?.id) metaChanges.id = suggest.data.id;
      const saved = await put<Item>(`/api/works/${workId}/file?path=${q(path)}`, {
        meta: metaChanges,
        body,
        base_hash: baseHash.current,
      });
      baseHash.current = saved.hash;
      const unchanged = latestEdit.current.body === body && latestEdit.current.meta === meta;
      if (unchanged) setMeta(saved.meta);
      setDirty(!unchanged);
      if (!unchanged) setSaveCycle((cycle) => cycle + 1);
      setError('');
      qc.setQueryData(['item', workId, path], saved);
      qc.invalidateQueries({ queryKey: ['tree', workId] });
      qc.invalidateQueries({ queryKey: ['check', workId] });
      qc.invalidateQueries({ queryKey: ['suggest-id', workId] });
      return unchanged;
    } catch (err) {
      setError(err instanceof ApiError ? tm(err.msg) : String(err));
      return false;
    } finally {
      saving.current = false;
    }
  }, [dirty, meta, body, kind, suggest.data, workId, path, qc, jsxSaver]);

  saveRef.current = save;

  // Autosave after the user pauses typing (02-editor: 편집과 저장).
  useEffect(() => {
    if (!dirty || !settings.data?.autosave?.enabled) return;
    const timer = setTimeout(save, settings.data.autosave.delay_ms ?? 1000);
    return () => clearTimeout(timer);
  }, [dirty, body, meta, save, settings.data, saveCycle]);

  // Reload puts the file as it is on disk into the editor (text, form and base hash) before the unsaved mark goes:
  // the query may already hold that answer, in which case the effect above would not run again.
  async function reload() {
    if (dirty && !confirm(t('editor.reload_confirm'))) return;
    const result = await item.refetch();
    if (!result.data || result.isError) {
      setError(t('editor.reload_failed'));
      return;
    }
    setMeta(result.data.meta);
    setBody(result.data.body);
    baseHash.current = result.data.hash;
    setError('');
    setDirty(false);
  }

  const change = (key: string, value: any) => {
    if (key === 'id' && imageDirty) {
      if (!confirm(t('editor.close_unsaved'))) return;
      setImageDirty(false);
    }
    setMeta((m) => ({ ...m, [key]: value }));
    setDirty(true);
  };

  async function changeKind(next: Kind) {
    if (imageDirty) {
      if (!confirm(t('editor.close_unsaved'))) return;
      setImageDirty(false);
    }
    if (dirty && !(await save())) return;
    const toJsx = next === 'jsx' && !path.endsWith('.jsx');
    const fromJsx = next !== 'jsx' && path.endsWith('.jsx');
    if ((toJsx || fromJsx) && body.trim() && !confirm(t('editor.kind_ext_confirm'))) return;
    try {
      const saved = await post<Item>(`/api/works/${workId}/kind`, { path, kind: next });
      qc.invalidateQueries({ queryKey: ['tree', workId] });
      if (saved.path !== path) onRenamed?.(path, saved.path);
      else {
        setMeta(saved.meta);
        baseHash.current = saved.hash;
        qc.setQueryData(['item', workId, path], saved);
      }
      setInner('body');
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  if (item.isError) return <div className="empty">{t('editor.missing')}</div>;
  if (!item.data) return null;

  const tabsByKind: Record<Kind, string[]> = {
    main: ['body', 'preview'],
    start: ['body', 'preview'],
    lorebook: ['body', 'preview'],
    note: ['body', 'preview'],
    character: ['body', 'preview', 'image', 'gallery'],
    jsx: ['code', 'props'],
  };
  const innerTabs = tabsByKind[kind];
  const current = innerTabs.includes(inner) ? inner : innerTabs[0];
  const extra = Object.keys(meta).filter((k) => !FORM_KEYS.includes(k));
  const hasKeywords = kind === 'lorebook' || kind === 'character';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="inner-tabs">
        {innerTabs.map((key) => (
          <button key={key} className={current === key ? 'on' : ''} onClick={() => setInner(key)}>
            {t(`inner.${key}`)}
          </button>
        ))}
        <span className="grow" />
        {kind !== 'jsx' && <EditorLlmTools workId={workId} path={path} beforeRun={save} />}
      </div>
      {item.data.meta_error && <div className="banner">{t('editor.meta_error')}: {item.data.meta_error}</div>}
      {error && (
        <div className="banner" style={{ background: 'var(--danger-bg)', color: 'var(--danger)' }}>
          {error}
          <span className="grow" />
          <button onClick={reload}>{t('editor.reload')}</button>
        </div>
      )}
      {(current === 'body' || current === 'code') && (
        <div className="form meta-bar">
          <label>
            {t('form.kind')}
            <KindIcon kind={kind} size={15} />
            <select value={kind} onChange={(e) => changeKind(e.target.value as Kind)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`kind.${k}`)}
                </option>
              ))}
            </select>
          </label>
          {kind !== 'note' && (
            <label style={{ width: 90 }}>
              ID
              <input
                value={meta.id ?? ''}
                placeholder={suggest.data?.id}
                readOnly={!!item.data.id_links?.length}
                title={item.data.id_links?.length ? t('editor.id_linked', { places: item.data.id_links.map((p) => t(`editor.id_link.${p}`)).join(', ') }) : undefined}
                onChange={(e) => change('id', e.target.value || null)}
              />
            </label>
          )}
          {hasKeywords && (
            <>
              <label className="grow" style={{ minWidth: 240 }}>
                {t('form.keywords')}
                <ChipsInput values={(meta.keywords ?? []).map(String)} onChange={(v) => change('keywords', v)} placeholder={t('form.keywords_hint')} />
              </label>
              <label style={{ width: 80 }}>
                {t('form.priority')}
                <input type="number" value={meta.priority ?? ''} onChange={(e) => change('priority', e.target.value === '' ? null : Number(e.target.value))} />
              </label>
              <label>
                {t('form.always')}
                <input type="checkbox" checked={!!meta.always} onChange={(e) => change('always', e.target.checked)} />
              </label>
            </>
          )}
          {kind === 'jsx' && (
            <label style={{ width: 120 }}>
              {t('form.default_props')}
              <input value={meta.default_props ?? ''} onChange={(e) => change('default_props', e.target.value || null)} />
            </label>
          )}
          {kind !== 'note' && (
            <label>
              {t('form.enabled')}
              <input type="checkbox" checked={meta.enabled !== false} onChange={(e) => change('enabled', e.target.checked ? null : false)} />
            </label>
          )}
          {extra.length > 0 && (
            <details style={{ width: '100%' }}>
              <summary className="faint">{t('form.extra', { n: extra.length })}</summary>
              <pre className="mono faint" style={{ margin: 0 }}>
                {extra.map((k) => `${k}: ${JSON.stringify(meta[k])}`).join('\n')}
              </pre>
            </details>
          )}
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {(current === 'body' || current === 'code') && (
          <CodeEditor
            value={body}
            language={kind === 'jsx' ? 'jsx' : 'markdown'}
            onChange={(value) => {
              setBody(value);
              setDirty(true);
            }}
            onAttach={(selection) =>
              window.dispatchEvent(new CustomEvent('atelierx:agent-attach', { detail: { path, ...selection } }))
            }
            onSave={save}
          />
        )}
        {/* Raw HTML in a document stays text: the preview runs in the app and must never execute a document. */}
        {current === 'preview' && <div className="preview"><MessageMarkdown text={body} /></div>}
        {(current === 'image' || imageDirty) && <div style={{ display: current === 'image' ? 'block' : 'none' }}>
          <ImageDesign key={meta.id ?? ''} workId={workId} characterId={meta.id} info={info} onReview={onReview} beforeConvert={save} openImage={onImage} onDirtyChange={setImageDirty} />
        </div>}
        {current === 'gallery' && (meta.id ? <div style={{ height: '100%', overflow: 'auto' }}>
          <div className="row image-flow"><button onClick={() => onImage?.('generate', meta.id)}>{t('flow.generate')}</button><button onClick={() => onImage?.('lora', meta.id)}>{t('flow.lora')}</button></div>
          <ImageGallery key={`${workId}:${meta.id}`} workId={workId} characterId={meta.id} openLab={() => onImage?.('lab', meta.id)} openTools={() => onImage?.('tools', meta.id)} />
        </div> : <div className="empty">{t('image.need_id')}</div>)}
        {current === 'props' && (
          <JsxWorkbench
            workId={workId}
            jsxId={meta.id}
            name={path.split('/').pop()!.replace(/\.jsx$/, '')}
            source={body}
            defaultProps={meta.default_props}
            info={info}
            setDefault={(name) => change('default_props', name)}
            openItem={onOpen}
            saver={jsxSaver}
          />
        )}
      </div>
    </div>
  );
}
