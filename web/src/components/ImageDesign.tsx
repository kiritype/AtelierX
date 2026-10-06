import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import type { WorkInfo, ImageView } from '../types';
import { useToast } from './Toasts';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import { useUnsaved } from './Unsaved';

type Prompt = { prompt?: string[]; negative?: string[]; ref?: string; [key: string]: any };
type Outfit = { name: string; slots?: Record<string, Prompt>; negative?: string[]; [key: string]: any };
type Design = { trigger?: string; appearance?: Prompt; outfits?: Record<string, Outfit>; default_outfit?: string | null; retired_outfit_ids?: string[]; next_outfit_number?: number; [key: string]: any };
type DesignResult = { design?: Design; status?: Record<string, string>; revision?: string | null };
const DESIGN_URL = (workId: string, characterId: string) => `/api/works/${workId}/image/characters/${characterId}`;
const splitTags = (text: string) => text.split(/[,\n]/).map((v) => v.trim()).filter(Boolean);
const joinTags = (tags?: string[]) => (tags ?? []).join(', ');

export default function ImageDesign({ workId, characterId, info, onReview: _onReview, beforeConvert, openImage, onDirtyChange }: {
  workId: string; characterId?: string; info: WorkInfo; onReview: (draft: string) => void;
  beforeConvert?: () => Promise<boolean>; openImage?: (view: ImageView, characterId: string, outfitId?: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const toast = useToast(); const qc = useQueryClient();
  const queryKey = ['design', workId, characterId];
  const designQuery = useQuery<DesignResult>({ queryKey, queryFn: () => get(DESIGN_URL(workId, characterId!)), enabled: !!characterId });
  const rules = useQuery<{ slots?: { id: string; name: string }[] }>({ queryKey: ['image-library', 'rules'], queryFn: () => get('/api/image/library/rules') });
  const [draft, setDraft] = useState<Design | null>(null); const [editing, setEditing] = useState(false); const [saving, setSaving] = useState(false);
  const [baseRevision, setBaseRevision] = useState<string | null>(null);
  const [slotSelection, setSlotSelection] = useState<Record<string, string>>({});
  const [llm, setLlm] = useState<LlmOverride>();
  useEffect(() => { if (!editing && designQuery.data) setDraft(designQuery.data.design ? structuredClone(designQuery.data.design) : null); }, [designQuery.data, editing]);
  const dirty = editing && JSON.stringify(draft) !== JSON.stringify(designQuery.data?.design ?? null);
  useEffect(() => { onDirtyChange?.(!!dirty); }, [dirty, onDirtyChange]);
  // Saved with its own button only: leaving asks instead of saving it.
  useUnsaved('image-design', !!dirty);
  if (!characterId) return <div className="empty">{t('image.need_id')}</div>;
  const doc = draft; const status = designQuery.data?.status ?? {};
  const slots = rules.data?.slots ?? [{ id: 'full', name: '전체' }, { id: 'hands', name: '손' }, { id: 'top', name: '상의' }, { id: 'bottom', name: '하의' }, { id: 'shoes', name: '신발' }];
  const slotName = (id: string) => slots.find((s) => s.id === id)?.name ?? id;
  function beginEdit() { setBaseRevision(designQuery.data?.revision ?? null); setDraft(designQuery.data?.design ? structuredClone(designQuery.data.design) : { trigger: `${info.doc.id.toLowerCase()}_${characterId!.toLowerCase()}`, appearance: { prompt: [], negative: [] }, outfits: {}, retired_outfit_ids: [], next_outfit_number: 1 }); setEditing(true); }
  function cancelEdit() { if (dirty && !confirm(t('image.design.discard_confirm'))) return; setDraft(designQuery.data?.design ? structuredClone(designQuery.data.design) : null); setEditing(false); }
  async function saveEdit() {
    if (!draft) return;
    setSaving(true);
    try {
      const result = await put<DesignResult>(DESIGN_URL(workId, characterId!), { design: draft, base_revision: baseRevision });
      qc.setQueryData(queryKey, result); qc.invalidateQueries({ queryKey: ['image-designs', workId] }); qc.invalidateQueries({ queryKey: ['design', workId, characterId] }); qc.invalidateQueries({ queryKey: ['lora', workId] });
      setDraft(result.design ?? draft); setEditing(false); toast({ text: t('image.design.saved') });
    } catch (err) { toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }); }
    finally { setSaving(false); }
  }
  function patchDesign(patch: Partial<Design>) { setDraft((old) => old ? { ...old, ...patch } : old); }
  function addOutfit() {
    if (!draft) return;
    const used = new Set([...Object.keys(draft.outfits ?? {}), ...(draft.retired_outfit_ids ?? [])]);
    let n = Math.max(1, Number(draft.next_outfit_number) || 1); while (used.has(`o${String(n).padStart(2, '0')}`)) n++;
    const id = `o${String(n).padStart(2, '0')}`; const outfit: Outfit = { name: t('image.design.new_outfit'), slots: {}, negative: [] };
    patchDesign({ outfits: { ...(draft.outfits ?? {}), [id]: outfit }, default_outfit: draft.default_outfit ?? id, next_outfit_number: n + 1 });
  }
  function deleteOutfit(id: string) {
    if (!draft || !confirm(t('image.design.delete_confirm', { id }))) return;
    const outfits = { ...(draft.outfits ?? {}) }; delete outfits[id];
    patchDesign({ outfits, retired_outfit_ids: [...new Set([...(draft.retired_outfit_ids ?? []), id])], default_outfit: draft.default_outfit === id ? Object.keys(outfits)[0] ?? null : draft.default_outfit });
  }
  async function convert() {
    if (dirty) { toast({ text: t('image.design.save_before_convert'), tone: 'error' }); return; }
    try { if (beforeConvert && !(await beforeConvert())) return; await post(`${DESIGN_URL(workId, characterId!)}/convert`, { llm }); toast({ text: t('image.convert_started') }); designQuery.refetch(); }
    catch (err) { toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }); }
  }
  const field = (label: string, value: string, onChange: (v: string) => void) => <TagField key={label} label={label} value={value} onChange={onChange} />;
  return <div className="pad col">
    <div className="row"><span className="muted">{t('image.trigger')}</span><code>{doc?.trigger ?? `${info.doc.id.toLowerCase()}_${characterId.toLowerCase()}`}</code><span className="grow" />
      {editing ? <><button disabled={saving} onClick={cancelEdit}>{t('common.cancel')}</button><button className="primary" disabled={!dirty || saving} onClick={saveEdit}>{saving ? t('common.saving') : t('common.save')}</button></> : <button onClick={beginEdit}>{t('image.design.manage')}</button>}
      <button className="primary" disabled={saving || editing} onClick={convert}>{doc ? t('image.reconvert') : t('image.convert')}</button>
    </div>
    <RunLlmSelector task="image_prompt" value={llm} onChange={setLlm} disabled={saving || editing} />
    {doc && <div className="faint">{t('image.design.convert_preserves_manual')}</div>}
    {!doc && !editing && <div className="empty">{t('image.empty')}</div>}
    <fieldset disabled={saving} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
    {doc && <>
      <Part title={t('image.appearance')} status={status.appearance}>
        {editing ? <div className="row" style={{ alignItems: 'start' }}>{field(t('image.design.positive'), joinTags(doc.appearance?.prompt), (v) => patchDesign({ appearance: { ...(doc.appearance ?? {}), prompt: splitTags(v) } }))}{field(t('image.design.negative'), joinTags(doc.appearance?.negative), (v) => patchDesign({ appearance: { ...(doc.appearance ?? {}), negative: splitTags(v) } }))}</div> : <><Tags values={doc.appearance?.prompt ?? []} />{(doc.appearance?.negative?.length ?? 0) > 0 && <div className="row"><span className="faint">{t('image.design.negative')}:</span><Tags values={doc.appearance?.negative ?? []} /></div>}</>}
      </Part>
      {Object.entries(doc.outfits ?? {}).map(([id, outfit]) => <Part key={id} title={<>{t('image.outfit')} {id} · {outfit.name}{doc.default_outfit === id && <span className="chip">{t('image.design.default')}</span>}</>} status={status[`outfit:${id}`]}>
        {editing && <div className="row"><label className="grow">{t('image.design.outfit_name')}<input value={outfit.name ?? ''} onChange={(e) => patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, name: e.target.value } } })} /></label><label>{t('image.design.default')}<input type="radio" checked={doc.default_outfit === id} onChange={() => patchDesign({ default_outfit: id })} /></label><button className="danger" onClick={() => deleteOutfit(id)}>{t('common.delete')}</button></div>}
        {!editing && <div className="row"><button onClick={() => openImage?.('generate', characterId, id)}>{t('flow.generate')}</button><button onClick={() => openImage?.('gallery', characterId, id)}>{t('flow.gallery')}</button><button onClick={() => openImage?.('lora', characterId, id)}>{t('flow.lora')}</button></div>}
        {!editing && (outfit.negative?.length ?? 0) > 0 && <div className="row"><span className="faint">{t('image.design.outfit_negative')}:</span><Tags values={outfit.negative ?? []} /></div>}
        {Object.entries(outfit.slots ?? {}).map(([slot, part]) => <div key={slot} className="row" style={{ alignItems: 'start' }}><strong className="faint" style={{ width: 70 }}>{slotName(slot)}</strong>{part.ref ? <div className="col grow"><span className="chip">→ {part.ref}</span><span className="faint">{t('image.design.shared_ref_kept')}</span>{editing && <button className="self-start" onClick={() => { const next = { ...outfit.slots }; delete next[slot]; patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, slots: { ...next, [slot]: { prompt: [], negative: [] } } } } }); }}>{t('image.design.unlink_ref')}</button>}</div> : editing ? <div className="row grow">{field(t('image.design.positive'), joinTags(part.prompt), (v) => patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, slots: { ...outfit.slots, [slot]: { ...part, prompt: splitTags(v) } } } } }))}{field(t('image.design.negative'), joinTags(part.negative), (v) => patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, slots: { ...outfit.slots, [slot]: { ...part, negative: splitTags(v) } } } } }))}<button onClick={() => { const next = { ...outfit.slots }; delete next[slot]; patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, slots: next } } }); }}>{t('common.delete')}</button></div> : <div className="col"><Tags values={part.prompt ?? []} />{(part.negative?.length ?? 0) > 0 && <div className="row"><span className="faint">{t('image.design.negative')}:</span><Tags values={part.negative ?? []} /></div>}</div>}</div>)}
        {editing && <><div className="row"><select aria-label={t('image.design.add_slot')} value={slotSelection[id] ?? ''} onChange={(e) => setSlotSelection((s) => ({ ...s, [id]: e.target.value }))}><option value="">{t('image.design.add_slot')}</option>{slots.filter((s) => !outfit.slots?.[s.id]).map((s) => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}</select><button disabled={saving} onClick={() => { const slot = slotSelection[id]; if (!slot) return; patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, slots: { ...outfit.slots, [slot]: { prompt: [], negative: [] } } } } }); setSlotSelection((s) => ({ ...s, [id]: '' })); }}>{t('common.add')}</button></div>{field(t('image.design.outfit_negative'), joinTags(outfit.negative), (v) => patchDesign({ outfits: { ...doc.outfits, [id]: { ...outfit, negative: splitTags(v) } } }))}</>}
      </Part>)}
      {editing && <button onClick={addOutfit}>{t('image.design.add_outfit')}</button>}
      {!editing && <div className="row image-flow"><button className="primary" onClick={() => openImage?.('generate', characterId)}>{t('flow.generate')}</button><button onClick={() => openImage?.('gallery', characterId)}>{t('flow.gallery')}</button><button onClick={() => openImage?.('lora', characterId)}>{t('flow.lora')}</button></div>}
    </>}
    </fieldset>
  </div>;
}

function Part({ title, status, children }: { title: React.ReactNode; status?: string; children: React.ReactNode }) {
  const tone: Record<string, string> = { fresh: 'var(--success)', stale: 'var(--warning)', broken: 'var(--danger)', manual: 'var(--text-2)' };
  return <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10 }} className="col"><div className="row"><strong className="grow">{title}</strong>{status && <span style={{ color: tone[status] }}>● {t(`image.status.${status}`)}</span>}</div>{children}</div>;
}
function TagField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [text, setText] = useState(value);
  return <label className="col" style={{ flex: 1, minWidth: 180 }}>{label}<textarea rows={2} value={text} onChange={(e) => { setText(e.target.value); onChange(e.target.value); }} placeholder={t('image.design.tags_hint')} /></label>;
}
function Tags({ values }: { values: string[] }) { return <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>{values.map((v, i) => <span key={i} className="chip">{v}</span>)}</div>; }
