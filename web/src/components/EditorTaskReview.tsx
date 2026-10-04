import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';

export default function EditorTaskReview({ workId, draft, onDone }: { workId: string; draft: any; onDone: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const candidate = draft.candidates?.[0] ?? {};
  const edit = draft.kind === 'text_edit';
  const finish = async (apply: boolean) => {
    setBusy(true);
    try {
      await post(apply ? `/api/works/${workId}/editor-drafts/${draft.id}/apply` : `/api/works/${workId}/drafts/${draft.id}/discard`, {});
      for (const key of ['drafts', 'drafts-all', 'item', 'tree', 'check', 'snapshots']) await qc.invalidateQueries({ queryKey: [key, workId] });
      onDone();
    } catch (err) { toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' }); }
    finally { setBusy(false); }
  };
  return <div className="pad col">
    <div className="row"><strong className="grow">{t(edit ? 'llm_tools.format' : 'llm_tools.content_review')} · {draft.target.path ?? draft.target.paths?.join(', ')}</strong>
      {draft.status === 'pending' && <><button disabled={busy} onClick={() => finish(false)}>{t('review.discard')}</button>{edit && <button className="primary" disabled={busy} onClick={() => finish(true)}>{t('llm_tools.apply')}</button>}</>}
    </div>
    <p className="faint">{draft.model?.provider === 'mock' ? t('review.mock_generic') : t('review.model', { name: draft.model?.name })}</p>
    {edit ? <>
      <p>{candidate.note}</p>
      <div className="editor-proposal"><section><strong>{t('llm_tools.original')}</strong><pre>{draft.request.original}</pre></section><section><strong>{t('llm_tools.proposed')}</strong><pre>{candidate.text}</pre></section></div>
    </> : <>
      {!candidate.issues?.length && <p>{t('llm_tools.no_issues')}</p>}
      {(candidate.issues ?? []).map((issue: any, index: number) => <article className="compose-card" key={index}><strong>{issue.reason}</strong><div className="faint">{issue.path}</div><blockquote style={{ whiteSpace: 'pre-wrap' }}>{issue.evidence}</blockquote></article>)}
    </>}
  </div>;
}
