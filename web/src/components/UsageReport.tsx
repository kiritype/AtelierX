import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get, q } from '../api';
import { t } from '../i18n';
import type { WorkCard } from '../types';

type Row = { provider?: string; model?: string; task?: string; work?: string; requests: number; unknown: number; input_tokens: number; output_tokens: number };
type Entry = { at: string; provider: string; model: string; task: string; work?: string | null; input_tokens?: number | null; output_tokens?: number | null };
type By = 'model' | 'task' | 'work';
const PAGE = 50;

// 03-llm: monthly usage grouped by connection·model·task, task or work, and the month's requests one by one.
export default function UsageReport({ providerName }: { providerName: (id: string) => string }) {
  const [month, setMonth] = useState('');
  const [by, setBy] = useState<By>('model');
  const [detail, setDetail] = useState(false);
  const [offset, setOffset] = useState(0);
  const [work, setWork] = useState('');
  const [task, setTask] = useState('');
  const summary = useQuery<{ month: string; months: string[]; tasks: string[]; rows: Row[] }>({
    queryKey: ['usage', month, by],
    queryFn: () => get(`/api/usage?by=${by}${month ? `&month=${q(month)}` : ''}`),
  });
  const shown = month || summary.data?.month || '';
  const log = useQuery<{ total: number; rows: Entry[] }>({
    queryKey: ['usage-log', shown, offset, work, task],
    queryFn: () => get(`/api/usage/log?month=${q(shown)}&offset=${offset}&limit=${PAGE}&work=${q(work)}&task=${q(task)}`),
    enabled: detail && !!shown,
  });
  // Same query as the work list (`{works, suggest_id}`), so both share one cache entry.
  const works = useQuery<{ works: WorkCard[] }>({ queryKey: ['works'], queryFn: () => get('/api/works') });
  const workName = (id?: string | null) => (id ? works.data?.works.find((w) => w.id === id)?.name ?? id : t('usage.no_work'));
  const months = Array.from(new Set([shown, ...(summary.data?.months ?? [])].filter(Boolean)));
  const tokens = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString());
  const rows = summary.data?.rows ?? [];
  // The task filter lists the month's tasks from the server, so it does not depend on the grouping.
  const tasks = summary.data?.tasks ?? [];

  return (
    <div className="col">
      <div className="row wrap">
        <div className="section-title grow">{t('usage.title')}</div>
        <select aria-label={t('usage.month')} value={shown} onChange={(e) => { setMonth(e.target.value); setOffset(0); }}>
          {months.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <select aria-label={t('usage.group')} value={by} onChange={(e) => setBy(e.target.value as By)}>
          <option value="model">{t('usage.by_model')}</option>
          <option value="task">{t('usage.by_task')}</option>
          <option value="work">{t('usage.by_work')}</option>
        </select>
        <button onClick={() => setDetail(!detail)}>{detail ? t('usage.hide_detail') : t('usage.show_detail')}</button>
        <a className="button" href={`/api/usage.csv?month=${q(shown)}`} download>{t('usage.csv')}</a>
      </div>
      {rows.length === 0 ? (
        <div className="faint">{t('llm.no_usage')}</div>
      ) : (
        <div className="usage-table"><table className="plain">
          <thead>
            <tr className="faint">
              {by === 'model' && <><td>{t('llm.connections')}</td><td>{t('llm.model')}</td><td>{t('llm.task_col')}</td></>}
              {by === 'task' && <td>{t('llm.task_col')}</td>}
              {by === 'work' && <td>{t('usage.work')}</td>}
              <td>{t('llm.requests')}</td>
              <td>{t('llm.tokens_in_out')}</td>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, n) => (
              <tr key={n}>
                {by === 'model' && <><td>{providerName(row.provider ?? '')}</td><td className="mono">{row.model}</td><td>{t(`llm.task.${row.task}`)}</td></>}
                {by === 'task' && <td>{t(`llm.task.${row.task}`)}</td>}
                {by === 'work' && <td>{workName(row.work)}</td>}
                <td>
                  {row.requests.toLocaleString()}
                  {row.unknown > 0 && <span className="faint"> ({t('usage.unknown', { n: row.unknown })})</span>}
                </td>
                <td>{row.input_tokens.toLocaleString()} / {row.output_tokens.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      <p className="faint small">{t('usage.note')}</p>
      {detail && (
        <div className="col">
          <div className="row wrap">
            <select aria-label={t('usage.work')} value={work} onChange={(e) => { setWork(e.target.value); setOffset(0); }}>
              <option value="">{t('usage.all_works')}</option>
              {(works.data?.works ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>
            <select aria-label={t('llm.task_col')} value={task} onChange={(e) => { setTask(e.target.value); setOffset(0); }}>
              <option value="">{t('usage.all_tasks')}</option>
              {tasks.map((name) => <option key={name} value={name}>{t(`llm.task.${name}`)}</option>)}
            </select>
            <span className="grow" />
            <span className="faint">{t('usage.range', { from: log.data?.total ? offset + 1 : 0, to: Math.min(offset + PAGE, log.data?.total ?? 0), total: log.data?.total ?? 0 })}</span>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>{t('usage.newer')}</button>
            <button disabled={!log.data || offset + PAGE >= log.data.total} onClick={() => setOffset(offset + PAGE)}>{t('usage.older')}</button>
          </div>
          <div className="usage-table"><table className="plain">
            <thead>
              <tr className="faint">
                <td>{t('usage.at')}</td><td>{t('usage.work')}</td><td>{t('llm.task_col')}</td><td>{t('llm.connections')}</td><td>{t('llm.model')}</td><td>{t('llm.tokens_in_out')}</td>
              </tr>
            </thead>
            <tbody>
              {(log.data?.rows ?? []).map((e, n) => (
                <tr key={`${e.at}-${n}`}>
                  <td className="mono small">{e.at.slice(5, 16).replace('T', ' ')}</td>
                  <td>{workName(e.work)}</td>
                  <td>{t(`llm.task.${e.task}`)}</td>
                  <td>{providerName(e.provider)}</td>
                  <td className="mono small">{e.model}</td>
                  <td>{tokens(e.input_tokens)} / {tokens(e.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      )}
    </div>
  );
}
