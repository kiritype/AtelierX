import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type PointerEvent, type CSSProperties } from 'react';
import { ApiError, get, put } from '../../api';
import { t, tm } from '../../i18n';
import type { MossDocument, MossItem, MossTemplate } from '../../imageTypes';
import { compileMoss, mossErrors, newMossItem, templateMoss, validRect } from '../../lib/mossLayout';
import MossTargetPicker from './MossTargetPicker';
import './MossLayoutEditor.css';

type Props = { value: MossDocument; onChange: (value: MossDocument) => void; onInvalid: (invalid: boolean) => void; workId?: string; batch?: boolean; sceneMaterial?: string };
type Gesture = { before: MossDocument; id: string; x: number; y: number; bounds: DOMRect; kind: 'move' | 'resize' | 'draw'; pointer: number; releaseScroll: () => void };
const copy = (doc: MossDocument) => structuredClone(doc);
const clamp = (n: number, low: number, high: number) => Math.min(high, Math.max(low, n));
const labels = ['character', 'object', 'text'] as const;

// A partly clipped canvas can trigger browser autoscroll during pointer capture.
// Keep the coordinate frame fixed for this gesture, without changing its layout.
function holdAncestorScroll(canvas: HTMLElement) {
  const positions: { element: HTMLElement; top: number; left: number }[] = [];
  for (let element = canvas.parentElement; element; element = element.parentElement) {
    if (element.scrollHeight > element.clientHeight || element.scrollWidth > element.clientWidth) {
      positions.push({ element, top: element.scrollTop, left: element.scrollLeft });
    }
  }
  const restore = () => {
    for (const { element, top, left } of positions) {
      if (element.scrollTop !== top) element.scrollTop = top;
      if (element.scrollLeft !== left) element.scrollLeft = left;
    }
  };
  for (const { element } of positions) element.addEventListener('scroll', restore);
  return () => {
    restore();
    for (const { element } of positions) element.removeEventListener('scroll', restore);
  };
}

export function MossBadge() { return <span className="moss-beta">Beta</span>; }
export function MossMode({ mode, onChange }: { mode: MossDocument['mode']; onChange: (mode: MossDocument['mode']) => void }) {
  return <div className="moss-mode"><strong>MOSS-Image <MossBadge /></strong><div className="seg" role="group" aria-label={t('moss.input_mode')}>
    {(['general', 'layout'] as const).map(value => <button type="button" key={value} className={mode === value ? 'on' : ''} aria-pressed={mode === value} onClick={() => onChange(value)}>{t(`moss.mode.${value}`)}</button>)}
  </div></div>;
}

export default function MossLayoutEditor({ value, onChange, onInvalid, workId, batch = false, sceneMaterial = '' }: Props) {
  const qc = useQueryClient();
  const templates = useQuery<Record<string, MossTemplate>>({ queryKey: ['image-lib', 'compositions', workId], queryFn: () => get(`/api/image/library/compositions${workId ? `?work=${workId}` : ''}`) });
  const [selected, setSelected] = useState(value.items[0]?.id ?? '');
  const [past, setPast] = useState<MossDocument[]>([]);
  const [future, setFuture] = useState<MossDocument[]>([]);
  const [numbers, setNumbers] = useState<Record<string, string[]>>({});
  const [templateName, setTemplateName] = useState('');
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const canvas = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  useEffect(() => () => { gesture.current?.releaseScroll(); gesture.current = null; }, []);
  const latest = useRef(value); latest.current = value;
  const selectedItem = value.items.find(i => i.id === selected);
  const errors = mossErrors(value, batch);
  const numericInvalid = Object.entries(numbers).some(([id, fields]) => value.items.some(i => i.id === id) && !validRect(fields.map((s, n) => s.trim() ? Number(s) / (n % 2 ? value.height : value.width) : NaN)));
  const invalid = errors.length > 0 || numericInvalid || compileMoss(value, sceneMaterial).length > 30000;
  useEffect(() => { onInvalid(invalid); return () => onInvalid(false); }, [invalid, onInvalid]);
  useEffect(() => { setNumbers({}); }, [value.width, value.height]);
  function commit(next: MossDocument, before = value) {
    setPast(list => [...list.slice(-49), copy(before)]); setFuture([]); onChange(next);
  }
  function replace(item: MossItem) { commit({ ...value, items: value.items.map(i => i.id === item.id ? item : i) }); }
  function undo() {
    if (!past.length) return;
    setFuture(list => [copy(value), ...list]); onChange(past[past.length - 1]); setPast(list => list.slice(0, -1)); setNumbers({});
  }
  function redo() {
    if (!future.length) return;
    setPast(list => [...list, copy(value)]); onChange(future[0]); setFuture(list => list.slice(1)); setNumbers({});
  }
  function remove() { commit({ ...value, items: value.items.filter(i => i.id !== selected) }); setSelected(''); }
  function begin(e: PointerEvent<HTMLElement>, item: MossItem | null, kind: Gesture['kind']) {
    if (gesture.current || e.button !== 0 || !canvas.current || (kind === 'draw' && e.target !== e.currentTarget) || (!item && value.items.length >= 32)) return;
    e.preventDefault(); e.stopPropagation();
    const added = item ?? newMossItem('object');
    const bounds = canvas.current.getBoundingClientRect();
    gesture.current = { before: copy(value), id: added.id, x: e.clientX, y: e.clientY, bounds, kind, pointer: e.pointerId, releaseScroll: holdAncestorScroll(canvas.current) };
    setSelected(added.id); setNumbers({});
    if (!item) onChange({ ...value, items: [...value.items, { ...added, rect: [clamp((e.clientX - bounds.left) / bounds.width, 0, .999), clamp((e.clientY - bounds.top) / bounds.height, 0, .999), .001, .001] }] });
    canvas.current.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent<HTMLDivElement>) {
    const g = gesture.current; if (!g || g.pointer !== e.pointerId) return;
    const dx = (e.clientX - g.x) / g.bounds.width, dy = (e.clientY - g.y) / g.bounds.height;
    const original = g.before.items.find(i => i.id === g.id);
    let rect: MossItem['rect'];
    if (!original) {
      const x0 = clamp((g.x - g.bounds.left) / g.bounds.width, 0, 1), y0 = clamp((g.y - g.bounds.top) / g.bounds.height, 0, 1);
      const x1 = clamp(x0 + dx, 0, 1), y1 = clamp(y0 + dy, 0, 1);
      rect = [Math.min(x0, x1), Math.min(y0, y1), Math.max(.001, Math.abs(x1 - x0)), Math.max(.001, Math.abs(y1 - y0))];
    } else {
      const [x, y, w, h] = original.rect;
      rect = g.kind === 'resize' ? [x, y, clamp(w + dx, 1 / value.width, 1 - x), clamp(h + dy, 1 / value.height, 1 - y)] : [clamp(x + dx, 0, 1 - w), clamp(y + dy, 0, 1 - h), w, h];
    }
    onChange({ ...latest.current, items: latest.current.items.map(i => i.id === g.id ? { ...i, rect } : i) });
  }
  function end(e: PointerEvent<HTMLDivElement>, cancel = false) {
    const g = gesture.current; if (!g || g.pointer !== e.pointerId) return;
    gesture.current = null;
    g.releaseScroll();
    if (cancel) { onChange(g.before); return; }
    const item = latest.current.items.find(i => i.id === g.id);
    if (!item || !validRect(item.rect) || (g.kind === 'draw' && (item.rect[2] * value.width < 2 || item.rect[3] * value.height < 2))) onChange(g.before);
    else if (JSON.stringify(g.before) !== JSON.stringify(latest.current)) commit(latest.current, g.before);
  }
  async function saveTemplate() {
    if (!templateName.trim()) return;
    setSaving(true); setMessage('');
    try {
      await put(`/api/image/library/compositions/${crypto.randomUUID()}`, { scope: 'global', revision: null, item: { name: templateName.trim(), prompt: [], negative: [], targets: ['moss'], moss_layout: templateMoss(value) } });
      await qc.invalidateQueries({ queryKey: ['image-lib', 'compositions'] }); setMessage(t('moss.saved'));
    } catch (err) { setMessage(err instanceof ApiError ? tm(err.msg) : String(err)); }
    finally { setSaving(false); }
  }
  const fieldNumbers = selectedItem ? numbers[selectedItem.id] ?? selectedItem.rect.map((n, i) => String(Math.round(n * (i % 2 ? value.height : value.width) * 100) / 100)) : [];
  return <section className="moss-editor" aria-label={t('moss.editor')}>
    <div className="moss-template-row"><label>{t('moss.template')}<select value="" onChange={e => {
      const doc = templates.data?.[e.target.value]?.moss_layout; if (doc) { commit({ ...copy(doc), mode: 'layout', width: value.width, height: value.height }); setSelected(doc.items[0]?.id ?? ''); setNumbers({}); }
    }}><option value="">{t('moss.load_template')}</option>{Object.values(templates.data ?? {}).filter(x => x.moss_layout).map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
      <label>{t('moss.template_name')}<input maxLength={200} value={templateName} onChange={e => setTemplateName(e.target.value)} /></label>
      <button type="button" onClick={saveTemplate} disabled={saving || !templateName.trim() || numericInvalid}>{t('moss.save_template')}</button>
    </div>{message && <p role="status">{message}</p>}
    <label>{t('moss.scene')}<textarea rows={3} maxLength={10000} value={value.scene} aria-invalid={!value.scene.trim()} onChange={e => commit({ ...value, scene: e.target.value })} /></label>
    {errors.includes('scene') && <span className="warn-text small">{t('moss.required')}</span>}
    <div className="moss-toolbar">{labels.map(label => <button type="button" key={label} disabled={value.items.length >= 32} onClick={() => {
      const item = newMossItem(label); setSelected(item.id); commit({ ...value, items: [...value.items, item] });
    }}>{t(`moss.add.${label}`)}</button>)}<button type="button" disabled={!past.length} onClick={undo}>{t('moss.undo')}</button><button type="button" disabled={!future.length} onClick={redo}>{t('moss.redo')}</button></div>
    <div className="moss-workspace"><div className="moss-canvas-column">
      <div className="moss-canvas" ref={canvas} role="group" aria-label={t('moss.canvas')} style={{ aspectRatio: `${value.width}/${value.height}` }} onPointerDown={e => begin(e, null, 'draw')} onPointerMove={move} onPointerUp={e => end(e)} onPointerCancel={e => end(e, true)} onLostPointerCapture={e => end(e, true)}>
        {value.items.map((item, n) => <button key={item.id} type="button" aria-pressed={selected === item.id} aria-label={`${n + 1}. ${item.name || t(`moss.kind.${item.label}`)}`}
          className={`moss-box moss-${item.label}${selected === item.id ? ' selected' : ''}`} style={{ left: `${item.rect[0] * 100}%`, top: `${item.rect[1] * 100}%`, width: `${item.rect[2] * 100}%`, height: `${item.rect[3] * 100}%` } as CSSProperties}
          onClick={() => setSelected(item.id)} onPointerDown={e => begin(e, item, 'move')} onKeyDown={e => {
            if (e.key === 'Delete') { e.preventDefault(); commit({ ...value, items: value.items.filter(i => i.id !== item.id) }); return; }
            if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
            e.preventDefault(); setSelected(item.id); setNumbers({});
            const rect = [...item.rect] as MossItem['rect']; const axis = e.key === 'ArrowLeft' || e.key === 'ArrowRight' ? 0 : 1;
            const index = axis + (e.shiftKey ? 2 : 0); const step = (e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1) / (axis ? value.height : value.width);
            rect[index] += step; if (validRect(rect)) replace({ ...item, rect });
          }}><span>{n + 1} · {item.name || t(`moss.kind.${item.label}`)}{item.binding === 'target' ? ` · ${t('moss.current_target')}` : ''}</span><span className="moss-resize" aria-hidden="true" onPointerDown={e => begin(e, item, 'resize')}>◢</span></button>)}
      </div><p className="small faint">{value.width} × {value.height} px · {t('moss.item_count', { n: value.items.length })}</p><p className="small faint">{t('moss.controls')}</p>
    </div><aside className="moss-inspector" aria-label={t('moss.elements')}>
      <div className="moss-element-list">{value.items.map((item, n) => <button type="button" key={item.id} className={selected === item.id ? 'on' : ''} aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>{n + 1} · {item.name || t(`moss.kind.${item.label}`)}{errors.some(e => e.startsWith(`${item.id}:`)) ? ' !' : ''}</button>)}</div>
      {selectedItem ? <div className="moss-properties">
        <label>{t('moss.name')}<input value={selectedItem.name} maxLength={200} onChange={e => replace({ ...selectedItem, name: e.target.value })} /></label>
        <label>{t('moss.kind')}<select value={selectedItem.label} onChange={e => replace({ ...selectedItem, label: e.target.value as MossItem['label'], binding: 'manual', resolved: undefined })}>{labels.map(label => <option key={label} value={label}>{t(`moss.kind.${label}`)}</option>)}</select></label>
        {selectedItem.label === 'character' && <><label>{t('moss.binding')}<select value={selectedItem.binding} onChange={e => replace({ ...selectedItem, binding: e.target.value as MossItem['binding'], resolved: undefined })}><option value="manual">{t('moss.manual')}</option>{(batch || workId || selectedItem.resolved) && <option value="target">{t('moss.current_target')}</option>}</select></label>
          {selectedItem.binding === 'target' && (batch ? <p className="small">{t('moss.batch_binding')}</p> : workId ? <MossTargetPicker key={selectedItem.id} workId={workId} value={selectedItem.resolved} onChange={resolved => {
            const doc = latest.current;
            const item = doc.items.find(i => i.id === selectedItem.id && i.binding === 'target');
            if (item) commit({ ...doc, items: doc.items.map(i => i.id === item.id ? { ...i, resolved } : i) }, doc);
          }} /> : null)}
          {selectedItem.resolved && <details><summary>{t('moss.resolved')}</summary><pre>{selectedItem.resolved.caption}</pre></details>}
        </>}
        <label>{t(selectedItem.label === 'text' ? 'moss.typography' : 'moss.caption')}<textarea rows={3} maxLength={10000} value={selectedItem.caption} onChange={e => replace({ ...selectedItem, caption: e.target.value })} /></label>
        {selectedItem.label === 'text' && <label>{t('moss.text')}<textarea rows={2} maxLength={4000} value={selectedItem.text ?? ''} onChange={e => replace({ ...selectedItem, text: e.target.value })} /></label>}
        <div className="moss-coordinates">{['x', 'y', 'width', 'height'].map((field, index) => <label key={field}>{t(`moss.${field}`)} (px)<input type="number" step="any" value={fieldNumbers[index]} aria-invalid={numericInvalid} onChange={e => {
          const next = [...fieldNumbers]; next[index] = e.target.value; setNumbers(old => ({ ...old, [selectedItem.id]: next }));
          const rect = next.map((s, n) => s.trim() ? Number(s) / (n % 2 ? value.height : value.width) : NaN);
          if (validRect(rect)) replace({ ...selectedItem, rect: rect as MossItem['rect'] });
        }} /></label>)}</div>
        {(numericInvalid || errors.includes(`${selectedItem.id}:rect`)) && <p className="warn-text small" role="alert">{t('moss.invalid_rect')}</p>}
        {errors.some(e => e.startsWith(`${selectedItem.id}:`) && !e.endsWith(':rect')) && <p className="warn-text small">{t('moss.required')}</p>}
        <button type="button" onClick={remove}>{t('moss.delete')}</button>
      </div> : <p className="faint">{t('moss.select')}</p>}
    </aside></div>
    {errors.includes('items') && <p className="warn-text small">{t('moss.need_items')}</p>}
    {errors.includes('size') && <p className="warn-text small">{t('moss.invalid_size')}</p>}
    <details><summary>{t('single.final_prompt')}</summary>{batch && <p className="small faint">{t('moss.preview_binding')}</p>}<pre>{compileMoss(value, sceneMaterial)}</pre></details>
    <details><summary>{t('moss.limits_title')}</summary><p className="small faint">{t('moss.limits')}</p></details>
  </section>;
}
