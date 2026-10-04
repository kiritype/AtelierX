import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import type { TreeEntry } from '../types';
import { useToast } from './Toasts';

// Review screens for the authoring-support drafts: relations from bodies, consistency issues, JSX prompt text.

function useDone(workId: string, onDone: () => void) {
  const qc = useQueryClient();
  return () => {
    for (const key of ['drafts', 'drafts-all', 'tree', 'check', 'snapshots', 'relations']) qc.invalidateQueries({ queryKey: [key, workId] });
    qc.invalidateQueries({ queryKey: ['item', workId] });
    onDone();
  };
}

function ModelLine({ draft }: { draft: any }) {
  return <p className="faint">{draft.model?.provider === 'mock' ? t('review.mock_generic') : t('review.model', { name: draft.model?.name })}</p>;
}

function DiscardButton({ workId, draft, done }: { workId: string; draft: any; done: () => void }) {
  return (
    <button
      onClick={async () => {
        await post(`/api/works/${workId}/drafts/${draft.id}/discard`);
        done();
      }}
    >
      {t('review.discard')}
    </button>
  );
}

export function RelationsReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  const toast = useToast();
  const done = useDone(workId, onDone);
  const rel = useQuery({ queryKey: ['relations', workId], queryFn: () => get(`/api/works/${workId}/relations`) });
  const rows: any[] = draft.candidates[0].rows;
  const people: any[] = draft.candidates[0].people ?? [];
  const [chosen, setChosen] = useState<Set<number>>(() => new Set(rows.flatMap((r, n) => (r.status === 'new' ? [n] : []))));
  // "different" rows would overwrite what the user wrote, so they start unchecked.
  const pending = draft.status === 'pending';
  const names: Record<string, string> = Object.fromEntries([...(rel.data?.view ?? []), ...people].map((p: any) => [p.id, p.name]));
  const nameOf = (id: string) => names[id] ?? id;

  return (
    <div className="pad col">
      <div className="row">
        <strong className="grow">{t('relations.extract_title')}</strong>
        {pending && (
          <>
            <DiscardButton workId={workId} draft={draft} done={done} />
            <button
              className="primary"
              disabled={chosen.size === 0}
              onClick={async () => {
                try {
                  const result = await post(`/api/works/${workId}/drafts/${draft.id}/apply`, { rows: rows.filter((_, n) => chosen.has(n)) });
                  toast({ text: t('relations.extract_added', { n: result.added }) });
                  done();
                } catch (err) {
                  toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
                }
              }}
            >
              {t('relations.extract_add', { n: chosen.size })}
            </button>
          </>
        )}
      </div>
      <ModelLine draft={draft} />
      {people.length > 0 && <p className="faint">{t('relations.extract_new_people', { names: people.map((p) => `${p.name}(${p.id})`).join(', ') })}</p>}
      {rows.length === 0 && <div className="empty">{t('relations.extract_none')}</div>}
      <table className="plain">
        <tbody>
          {rows.map((row, n) => (
            <tr key={n} className={row.status === 'same' ? 'faint' : ''}>
              <td>
                <input
                  type="checkbox"
                  disabled={!pending}
                  checked={chosen.has(n)}
                  onChange={(e) => {
                    const next = new Set(chosen);
                    if (e.target.checked) next.add(n);
                    else next.delete(n);
                    setChosen(next);
                  }}
                />
              </td>
              <td>
                <span className={`chip status-${row.status}`}>{t(`relations.status.${row.status}`)}</span>
              </td>
              <td>
                {row.type === 'relation' ? (
                  <>
                    {nameOf(row.from)} → {nameOf(row.to)} · {row.kind}
                    {row.calls && ` · "${row.calls}"`}
                    {row.status === 'different' && row.old && (
                      <div className="faint">
                        {t('relations.extract_now')}: {row.old.kind} {row.old.calls && `· "${row.old.calls}"`}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    {nameOf(row.subject)} · {row.key}: {row.value}
                    {row.status === 'different' && row.old && (
                      <div className="faint">
                        {t('relations.extract_now')}: {row.old.value}
                      </div>
                    )}
                  </>
                )}
              </td>
              <td className="faint" style={{ maxWidth: 320 }}>
                {row.quote && `“${row.quote}”`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ConsistencyReview({
  workId,
  draft,
  onDone,
  openItem,
}: {
  workId: string;
  draft: any;
  onDone: () => void;
  openItem: (path: string) => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const done = useDone(workId, onDone);
  const [issues, setIssues] = useState<any[]>(draft.candidates[0].issues);
  const [showFolded, setShowFolded] = useState(false);
  const open = issues.filter((i) => i.status === 'open').length;

  async function act(n: number, action: string) {
    let note = '';
    if (action === 'ignore') {
      const answer = prompt(t('consistency.ignore_prompt'));
      if (answer === null) return;
      note = answer;
    }
    try {
      const result = await post(`/api/works/${workId}/drafts/${draft.id}/issues/${n}`, { action, note });
      if (result.error === 'changed') toast({ text: t('consistency.changed'), tone: 'error' });
      setIssues(issues.map((issue, i) => (i === n ? result.issue : issue)));
      qc.invalidateQueries({ queryKey: ['item', workId] });
      qc.invalidateQueries({ queryKey: ['check', workId] });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <div className="pad col">
      <div className="row">
        <strong className="grow">{t('consistency.title', { n: open })}</strong>
        <label className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={showFolded} onChange={(e) => setShowFolded(e.target.checked)} />
          {t('consistency.show_folded')}
        </label>
        {draft.status === 'pending' && (
          <button
            className="primary"
            onClick={async () => {
              await post(`/api/works/${workId}/drafts/${draft.id}/discard`);
              done();
            }}
          >
            {t('consistency.finish')}
          </button>
        )}
      </div>
      <ModelLine draft={draft} />
      {issues.length === 0 && <div className="empty">{t('consistency.none')}</div>}
      {issues.map((issue, n) =>
        !showFolded && issue.status !== 'open' && issue.status !== 'applied' ? null : (
          <div key={n} className={`issue-card ${issue.status}`}>
            <div className="row">
              <span className={`chip type-${issue.type}`}>{t(`consistency.type.${issue.type}`)}</span>
              <span className="grow">{issue.explain}</span>
              {issue.status !== 'open' && <span className="faint">{t(`consistency.status.${issue.status}`)}</span>}
            </div>
            {issue.quote && (
              <div className="quote">
                “{issue.quote}”{' '}
                {issue.path ? (
                  <a href="#" onClick={(e) => (e.preventDefault(), openItem(issue.path))}>
                    {issue.path}
                  </a>
                ) : null}
                {!issue.verified && <span className="warn-text"> · {t('consistency.unverified')}</span>}
              </div>
            )}
            {issue.suggest && (
              <div className="mono suggest">
                <span className="del">{issue.suggest.find}</span> → <span className="ins">{issue.suggest.replace}</span>{' '}
                <span className="faint">({issue.suggest.path})</span>
              </div>
            )}
            {issue.status === 'open' && (
              <div className="row">
                {issue.suggest && <button onClick={() => act(n, 'apply')}>{t('consistency.apply')}</button>}
                <button onClick={() => act(n, 'resolve')}>{t('consistency.resolve')}</button>
                <button onClick={() => act(n, 'ignore')}>{t('consistency.ignore')}</button>
              </div>
            )}
          </div>
        ),
      )}
    </div>
  );
}

function flatten(entries: TreeEntry[]): TreeEntry[] {
  return entries.flatMap((e) => (e.type === 'folder' ? flatten(e.children ?? []) : e.type === 'item' ? [e] : []));
}

export function JsxPromptReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  const toast = useToast();
  const done = useDone(workId, onDone);
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const items = flatten(tree.data ?? []).filter((e) => ['main', 'lorebook', 'character', 'start'].includes(e.kind ?? ''));
  const main = items.find((e) => e.kind === 'main' && e.enabled !== false);
  const [text, setText] = useState<string>(draft.candidates[0].text);
  const [elements, setElements] = useState<any[]>(draft.candidates[0].elements ?? []);
  const [target, setTarget] = useState<string>('');
  const [newPath, setNewPath] = useState(`${draft.target.name} 문구.md`);
  const [position, setPosition] = useState<'end' | 'heading'>('end');
  const [heading, setHeading] = useState('');
  const pending = draft.status === 'pending';
  const chosen = target || main?.path || '';
  const targetItem = useQuery({
    queryKey: ['item', workId, chosen],
    queryFn: () => get(`/api/works/${workId}/file?path=${encodeURIComponent(chosen)}`),
    enabled: !!chosen && chosen !== '__new',
  });
  const headings = (targetItem.data?.body ?? '').split('\n').filter((l: string) => l.startsWith('#')).map((l: string) => l.replace(/^#+\s*/, ''));

  useEffect(() => {
    const timer = setTimeout(async () => setElements(await post(`/api/works/${workId}/jsx/elements`, { text, name: draft.target.name })), 400);
    return () => clearTimeout(timer);
  }, [text, workId, draft.target.name]);

  async function insert() {
    try {
      const result = await post(`/api/works/${workId}/drafts/${draft.id}/apply`, {
        text,
        ...(chosen === '__new' ? { new_path: newPath } : { path: chosen, position, heading }),
      });
      toast({ text: t('jsx.inserted', { path: result.path }) });
      done();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <div className="pad col">
      <div className="row">
        <strong className="grow">{t('jsx.prompt_review_title', { name: draft.target.name })}</strong>
        {pending && (
          <>
            <DiscardButton workId={workId} draft={draft} done={done} />
            <button className="primary" disabled={!chosen} onClick={insert}>
              {t('jsx.insert')}
            </button>
          </>
        )}
      </div>
      <ModelLine draft={draft} />
      <textarea className="mono" rows={14} value={text} disabled={!pending} onChange={(e) => setText(e.target.value)} />
      <div className="col" style={{ gap: 2 }}>
        {elements.length === 0 && <div className="warn-text">{t('jsx.no_elements', { name: draft.target.name })}</div>}
        {elements.map((el, n) => (
          <div key={n} className={el.errors.length ? 'warn-text' : 'faint'}>
            {el.errors.length ? '⚠' : '✓'} {el.raw.slice(0, 80)}
            {el.errors.length > 0 && ` — ${el.errors[0]}`}
          </div>
        ))}
        <span className="faint">{t('jsx.elements_note')}</span>
      </div>
      {pending && (
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <span className="muted">{t('jsx.insert_into')}</span>
          <select value={chosen} onChange={(e) => setTarget(e.target.value)}>
            {items.map((e) => (
              <option key={e.path} value={e.path}>
                {e.path} ({t(`kind.${e.kind}`)})
              </option>
            ))}
            <option value="__new">{t('jsx.new_lorebook')}</option>
          </select>
          {chosen === '__new' ? (
            <input value={newPath} onChange={(e) => setNewPath(e.target.value)} />
          ) : (
            <>
              <select value={position} onChange={(e) => setPosition(e.target.value as 'end' | 'heading')}>
                <option value="end">{t('jsx.at_end')}</option>
                <option value="heading">{t('jsx.under_heading')}</option>
              </select>
              {position === 'heading' && (
                <select value={heading} onChange={(e) => setHeading(e.target.value)}>
                  <option value="">—</option>
                  {headings.map((h: string) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
