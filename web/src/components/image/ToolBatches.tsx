import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { get, post } from '../../api';
import { msgText, t } from '../../i18n';
import type { ToolBatch } from '../../lib/toolBatches';

const STATES = ['pending', 'queued', 'running', 'cancelling', 'done', 'failed', 'cancelled', 'interrupted'] as const;
type Detail = { ordinal: number; status: string; target: { id: string }; result?: { error?: unknown; image_url?: string } };

export default function ToolBatches({ active, fail }: { active: boolean; fail: (error: unknown) => void }) {
  const qc = useQueryClient();
  const batches = useQuery<{ batches: ToolBatch[] }>({ queryKey: ['tool-batches'], queryFn: () => get('/api/image/tools/batches'), refetchInterval: active ? 1500 : false, enabled: active });
  const [selected, setSelected] = useState('');
  const [offset, setOffset] = useState(0);
  const container = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const focus = (event: Event) => {
      setSelected((event as CustomEvent<string>).detail);
      setOffset(0);
      if (container.current) {
        container.current.open = true;
        container.current.scrollIntoView({ block: 'nearest' });
      }
    };
    window.addEventListener('tool-batch-focus', focus);
    return () => window.removeEventListener('tool-batch-focus', focus);
  }, []);
  const details = useQuery<{ items: Detail[] }>({ queryKey: ['tool-batch', selected, offset], queryFn: () => get(`/api/image/tools/batches/${selected}?offset=${offset}&limit=50`), enabled: !!selected && active, refetchInterval: active ? 2000 : false });
  async function action(id: string, name: 'cancel' | 'retry') {
    try {
      await post(`/api/image/tools/batches/${id}/${name}`, {});
      await qc.invalidateQueries({ queryKey: ['tool-batches'] });
      await qc.invalidateQueries({ queryKey: ['tool-batch'] });
    } catch (error) { fail(error); }
  }
  if (!batches.data?.batches?.length) return null;
  const current = batches.data.batches.find((batch) => batch.id === selected);
  return <details ref={container} className="pad col" open>
    <summary>{t('bulk.title')}</summary>
    <p className="faint small">{t('bulk.about')}</p>
    {batches.data.batches.map((batch) => <div key={batch.id} className="col" style={{ gap: 4 }}>
      <div className="row">
        <button onClick={() => { setSelected(batch.id); setOffset(0); }}>{t(`bulk.op.${batch.operation}`)} · {batch.id.slice(0, 8)}</button>
        <span>{t('bulk.total', { n: batch.total })}</span>
        {batch.paused && <span className="warn-text">{t('bulk.paused')}</span>}
        <button disabled={batch.progress === 1 || batch.cancelled} onClick={() => action(batch.id, 'cancel')}>{t('common.cancel')}</button>
        <button disabled={!(batch.counts.failed + batch.counts.cancelled + batch.counts.interrupted)} onClick={() => action(batch.id, 'retry')}>{t('bulk.retry')}</button>
      </div>
      <progress max={1} value={batch.progress} aria-label={t('bulk.progress')} />
      <div className="row small" style={{ flexWrap: 'wrap' }}>{STATES.map((state) => <span key={state}>{t(`bulk.state.${state}`)} {batch.counts[state]}</span>)}</div>
    </div>)}
    {current && <div className="col small">
      <div className="row">
        <button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('bulk.previous')}</button>
        <span>{offset + 1}–{Math.min(offset + 50, current.total)} / {current.total}</span>
        <button disabled={offset + 50 >= current.total} onClick={() => setOffset(offset + 50)}>{t('bulk.next')}</button>
      </div>
      {(details.data?.items ?? []).map((item) => <div key={item.ordinal}>{item.target.id} · {t(`bulk.state.${item.status}`)} {item.result?.error ? msgText(item.result.error) : ''}</div>)}
    </div>}
  </details>;
}
