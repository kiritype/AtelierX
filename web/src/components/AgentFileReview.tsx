import { useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { compose, diffLines, hunks } from '../lib/diff';
import { useToast } from './Toasts';

// Review of an agent's whole-file proposal (11-agent): the change is shown hunk by hunk, each adopted or left out;
// adopting writes the original with the chosen hunks.

const CONTEXT = 2;

export default function AgentFileReview({ workId, draft, onDone, openItem }: { workId: string; draft: any; onDone: () => void; openItem: (path: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const target = draft.target as { path: string; new?: boolean };
  const proposed: string = draft.candidates?.[0]?.text ?? '';
  const original: string = draft.request?.original ?? '';
  const warnings: string[] = draft.request?.warnings ?? [];
  const pending = draft.status === 'pending';
  const ops = useMemo(() => diffLines(original.split('\n'), proposed.split('\n')), [original, proposed]);
  const list = useMemo(() => hunks(ops), [ops]);
  const [adopted, setAdopted] = useState<Set<number>>(() => new Set(list.map((h) => h.id)));
  const [busy, setBusy] = useState(false);

  async function finish(apply: boolean) {
    setBusy(true);
    try {
      if (apply) {
        const text = target.new ? proposed : compose(ops, list, adopted);
        const saved = await post<{ path: string }>(`/api/works/${workId}/agent-drafts/${draft.id}/apply`, { text });
        toast({ text: t('agent.applied', { path: saved.path }), action: { label: t('agent.open_file'), run: () => openItem(saved.path) } });
      } else {
        await post(`/api/works/${workId}/drafts/${draft.id}/discard`, {});
      }
      for (const key of ['drafts', 'drafts-all', 'item', 'tree', 'check', 'snapshots', 'agent-session']) qc.invalidateQueries({ queryKey: [key, workId] });
      onDone();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  const toggle = (id: number) => {
    const next = new Set(adopted);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setAdopted(next);
  };

  // Lines to show: every change, and a little unchanged text around each.
  const near = new Set<number>();
  for (const h of list) for (let k = Math.max(0, h.from - CONTEXT); k < Math.min(ops.length, h.to + CONTEXT); k++) near.add(k);
  const rows: React.ReactNode[] = [];
  let k = 0;
  while (k < ops.length) {
    const hunk = list.find((h) => h.from === k);
    if (hunk) {
      const on = adopted.has(hunk.id);
      rows.push(
        <div key={`h${hunk.id}`} className={`review-hunk${on ? ' on' : ''}`}>
          <label className="row review-hunk-head" style={{ flexDirection: 'row' }}>
            <input type="checkbox" checked={on} disabled={!pending} onChange={() => toggle(hunk.id)} />
            <span className="small">{t('agent.hunk', { n: hunk.id + 1 })}</span>
          </label>
          {ops.slice(hunk.from, hunk.to).map((op, n) => (
            <div key={n} className={`diff-line ${op.op === '+' ? 'add' : 'del'}`}>
              <span className="diff-mark">{op.op}</span>
              {op.text || ' '}
            </div>
          ))}
        </div>,
      );
      k = hunk.to;
      continue;
    }
    if (near.has(k)) {
      rows.push(
        <div key={k} className="diff-line same">
          <span className="diff-mark"> </span>
          {ops[k].text || ' '}
        </div>,
      );
      k++;
      continue;
    }
    let skip = k;
    while (skip < ops.length && !near.has(skip) && !list.some((h) => h.from === skip)) skip++;
    rows.push(
      <div key={`s${k}`} className="diff-skip faint small">
        {t('agent.same_lines', { n: skip - k })}
      </div>,
    );
    k = skip;
  }

  return (
    <div className="pad col agent-review">
      <div className="row">
        <strong className="grow">
          {t('draft.kind.agent_file')} · {target.path}
        </strong>
        {target.new && <span className="badge">{t('agent.new_file')}</span>}
      </div>
      <p className="faint small">{draft.model?.provider === 'mock' ? t('review.mock_generic') : t('review.model', { name: draft.model?.name ?? '' })}</p>
      {warnings.map((w) => (
        <div key={w} className="warn-text">
          {t(`agent.warning.${w}`)}
        </div>
      ))}
      {!pending && <div className="faint">{t(`agent.status.${draft.status}`)}</div>}
      {target.new ? (
        <pre className="proposal-text">{proposed}</pre>
      ) : list.length === 0 ? (
        <div className="empty">{t('agent.no_change')}</div>
      ) : (
        <>
          <div className="row">
            <span className="faint small grow">{t('agent.hunks', { adopted: adopted.size, total: list.length })}</span>
            {pending && (
              <>
                <button className="ghost small" onClick={() => setAdopted(new Set(list.map((h) => h.id)))}>
                  {t('agent.adopt_all')}
                </button>
                <button className="ghost small" onClick={() => setAdopted(new Set())}>
                  {t('agent.adopt_none')}
                </button>
              </>
            )}
          </div>
          <div className="diff-view">{rows}</div>
        </>
      )}
      {pending && (
        <div className="row">
          <span className="grow" />
          <button disabled={busy} onClick={() => finish(false)}>
            {t('review.discard')}
          </button>
          <button className="primary" disabled={busy || (!target.new && adopted.size === 0)} onClick={() => finish(true)}>
            {target.new ? t('agent.create_file') : t('agent.adopt')}
          </button>
        </div>
      )}
    </div>
  );
}
