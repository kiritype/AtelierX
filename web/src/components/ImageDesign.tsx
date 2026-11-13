import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post, put } from '../api';
import { t, tm } from '../i18n';
import type { WorkInfo, ImageView } from '../types';
import { useToast } from './Toasts';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import { useUnsaved } from './Unsaved';
import { Dialog } from './ui';
import { splitPrompt } from '../lib/tags';
import { spansOf, type Source } from '../lib/designSource';

type Prompt = { prompt?: string[]; negative?: string[]; ref?: string; source?: Source; [key: string]: unknown };
type Outfit = { name: string; code?: string; slots?: Record<string, Prompt>; negative?: string[]; source?: Source; [key: string]: unknown };
type Design = { trigger?: string; appearance?: Prompt; outfits?: Record<string, Outfit>; default_outfit?: string | null; retired_outfit_ids?: string[]; next_outfit_number?: number; [key: string]: unknown };
type DesignResult = { design?: Design | null; status?: Record<string, string>; revision?: string | null };
type Destination = { view: ImageView; outfitId?: string };
const DESIGN_URL = (workId: string, characterId: string) => `/api/works/${workId}/image/characters/${characterId}`;
// Commas and line breaks outside brackets separate entries, so weighted groups stay whole (#148).
const joinTags = (tags?: string[]) => (tags ?? []).join(', ');

export default function ImageDesign({ workId, characterId, info, onReview: _onReview, beforeConvert, openImage, onDirtyChange }: {
  workId: string; characterId?: string; info: WorkInfo; onReview: (draft: string) => void;
  beforeConvert?: () => Promise<boolean>; openImage?: (view: ImageView, characterId: string, outfitId?: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const toast = useToast(); const qc = useQueryClient();
  const queryKey = ['design', workId, characterId];
  const designQuery = useQuery<DesignResult>({ queryKey, queryFn: () => get(DESIGN_URL(workId, characterId!)), enabled: !!characterId });
  const rules = useQuery<{ slots?: { id: string; name: string }[] }>({ queryKey: ['image-library', 'rules'], queryFn: () => get('/api/image/library/rules'), enabled: !!characterId });
  const [draft, setDraft] = useState<Design | null>(null);
  const [base, setBase] = useState<DesignResult | null>(null);
  const [fieldVersion, setFieldVersion] = useState(0);
  const [saving, setSaving] = useState(false);
  const saveInFlight = useRef<Promise<boolean> | null>(null);
  const [converting, setConverting] = useState(false);
  const [llmOpen, setLlmOpen] = useState(false);
  const [llm, setLlm] = useState<LlmOverride>();
  const [slotSelection, setSlotSelection] = useState<Record<string, string>>({});
  const [destination, setDestination] = useState<Destination | null>(null);
  function editable(result: DesignResult | null): Design {
    return result?.design ?? { trigger: `${info.doc.id.toLowerCase()}_${characterId?.toLowerCase()}`, appearance: { prompt: [], negative: [] }, outfits: {}, retired_outfit_ids: [], next_outfit_number: 1 };
  }
  // Compare with the loaded snapshot, not a background refetch. Opening an empty form is not an edit.
  const dirty = draft !== null && JSON.stringify(draft) !== JSON.stringify(editable(base));
  const busy = saving || converting;
  function accept(result: DesignResult) {
    setBase(result); setDraft(structuredClone(editable(result)));
    setFieldVersion((n) => n + 1); setSlotSelection({});
  }
  useEffect(() => {
    if (!dirty && !busy && designQuery.data && base !== designQuery.data) accept(designQuery.data);
  }, [designQuery.data, base, dirty, busy]);
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  useUnsaved('image-design', dirty, saveEdit);

  async function saveEdit(): Promise<boolean> {
    if (saveInFlight.current) return saveInFlight.current;
    if (!dirty) return true;
    if (!draft || !base || saving || converting || !characterId) return false;
    setSaving(true);
    const pending = (async () => {
      try {
        const result = await put<DesignResult>(DESIGN_URL(workId, characterId), { design: draft, base_revision: base.revision ?? null });
        qc.setQueryData(queryKey, result); accept(result);
        qc.invalidateQueries({ queryKey: ['image-designs', workId] });
        qc.invalidateQueries({ queryKey: ['design', workId, characterId] });
        qc.invalidateQueries({ queryKey: ['lora', workId] });
        toast({ text: t('image.design.saved') });
        return true;
      } catch (err) {
        toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
        return false;
      } finally { setSaving(false); saveInFlight.current = null; }
    })();
    saveInFlight.current = pending;
    return pending;
  }
  async function revert() {
    if (!confirm(t('image.design.discard_confirm'))) return;
    setSaving(true);
    try {
      const result = await designQuery.refetch();
      if (result.isError) throw result.error;
      if (result.data) accept(result.data);
    } catch (err) { toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }); }
    finally { setSaving(false); }
  }
  function patchDesign(patch: Partial<Design>) { setDraft((old) => old ? { ...old, ...patch } : old); }
  function patchOutfit(id: string, patch: Partial<Outfit>) {
    setDraft((old) => old?.outfits?.[id] ? { ...old, outfits: { ...old.outfits, [id]: { ...old.outfits[id], ...patch } } } : old);
  }
  function addOutfit() {
    if (!draft) return;
    const used = new Set([...Object.keys(draft.outfits ?? {}), ...(draft.retired_outfit_ids ?? [])]);
    let n = Math.max(1, Number(draft.next_outfit_number) || 1); while (used.has(`o${String(n).padStart(2, '0')}`)) n++;
    const id = `o${String(n).padStart(2, '0')}`;
    patchDesign({ outfits: { ...(draft.outfits ?? {}), [id]: { name: t('image.design.new_outfit'), slots: {}, negative: [] } }, default_outfit: draft.default_outfit ?? id, next_outfit_number: n + 1 });
  }
  function deleteOutfit(id: string) {
    if (!draft || !confirm(t('image.design.delete_confirm', { id }))) return;
    const outfits = { ...(draft.outfits ?? {}) }; delete outfits[id];
    patchDesign({ outfits, retired_outfit_ids: [...new Set([...(draft.retired_outfit_ids ?? []), id])], default_outfit: draft.default_outfit === id ? Object.keys(outfits)[0] ?? null : draft.default_outfit });
  }
  async function convert() {
    if (dirty || busy) return;
    setConverting(true);
    try {
      if (beforeConvert && !(await beforeConvert())) return;
      await post(`${DESIGN_URL(workId, characterId!)}/convert`, { llm });
      toast({ text: t('image.convert_started') }); designQuery.refetch();
    } catch (err) { toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }); }
    finally { setConverting(false); }
  }
  function navigate(view: ImageView, outfitId?: string) {
    if (dirty) setDestination({ view, outfitId });
    else openImage?.(view, characterId!, outfitId);
  }
  function continueToImage(target: Destination) {
    setDestination(null); openImage?.(target.view, characterId!, target.outfitId);
  }
  const navigation = (outfitId?: string) => <div className="row wrap image-flow">
    <button className={outfitId ? undefined : 'primary'} onClick={() => navigate('generate', outfitId)}>{t('flow.generate')}</button>
    <button onClick={() => navigate('gallery', outfitId)}>{t('flow.gallery')}</button>
    <button onClick={() => navigate('lora', outfitId)}>{t('flow.lora')}</button>
  </div>;
  // Remount only when accepting a saved/reverted snapshot; typing keeps delimiters and unfinished weights intact.
  const field = (label: string, tags: string[] | undefined, onChange: (v: string[]) => void) =>
    <TagField key={`${fieldVersion}:${label}`} label={label} value={joinTags(tags)} onChange={(v) => onChange(splitPrompt(v))} />;
  if (!characterId) return <div className="empty">{t('image.need_id')}</div>;
  if (!draft) return <div className="empty">{designQuery.isError ? <><p>{tm((designQuery.error as ApiError).msg ?? { key: '', text: String(designQuery.error) })}</p><button onClick={() => designQuery.refetch()}>{t('common.retry')}</button></> : t('common.loading')}</div>;
  const doc = draft; const status = base?.status ?? {};
  const slots = rules.data?.slots ?? [{ id: 'full', name: 'full' }, { id: 'hands', name: 'hands' }, { id: 'top', name: 'top' }, { id: 'bottom', name: 'bottom' }, { id: 'shoes', name: 'shoes' }];
  const slotName = (id: string) => slots.find((s) => s.id === id)?.name ?? id;
  const sameOutfitCode = (id: string) => {
    const code = (doc.outfits?.[id]?.code ?? '').trim();
    if (!code) return [];
    return Object.entries(doc.outfits ?? {}).filter(([other, o]) => other !== id && (o.code ?? '').trim() === code).map(([other, o]) => `${o.name} (${other})`);
  };
  return <div className="pad col image-design">
    <div className="row wrap">
      <strong>{t('image.design.title')}</strong><span className={dirty ? 'warn-text small' : 'faint small'} role="status">{t(dirty ? 'image.design.unsaved' : base?.design ? 'image.design.clean' : 'image.design.new')}</span><span className="grow" />
      <button disabled={!dirty || busy} onClick={revert}>{t('image.design.revert')}</button>
      <button className="primary" disabled={!dirty || busy} onClick={saveEdit}>{saving ? t('common.saving') : t('common.save')}</button>
    </div>
    <div className="faint small">{t('image.design.manual_hint')}</div>
    <details className="image-design-assist" open={llmOpen} onToggle={(e) => setLlmOpen(e.currentTarget.open)}>
      <summary>{t('image.design.llm_assist')}</summary>
      {llmOpen && <div className="col">
        <p className="faint small">{t('image.design.convert_preserves_manual')}</p>
        <RunLlmSelector task="image_prompt" value={llm} onChange={setLlm} disabled={busy} />
        <div className="row wrap"><button disabled={dirty || busy} onClick={convert}>{t('image.design.convert_all')}</button>{dirty && <span className="warn-text small">{t('image.design.save_before_convert')}</span>}</div>
        <div className="faint small">{t('image.range.hint')}</div>
      </div>}
    </details>
    <fieldset className="col image-design-fields" disabled={busy}>
      <Part title={t('image.appearance')} status={status.appearance} source={doc.appearance?.source}>
        <div className="image-design-prompts">
          {field(t('image.design.positive'), doc.appearance?.prompt, (prompt) => patchDesign({ appearance: { ...doc.appearance, prompt } }))}
          {field(t('image.design.negative'), doc.appearance?.negative, (negative) => patchDesign({ appearance: { ...doc.appearance, negative } }))}
        </div>
      </Part>
      {Object.entries(doc.outfits ?? {}).map(([id, outfit]) => <Part key={id} title={<><span>{outfit.name?.trim() || `${t('image.outfit')} ${id}`}</span>{outfit.name?.trim() && <span className="faint mono small"> · {id}</span>}{outfit.code && <span className="chip small mono" title={t('lib.code')}>{outfit.code}</span>}{doc.default_outfit === id && <span className="chip">{t('image.design.default')}</span>}</>} status={status[`outfit:${id}`]} source={outfit.source}>
        <div className="row wrap image-design-outfit-meta">
          <label className="col grow">{t('image.design.outfit_name')}<input value={outfit.name ?? ''} onChange={(e) => patchOutfit(id, { name: e.target.value })} /></label>
          <label className="col" title={t('lib.code_hint')}>{t('lib.code')}<input className="mono image-design-code" value={outfit.code ?? ''} onChange={(e) => patchOutfit(id, { code: e.target.value })} /></label>
          <label className="row"><input type="radio" name={`default-outfit-${workId}-${characterId}`} checked={doc.default_outfit === id} onChange={() => patchDesign({ default_outfit: id })} />{t('image.design.default')}</label>
          <button className="danger" onClick={() => deleteOutfit(id)}>{t('common.delete')}</button>
        </div>
        {sameOutfitCode(id).length > 0 && <span className="warn-text small">{t('lib.code_same', { names: sameOutfitCode(id).join(', ') })}</span>}
        {Object.entries(outfit.slots ?? {}).map(([slot, part]) => <div key={slot} className="col image-design-slot">
          <div className="row wrap"><strong className="grow faint">{slotName(slot)}</strong><button onClick={() => { const next = { ...outfit.slots }; delete next[slot]; patchOutfit(id, { slots: next }); }}>{t('common.delete')}</button></div>
          {part.ref ? <div className="col"><span className="chip self-start">→ {part.ref}</span><span className="faint">{t('image.design.shared_ref_kept')}</span><button className="self-start" onClick={() => patchOutfit(id, { slots: { ...outfit.slots, [slot]: { prompt: [], negative: [] } } })}>{t('image.design.unlink_ref')}</button></div> : <div className="image-design-prompts">
            {field(t('image.design.positive'), part.prompt, (prompt) => patchOutfit(id, { slots: { ...outfit.slots, [slot]: { ...part, prompt } } }))}
            {field(t('image.design.negative'), part.negative, (negative) => patchOutfit(id, { slots: { ...outfit.slots, [slot]: { ...part, negative } } }))}
          </div>}
        </div>)}
        <div className="row wrap"><select aria-label={t('image.design.add_slot')} value={slotSelection[id] ?? ''} onChange={(e) => setSlotSelection((s) => ({ ...s, [id]: e.target.value }))}><option value="">{t('image.design.add_slot')}</option>{slots.filter((s) => !outfit.slots?.[s.id]).map((s) => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}</select>
          <button disabled={!slotSelection[id]} onClick={() => { const slot = slotSelection[id]; if (!slot) return; patchOutfit(id, { slots: { ...outfit.slots, [slot]: { prompt: [], negative: [] } } }); setSlotSelection((s) => ({ ...s, [id]: '' })); }}>{t('common.add')}</button></div>
        <details><summary className="faint">{t('image.design.outfit_negative')}</summary>{field(t('image.design.outfit_negative'), outfit.negative, (negative) => patchOutfit(id, { negative }))}</details>
        {navigation(id)}
      </Part>)}
      <button className="self-start" onClick={addOutfit}>{t('image.design.add_outfit')}</button>
      <details><summary className="faint">{t('image.design.more')}</summary><div className="row wrap"><span className="muted">{t('image.trigger')}</span><code>{doc.trigger ?? `${info.doc.id.toLowerCase()}_${characterId.toLowerCase()}`}</code></div></details>
      {navigation()}
    </fieldset>
    {destination && <Dialog title={t('leave.title')} onClose={() => !busy && setDestination(null)} actions={<>
      <button className="danger" disabled={busy} onClick={() => { accept(designQuery.data ?? base!); continueToImage(destination); }}>{t('leave.discard')}</button>
      <button className="primary" disabled={busy} onClick={async () => { if (await saveEdit()) continueToImage(destination); }}>{t('image.design.save_continue')}</button>
    </>}><p>{t('image.design.leave_hint')}</p></Dialog>}
  </div>;
}

function Part({ title, status, source, children }: { title: React.ReactNode; status?: string; source?: Source; children: React.ReactNode }) {
  const tone: Record<string, string> = { fresh: 'var(--success)', stale: 'var(--warning)', broken: 'var(--danger)', manual: 'var(--text-2)', unsourced: 'var(--warning)' };
  return <section className="col image-design-part"><div className="row wrap"><strong className="grow">{title}</strong>{status && <span style={{ color: tone[status] }} title={t(`image.status_hint.${status}`)}>● {t(`image.status.${status}`)}</span>}</div>{children}<Sources source={source} /></section>;
}
// The text a part came from (#150), folded: quoted by a whole-text conversion or chosen as a range.
export function Sources({ source }: { source?: Source }) {
  const spans = spansOf({ source });
  if (!spans.length) return null;
  return <details className="small"><summary className="faint">{t('image.source.title', { n: spans.length })}</summary><div className="col" style={{ gap: 4, marginTop: 4 }}>{spans.map((s, i) => <div key={i} className="row" style={{ alignItems: 'start' }}><span className="chip small">{t(`image.source.${s.by}`)}</span><span className="grow" style={{ whiteSpace: 'pre-wrap' }}>{s.text}</span></div>)}</div></details>;
}
function TagField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [text, setText] = useState(value);
  return <label className="col image-design-tag-field">{label}<textarea rows={3} value={text} onChange={(e) => { setText(e.target.value); onChange(e.target.value); }} placeholder={t('image.design.tags_hint')} /></label>;
}
