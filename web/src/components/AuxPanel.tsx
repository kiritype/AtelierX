import { useQuery } from '@tanstack/react-query';
import { get } from '../api';
import { t, tm } from '../i18n';
import type { Issue } from '../types';

type AuxTab = 'check' | 'review';

export default function AuxPanel({
  tab,
  setTab,
  workId,
  activePath,
  openItem,
  openDraft,
  pendingDrafts,
}: {
  tab: AuxTab;
  setTab: (tab: AuxTab | null) => void;
  workId: string;
  activePath: string | null;
  openItem: (path: string) => void;
  openDraft: (draft: string) => void;
  pendingDrafts: number;
}) {
  return (
    <>
      <div className="aux-tabs">
        {(['check', 'review'] as AuxTab[]).map((key) => (
          <button key={key} className={tab === key ? 'on' : ''} onClick={() => setTab(key)}>
            {t(`aux.${key}`)}
            {key === 'review' && pendingDrafts > 0 && <span className="badge" style={{ marginLeft: 4 }}>{pendingDrafts}</span>}
          </button>
        ))}
        <span className="grow" />
        <button onClick={() => setTab(null)}>×</button>
      </div>
      <div className="aux-body">
        {tab === 'check' && <Checks workId={workId} activePath={activePath} openItem={openItem} />}
        {tab === 'review' && <ReviewQueue workId={workId} openDraft={openDraft} />}
      </div>
    </>
  );
}

function Checks({ workId, activePath, openItem }: { workId: string; activePath: string | null; openItem: (p: string) => void }) {
  const issues = useQuery<Issue[]>({ queryKey: ['check', workId], queryFn: () => get(`/api/works/${workId}/check`) });
  const list = issues.data ?? [];
  const mine = list.filter((i) => i.path === activePath);
  const rest = list.filter((i) => i.path !== activePath);
  const icon = { error: '⛔', warning: '⚠', info: 'ⓘ' };
  const row = (issue: Issue, n: number) => (
    <div
      key={n}
      className={`list-row issue ${issue.level}`}
      style={{ cursor: issue.path ? 'pointer' : 'default', alignItems: 'flex-start' }}
      onClick={() => issue.path && openItem(issue.path)}
    >
      <span>{icon[issue.level]}</span>
      <span className="grow">
        {tm(issue.message)}
        {issue.path && <div className="faint">{issue.path}</div>}
      </span>
    </div>
  );
  if (issues.data && list.length === 0) return <div className="empty">✓ {t('check.none')}</div>;
  return (
    <>
      {activePath && (
        <>
          <div className="section-title">{t('check.this_file')}</div>
          {mine.length ? mine.map(row) : <div className="faint">✓ {t('check.none')}</div>}
        </>
      )}
      <div className="section-title">{t('check.work')}</div>
      {rest.map(row)}
    </>
  );
}

function ReviewQueue({ workId, openDraft }: { workId: string; openDraft: (d: string) => void }) {
  const drafts = useQuery({ queryKey: ['drafts', workId], queryFn: () => get(`/api/works/${workId}/drafts?status=pending`) });
  if ((drafts.data ?? []).length === 0) return <div className="empty">{t('drafts.empty')}</div>;
  return (
    <>
      {(drafts.data ?? []).map((d: any) => (
        <div key={d.id} className="list-row" style={{ cursor: 'pointer' }} onClick={() => openDraft(d.id)}>
          <span className="grow">
            {t(`draft.kind.${d.kind}`)}
            {d.target.path ? ` · ${d.target.path.split('/').pop()}` : ''}
          </span>
          <button>{t('review.open')}</button>
        </div>
      ))}
    </>
  );
}
