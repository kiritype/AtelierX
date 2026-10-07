import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import { ConsistencyReview, JsxPromptReview, RelationsReview } from './SupportReviews';
import { useToast } from './Toasts';
import EditorTaskReview from './EditorTaskReview';
import AgentFileReview from './AgentFileReview';
import { Sources } from './ImageDesign';
import { picked } from '../lib/designSource';

const utf8 = (text: string) => new TextEncoder().encode(text).length;

export default function ReviewTab({
  workId,
  draftId,
  onDone,
  openItem,
}: {
  workId: string;
  draftId: string;
  onDone: () => void;
  openItem: (path: string) => void;
}) {
  const draft = useQuery({ queryKey: ['draft', workId, draftId], queryFn: () => get(`/api/works/${workId}/drafts/${draftId}`) });
  if (!draft.data) return null;
  if (['content_review', 'text_edit'].includes(draft.data.kind)) return <EditorTaskReview workId={workId} draft={draft.data} onDone={onDone} />;
  if (draft.data.kind === 'agent_file') return <AgentFileReview workId={workId} draft={draft.data} onDone={onDone} openItem={openItem} />;
  if (draft.data.kind === 'compression') return <CompressionReview workId={workId} draft={draft.data} onDone={onDone} />;
  if (draft.data.kind === 'image_prompt') return <ImagePromptReview workId={workId} draft={draft.data} onDone={onDone} />;
  if (draft.data.kind === 'authoring') return <AuthoringReview workId={workId} draft={draft.data} onDone={onDone} />;
  if (draft.data.kind === 'relations') return <RelationsReview workId={workId} draft={draft.data} onDone={onDone} />;
  if (draft.data.kind === 'consistency') return <ConsistencyReview workId={workId} draft={draft.data} onDone={onDone} openItem={openItem} />;
  if (draft.data.kind === 'jsx_prompt') return <JsxPromptReview workId={workId} draft={draft.data} onDone={onDone} />;
  return <div className="empty">{t('review.unsupported')}</div>;
}

function useFinish(workId: string, onDone: () => void) {
  const qc = useQueryClient();
  return () => {
    for (const key of ['drafts', 'drafts-all', 'tree', 'check', 'snapshots', 'design', 'image-designs', 'lora']) qc.invalidateQueries({ queryKey: [key, workId] });
    qc.invalidateQueries({ queryKey: ['item', workId] });
    onDone();
  };
}

function CompressionReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  const toast = useToast();
  const finish = useFinish(workId, onDone);
  const candidates: any[] = draft.candidates;
  const blocks: any[] = draft.blocks ?? [];
  // choice per original block number: -1 = original, n = candidate index
  const [choice, setChoice] = useState<Record<number, number>>(() => draft.composition?.choice ?? Object.fromEntries(blocks.map((b) => [b.n, 0])));
  const [edits, setEdits] = useState<Record<number, string>>(draft.composition?.edits ?? {});
  const [onlyChanged, setOnlyChanged] = useState(false);
  const pending = draft.status === 'pending';

  const resultOf = (n: number, c: number) => {
    if (c < 0) return blocks.find((b) => b.n === n)?.text ?? '';
    const hit = candidates[c].blocks.find((r: any) => r.from <= n && n <= r.to);
    if (!hit) return '';
    return hit.from === n ? hit.text ?? '' : null; // merged blocks show once
  };

  const composed = useMemo(() => {
    const parts: string[] = [];
    for (const block of blocks) {
      if (edits[block.n] !== undefined) {
        parts.push(edits[block.n]);
        continue;
      }
      const text = resultOf(block.n, choice[block.n] ?? 0);
      if (text) parts.push(text);
    }
    return parts.join('\n\n') + '\n';
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [choice, edits, blocks]);

  useEffect(() => {
    if (!pending) return;
    const timer = setTimeout(() => {
      fetch(`/api/works/${workId}/drafts/${draft.id}/composition`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ choice, edits }),
      });
    }, 800);
    return () => clearTimeout(timer);
  }, [choice, edits, pending, workId, draft.id]);

  const originalSize = blocks.reduce((sum, b) => sum + utf8(b.text), 0);
  const target = draft.request?.target_size;

  async function apply(mode: 'overwrite' | 'new_file') {
    try {
      const result = await post(`/api/works/${workId}/drafts/${draft.id}/apply`, { text: composed, mode, enable: 'new' });
      toast({ text: t('review.applied', { path: result.path }) });
      finish();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  const cols = 2 + candidates.length;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div className="row pad" style={{ borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <strong>{t('review.compression_title', { path: draft.target.path })}</strong>
        <span className="muted">
          {originalSize.toLocaleString()} B → {utf8(composed).toLocaleString()} B{target ? ` / ${t('review.target')} ${target.toLocaleString()} B` : ''}
        </span>
        <label className="row faint">
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} /> {t('review.only_changed')}
        </label>
        <span className="grow" />
        {pending ? (
          <>
            <button
              onClick={async () => {
                await post(`/api/works/${workId}/drafts/${draft.id}/discard`);
                finish();
              }}
            >
              {t('review.discard')}
            </button>
            <button onClick={() => apply('new_file')}>{t('review.apply_new')}</button>
            <button className="primary" onClick={() => apply('overwrite')}>
              {t('review.apply_overwrite')}
            </button>
          </>
        ) : (
          <span className="chip">{t(`draft.status.${draft.status}`)}</span>
        )}
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <div className="review" style={{ ['--cols' as string]: cols }}>
          <div className="review-row review-head">
            <div>#</div>
            <div>{t('review.original')}</div>
            {candidates.map((c, i) => (
              <div key={i}>
                {t('review.candidate', { n: i + 1 })} <span className="faint">{c.size?.toLocaleString()} B</span>
              </div>
            ))}
            <div>{t('review.result')}</div>
          </div>
          {blocks.map((block) => {
            const picked = choice[block.n] ?? 0;
            const texts = candidates.map((_, i) => resultOf(block.n, i));
            if (onlyChanged && texts.every((x) => x === block.text)) return null;
            return (
              <div key={block.n} className="review-row">
                <div className="faint">B{block.n}</div>
                <div className={`pick${picked === -1 ? ' on' : ''}`} onClick={() => pending && setChoice({ ...choice, [block.n]: -1 })}>
                  {block.text}
                </div>
                {texts.map((text, i) => (
                  <div key={i} className={`pick${picked === i ? ' on' : ''}`} onClick={() => pending && setChoice({ ...choice, [block.n]: i })}>
                    {text === null ? <span className="faint">↑</span> : text || <span className="faint">{t('review.deleted')}</span>}
                  </div>
                ))}
                <div>
                  <textarea
                    style={{ width: '100%', minHeight: 40, border: edits[block.n] !== undefined ? '1px solid var(--accent)' : undefined }}
                    disabled={!pending}
                    value={edits[block.n] ?? resultOf(block.n, picked) ?? ''}
                    onChange={(e) => setEdits({ ...edits, [block.n]: e.target.value })}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="faint pad">{draft.model?.provider === 'mock' ? t('review.mock_note') : t('review.model', { name: draft.model?.name })}</p>
      </div>
    </div>
  );
}

function ImagePromptReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  // A range conversion (#150) changes one part: the one it names is taken, the rest stay as they are.
  const toast = useToast();
  const finish = useFinish(workId, onDone);
  const proposed = draft.candidates[0].design;
  const previous = draft.request?.previous_design;
  const focus: string | null = draft.request?.focus ?? null;
  const [useAppearance, setUseAppearance] = useState(focus === 'appearance' || !picked(previous?.appearance));
  const [keepOutfits, setKeepOutfits] = useState<string[]>(() =>
    Object.keys(proposed.outfits).filter((id) => focus !== `outfit:${id}` && previous?.outfits?.[id] && picked(previous.outfits[id])),
  );
  const shows = (key: string) => !focus || focus === key;
  const design = draft.status === 'applied' && draft.applied_design ? draft.applied_design : {
    ...proposed,
    appearance: useAppearance ? proposed.appearance : previous?.appearance ?? proposed.appearance,
    outfits: Object.fromEntries(Object.entries(proposed.outfits).map(([id, outfit]) => [id, keepOutfits.includes(id) ? previous?.outfits?.[id] ?? outfit : outfit])),
  };
  const pending = draft.status === 'pending';
  return (
    <div className="pad col">
      <div className="row">
        <strong className="grow">{t('review.image_title', { path: draft.target.path })}</strong>
        {pending && (
          <>
            <button
              onClick={async () => {
                await post(`/api/works/${workId}/drafts/${draft.id}/discard`);
                finish();
              }}
            >
              {t('review.discard')}
            </button>
            <button
              className="primary"
              onClick={async () => {
                try {
                  await post(`/api/works/${workId}/drafts/${draft.id}/apply`, { design });
                  toast({ text: t('review.image_applied') });
                  finish();
                } catch (err) {
                  toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
                }
              }}
            >
              {t('review.apply')}
            </button>
          </>
        )}
      </div>
      {previous && <p className="faint">{t('image.design.review_selection')}</p>}
      {shows('appearance') && (
        <>
          <div className="section-title">{t('image.appearance')}</div>
          {pending && previous?.appearance && <label><input type="checkbox" checked={useAppearance} onChange={(e) => setUseAppearance(e.target.checked)} /> {t('image.design.use_converted')}</label>}
          <div className="row" style={{ flexWrap: 'wrap', gap: 4 }}>
            {(design.appearance?.prompt ?? []).map((tag: string, i: number) => (
              <span key={i} className="chip">
                {tag}
              </span>
            ))}
          </div>
          <Sources source={design.appearance?.source} />
        </>
      )}
      {Object.entries(design.outfits).filter(([key]) => shows(`outfit:${key}`)).map(([key, outfit]: [string, any]) => (
        <div key={key}>
          <div className="section-title">
            {t('image.outfit')} {key} · {outfit.name}{' '}
            {pending && <span className="chip small">{previous?.outfits?.[key] ? t('image.review.update') : t('image.review.new')}</span>}
          </div>
          {pending && previous?.outfits?.[key] && <label><input type="checkbox" checked={!keepOutfits.includes(key)} onChange={(e) => setKeepOutfits((ids) => e.target.checked ? ids.filter((id) => id !== key) : [...ids, key])} /> {t('image.design.use_converted')}</label>}
          {Object.entries(outfit.slots).map(([slot, value]: [string, any]) => (
            <div key={slot} className="row">
              <span className="faint" style={{ width: 50 }}>
                {slot}
              </span>
              {(value.prompt ?? []).map((tag: string, i: number) => (
                <span key={i} className="chip">
                  {tag}
                </span>
              ))}
            </div>
          ))}
          <Sources source={outfit.source} />
        </div>
      ))}
      <p className="faint">{draft.model?.provider === 'mock' ? t('review.mock_note') : t('review.model', { name: draft.model?.name })}</p>
    </div>
  );
}

type SkeletonFile = { path: string; kind: string; id: string; keywords: string[]; body: string; exists: boolean };

// 04-authoring: 뼈대 검토 — pick files, adjust path and body, then create. Existing files are never overwritten.
function AuthoringReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  const toast = useToast();
  const finish = useFinish(workId, onDone);
  const qc = useQueryClient();
  const [files, setFiles] = useState<SkeletonFile[]>(draft.candidates[0].files);
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(files.flatMap((f, n) => (f.exists ? [] : [n]))));
  const [open, setOpen] = useState<number | null>(0);
  const [withRelations, setWithRelations] = useState(true);
  const relations: any[] = draft.candidates[0].relations ?? [];
  const pending = draft.status === 'pending';
  const update = (n: number, file: SkeletonFile) => setFiles(files.map((f, i) => (i === n ? file : f)));

  async function create() {
    try {
      const result = await post(`/api/works/${workId}/drafts/${draft.id}/apply`, {
        files: files.filter((_, n) => chosen.has(n)),
        relations: withRelations ? relations : [],
      });
      toast({ text: t('authoring.created', { n: result.created.length, skipped: result.skipped.length }) });
      qc.invalidateQueries({ queryKey: ['relations', workId] });
      finish();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <div className="pad col">
      <div className="row">
        <strong className="grow">{t('authoring.review_title', { scale: t(`scale.${draft.target.scale}`) })}</strong>
        {pending && (
          <>
            <button
              onClick={async () => {
                await post(`/api/works/${workId}/drafts/${draft.id}/discard`);
                finish();
              }}
            >
              {t('review.discard')}
            </button>
            <button className="primary" disabled={chosen.size === 0 && !withRelations} onClick={create}>
              {t('authoring.create', { n: chosen.size })}
            </button>
          </>
        )}
      </div>
      <p className="faint">{draft.model?.provider === 'mock' ? t('authoring.mock_note') : t('review.model', { name: draft.model?.name })}</p>
      <div className="skeleton">
        <div className="skeleton-list">
          {files.map((file, n) => (
            <div key={n} className={`list-row${open === n ? ' sel' : ''}`} onClick={() => setOpen(n)}>
              <input
                type="checkbox"
                checked={chosen.has(n)}
                disabled={file.exists || !pending}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => {
                  const next = new Set(chosen);
                  if (e.target.checked) next.add(n);
                  else next.delete(n);
                  setChosen(next);
                }}
              />
              <span className="grow">{file.path}</span>
              <span className="faint">
                {t(`kind.${file.kind}`)} {file.id}
              </span>
              {file.exists && <span className="chip">{t('authoring.exists')}</span>}
            </div>
          ))}
          <label className="list-row">
            <input type="checkbox" checked={withRelations} disabled={!pending || relations.length === 0} onChange={(e) => setWithRelations(e.target.checked)} />
            <span className="grow">{t('authoring.relations', { n: relations.length })}</span>
          </label>
        </div>
        {open !== null && files[open] && (
          <div className="col skeleton-detail">
            <label className="col" style={{ gap: 2 }}>
              <span className="muted">{t('authoring.path')}</span>
              <input value={files[open].path} disabled={!pending} onChange={(e) => update(open, { ...files[open], path: e.target.value })} />
            </label>
            {files[open].keywords.length > 0 && (
              <div className="faint">
                {t('form.keywords')}: {files[open].keywords.join(', ')}
              </div>
            )}
            <textarea
              className="mono grow"
              rows={16}
              value={files[open].body}
              disabled={!pending}
              onChange={(e) => update(open, { ...files[open], body: e.target.value })}
            />
          </div>
        )}
      </div>
    </div>
  );
}
