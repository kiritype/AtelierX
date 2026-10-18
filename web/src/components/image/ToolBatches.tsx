import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { get, post } from '../../api';
import { getLanguage, msgText, t } from '../../i18n';
import type { ToolBatch } from '../../lib/toolBatches';

const STATES = ['pending', 'queued', 'running', 'cancelling', 'done', 'failed', 'cancelled', 'interrupted'] as const;
const OPEN_KEY = 'atelierx.tools.batches.open';
const HISTORY_OPEN_KEY = 'atelierx.tools.batches.history.open';
type Detail = { ordinal: number; status: string; target: { id: string }; display_name?: string; thumbnail_url?: string | null; result?: { error?: unknown; image_url?: string } };
type BatchList = { batches: ToolBatch[]; running_count: number; failed_count: number; more_working: boolean; more_completed: boolean };

const finished = (batch: ToolBatch) => batch.total > 0 && batch.counts.done === batch.total;
const shownTime = (value: string) => {
  const date = new Date(value);
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleString(getLanguage()) : value;
};

export default function ToolBatches({ active, fail }: { active: boolean; fail: (error: unknown) => void }) {
  const qc = useQueryClient();
  const batches = useQuery<BatchList>({ queryKey: ['tool-batches'], queryFn: () => get('/api/image/tools/batches'), refetchInterval: active ? 1500 : false, enabled: active });
  const [selected, setSelected] = useState('');
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState(() => { try { return localStorage.getItem(OPEN_KEY) === 'true'; } catch { return false; } });
  const [historyOpen, setHistoryOpen] = useState(() => { try { return localStorage.getItem(HISTORY_OPEN_KEY) === 'true'; } catch { return false; } });
  const [clearing, setClearing] = useState(false);
  const details = useQuery<{ items: Detail[] }>({ queryKey: ['tool-batch', selected, offset], queryFn: () => get(`/api/image/tools/batches/${selected}?offset=${offset}&limit=50`), enabled: !!selected && active, refetchInterval: active ? 2000 : false });
  const all = batches.data?.batches ?? [];
  const working = all.filter((batch) => !finished(batch));
  const completed = all.filter(finished);
  const runningCount = batches.data?.running_count ?? working.reduce((n, batch) => n + batch.counts.pending + batch.counts.queued + batch.counts.running + batch.counts.cancelling, 0);
  const failedCount = batches.data?.failed_count ?? working.reduce((n, batch) => n + batch.counts.failed + batch.counts.cancelled + batch.counts.interrupted, 0);
  async function action(id: string, name: 'cancel' | 'retry') {
    try {
      await post(`/api/image/tools/batches/${id}/${name}`, {});
      await qc.invalidateQueries({ queryKey: ['tool-batches'] });
      await qc.invalidateQueries({ queryKey: ['tool-batch'] });
    } catch (error) { fail(error); }
  }
  async function clearCompleted() {
    if (!confirm(t('bulk.clear_confirm'))) return;
    setClearing(true);
    try {
      await post('/api/image/tools/batches/clear-completed', {});
      setSelected('');
      await qc.invalidateQueries({ queryKey: ['tool-batches'] });
    } catch (error) { fail(error); }
    finally { setClearing(false); }
  }
  function renderBatch(batch: ToolBatch) {
    return <div key={batch.id} className="col" style={{ gap: 4, minWidth: 0 }}>
      <div className="row" style={{ flexWrap: 'wrap', minWidth: 0 }}>
        <button title={batch.id} style={{ maxWidth: '100%', minWidth: 0, whiteSpace: 'normal', overflowWrap: 'anywhere', textAlign: 'left' }} onClick={() => { setSelected(batch.id); setOffset(0); }}>{t(`bulk.op.${batch.operation}`)} · {shownTime(batch.created_at) || batch.id.slice(0, 8)} · {t('bulk.total', { n: batch.total })}</button>
        {batch.paused && !finished(batch) && <span className="warn-text">{t('bulk.paused')}</span>}
        {!finished(batch) && <button disabled={batch.progress === 1 || batch.cancelled} onClick={() => action(batch.id, 'cancel')}>{t('common.cancel')}</button>}
        {!finished(batch) && <button disabled={!(batch.counts.failed + batch.counts.cancelled + batch.counts.interrupted)} onClick={() => action(batch.id, 'retry')}>{t('bulk.retry')}</button>}
      </div>
      <progress max={1} value={batch.progress} aria-label={t('bulk.progress')} style={{ width: '100%', maxWidth: '100%', minWidth: 0 }} />
      <div className="row small" style={{ flexWrap: 'wrap' }}>{STATES.filter((state) => batch.counts[state]).map((state) => <span key={state}>{t(`bulk.state.${state}`)} {batch.counts[state]}</span>)}</div>
      {selected === batch.id && <div className="col small">
        <div className="row">
          <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('bulk.previous')}</button>
          <span>{offset + 1}–{Math.min(offset + 50, batch.total)} / {batch.total}</span>
          <button disabled={offset + 50 >= batch.total} onClick={() => setOffset(offset + 50)}>{t('bulk.next')}</button>
        </div>
        {(details.data?.items ?? []).map((item) => {
          const filename = item.display_name?.trim() || item.target.id;
          return <div key={item.ordinal} className="row" style={{ minWidth: 0 }}>
            {item.thumbnail_url && <img src={item.thumbnail_url} alt="" style={{ width: 32, height: 32, objectFit: 'cover' }} />}
            <span title={item.target.id} style={{ overflowWrap: 'anywhere' }}>{filename}</span>
            <span className="faint mono small">{filename !== item.target.id ? item.target.id : ''}</span>
            <span>· {t(`bulk.state.${item.status}`)} {item.result?.error ? msgText(item.result.error) : ''}</span>
          </div>;
        })}
      </div>}
    </div>;
  }

  return <div className="col" style={{ gap: 0 }}>
    <details className="pad col" open={open} onToggle={(event) => {
      setOpen(event.currentTarget.open);
      try { localStorage.setItem(OPEN_KEY, String(event.currentTarget.open)); } catch { /* UI preference only */ }
    }}>
      <summary aria-expanded={open}>{t('bulk.title')} · {t('bulk.running_count', { n: runningCount })} · {t('bulk.failed_count', { n: failedCount })}</summary>
      <p className="faint small">{t('bulk.about')}</p>
      {working.length ? working.map(renderBatch) : <span className="faint small">{t('bulk.no_active')}</span>}
      {batches.data?.more_working && <span className="faint small">{t('bulk.latest_100')}</span>}
    </details>
    {completed.length > 0 && <details className="pad col" open={historyOpen} onToggle={(event) => {
      setHistoryOpen(event.currentTarget.open);
      try { localStorage.setItem(HISTORY_OPEN_KEY, String(event.currentTarget.open)); } catch { /* UI preference only */ }
    }}>
      <summary aria-expanded={historyOpen}>{t('bulk.completed_history', { n: completed.length })}</summary>
      <p className="faint small">{t('bulk.clear_about')}</p>
      <button disabled={clearing} onClick={clearCompleted}>{t('bulk.clear_completed')}</button>
      {completed.map(renderBatch)}
      {batches.data?.more_completed && <span className="faint small">{t('bulk.latest_100')}</span>}
    </details>}
  </div>;
}
