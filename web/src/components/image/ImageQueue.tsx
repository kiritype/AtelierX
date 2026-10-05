import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';

type Job = {
  id: string;
  status: string;
  kind?: string;
  work_id: string;
  character_id: string;
  outfit_name?: string;
  outfit_id: string;
  expression_name?: string;
  expression_id: string;
  seed: number | null;
  title?: string;
  post_op?: string;
  tool_name?: string;
  progress?: any;
  error?: any;
  image_url?: string;
  created_at: string;
  finished_at?: string;
};
type Queue = { paused: boolean; jobs: Job[]; gpu: { holder: string | null; label: any; state_label: any; waiting: any } };

const msg = (value: any) => (value && typeof value === 'object' ? tm(value) : String(value ?? ''));
const ORDER: Record<string, number> = { running: 0, cancelling: 0, queued: 1, failed: 2, interrupted: 2, cancelled: 3, completed: 4 };

// Image menu → Generation queue: order, pause, retry, cancel; finished images show as thumbnails.
export default function ImageQueue() {
  const qc = useQueryClient();
  const toast = useToast();
  const queue = useQuery<Queue>({ queryKey: ['image-queue'], queryFn: () => get('/api/image/queue'), refetchInterval: 1500 });
  const [show, setShow] = useState<'all' | 'active' | 'done'>('all');
  const [big, setBig] = useState<string | null>(null);
  const data = queue.data;
  const act = async (url: string) => {
    try {
      await post(url);
      qc.invalidateQueries({ queryKey: ['image-queue'] });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  };
  if (!data) return null;
  const jobs = [...data.jobs]
    .filter((j) => show === 'all' || (show === 'active' ? ['running', 'cancelling', 'queued'].includes(j.status) : !['running', 'cancelling', 'queued'].includes(j.status)))
    .sort((a, b) => (ORDER[a.status] ?? 5) - (ORDER[b.status] ?? 5) || (a.status === 'queued' ? a.created_at.localeCompare(b.created_at) : b.created_at.localeCompare(a.created_at)));
  const counts = data.jobs.reduce<Record<string, number>>((all, j) => ({ ...all, [j.status]: (all[j.status] ?? 0) + 1 }), {});

  return (
    <div className="pad col image-queue">
      <div className="row">
        <strong>{data.paused ? t('queue.paused') : t('queue.running')}</strong>
        <span className="faint">
          {t('queue.counts', { running: (counts.running ?? 0) + (counts.cancelling ?? 0), queued: counts.queued ?? 0, done: counts.completed ?? 0, failed: (counts.failed ?? 0) + (counts.interrupted ?? 0) })}
        </span>
        <span className="grow" />
        {data.paused ? (
          <button className="primary" onClick={() => act('/api/image/queue/resume')}>
            {t('queue.resume')}
          </button>
        ) : (
          <button onClick={() => act('/api/image/queue/pause')}>{t('queue.pause')}</button>
        )}
        <button onClick={() => confirm(t('queue.cancel_queued_confirm')) && act('/api/image/queue/cancel-queued')}>{t('queue.cancel_queued')}</button>
        <button onClick={() => act('/api/image/queue/clear-finished')}>{t('queue.clear_finished')}</button>
      </div>
      <div className="faint">
        GPU: {msg(data.gpu.label)}
        {data.gpu.state_label ? ` · ${msg(data.gpu.state_label)}` : ''}
        {data.gpu.waiting ? ` · ${msg(data.gpu.waiting.reason)}` : ''}
      </div>
      <div className="seg" style={{ alignSelf: 'flex-start' }}>
        {(['all', 'active', 'done'] as const).map((s) => (
          <button key={s} className={show === s ? 'on' : ''} onClick={() => setShow(s)}>
            {t(`queue.show.${s}`)}
          </button>
        ))}
      </div>
      {jobs.length === 0 && <div className="empty">{t('queue.empty')}</div>}
      <div className="queue-list">
        {jobs.map((job) => (
          <div key={job.id} className={`queue-row status-${job.status}`}>
            {job.image_url ? (
              <img src={job.image_url} alt="" onClick={() => setBig(job.image_url!)} />
            ) : (
              <div className="queue-thumb">{t(`queue.status.${job.status}`)}</div>
            )}
            <div className="col grow" style={{ gap: 2 }}>
              <div>
                {job.kind === 'post' ? (
                  // Post-processing works on a tool-workspace image, not on a character combination.
                  <>
                    <strong>{t(`queue.post_op.${job.post_op}`)}</strong> · {job.tool_name ?? job.title?.split(' · ').pop()}
                  </>
                ) : (
                  <>
                    <strong>{job.character_id}</strong> · {job.outfit_name ?? job.outfit_id} · {job.expression_name ?? job.expression_id}
                  </>
                )}
                {job.kind && job.kind !== 'image' && <span className="chip">{t(`queue.kind.${job.kind}`) === `queue.kind.${job.kind}` ? job.kind : t(`queue.kind.${job.kind}`)}</span>}
              </div>
              <div className="faint">
                {t(`queue.status.${job.status}`)}
                {job.progress && ['running', 'cancelling'].includes(job.status) ? ` · ${msg(job.progress)}` : ''}
                {job.seed != null ? ` · seed ${job.seed}` : ''}
              </div>
              {job.error && <div className="error-text">{msg(job.error)}</div>}
            </div>
            <div className="row">
              {['queued', 'running'].includes(job.status) && <button onClick={() => act(`/api/image/jobs/${job.id}/cancel`)}>{t('common.cancel')}</button>}
              {['failed', 'cancelled', 'interrupted'].includes(job.status) && <button onClick={() => act(`/api/image/jobs/${job.id}/retry`)}>{t('queue.retry')}</button>}
              {['completed', 'failed', 'cancelled', 'interrupted'].includes(job.status) && (
                <button className="ghost" onClick={() => act(`/api/image/jobs/${job.id}/remove`)}>
                  ×
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {big && (
        <div className="overlay" onMouseDown={() => setBig(null)}>
          <img src={big} alt="" style={{ maxWidth: '92vw', maxHeight: '92vh', borderRadius: 6 }} />
        </div>
      )}
    </div>
  );
}
