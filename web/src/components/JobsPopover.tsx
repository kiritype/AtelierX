import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { get, post } from '../api';
import { t } from '../i18n';
import { cancellable } from '../lib/lifecycle';
import type { ImageView, Job } from '../types';

// Image work, installs and LoRA training, in the shared life cycle (#89): shown with the LLM jobs, opened where they run.
export type Activity = {
  kind: 'image_queue' | 'install' | 'lora' | 'convert';
  status: string;
  phase?: string | null;
  counts?: Record<string, number>;
  paused?: boolean;
  section?: string;
  title?: string;
  character_id?: string;
  done?: number;
  total?: number;
};

export const useActivity = (refetch: number) =>
  useQuery<{ items: Activity[] }>({ queryKey: ['activity'], queryFn: () => get('/api/activity'), refetchInterval: refetch });

const VIEWS: Record<Activity['kind'], ImageView | 'settings'> = { image_queue: 'queue', install: 'settings', lora: 'lora', convert: 'tools' };

function detail(item: Activity) {
  if (item.kind === 'image_queue') {
    const c = item.counts ?? {};
    return t('activity.queue_counts', { running: (c.running ?? 0) + (c.cancelling ?? 0), queued: c.queued ?? 0 }) + (item.paused ? ` · ${t('activity.paused')}` : '');
  }
  if (item.kind === 'install') return t(`install.section.${item.section}`) === `install.section.${item.section}` ? item.section : t(`install.section.${item.section}`);
  if (item.kind === 'lora') return `${item.title}${item.phase ? ` · ${t(`lora.status.${item.phase}`)}` : ''}`;
  return `${item.done}/${item.total}`;
}

export default function JobsPopover({
  jobs,
  onClose,
  openDraft,
  openView,
}: {
  jobs: Job[];
  onClose: () => void;
  openDraft: (d: string) => void;
  openView: (view: ImageView | 'settings', characterId?: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const activity = useActivity(2000);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    setTimeout(() => window.addEventListener('mousedown', close));
    return () => window.removeEventListener('mousedown', close);
  }, [onClose]);
  const others = activity.data?.items ?? [];
  return (
    <div className="popover" ref={ref}>
      <div className="side-head">{t('jobs.title')}</div>
      {jobs.length === 0 && others.length === 0 && <div className="empty">{t('jobs.empty')}</div>}
      {others.map((item, n) => (
        <div key={`${item.kind}-${n}`} className="list-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div className="row">
            <span className="grow">
              {t(`activity.kind.${item.kind}`)} <span className="faint small">{detail(item)}</span>
            </span>
            <span className="faint">{t(`jobs.status.${item.status}`)}</span>
            <button className="ghost" onClick={() => (openView(VIEWS[item.kind], item.character_id), onClose())}>
              {t('activity.open')}
            </button>
          </div>
        </div>
      ))}
      {jobs.map((job) => (
        <div key={job.id} className="list-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div className="row">
            <span className="grow">{job.title}</span>
            <span className="faint">{t(`jobs.status.${job.status}`)}</span>
            {cancellable(job.status) && (
              <button className="ghost" onClick={() => post(`/api/jobs/${job.id}/cancel`)}>
                {t('common.cancel')}
              </button>
            )}
            {job.status === 'done' && job.result?.draft && <button onClick={() => openDraft(job.result.draft)}>{t('review.open')}</button>}
          </div>
          {job.status === 'running' && (
            <div className="progress">
              <div style={{ width: `${job.progress}%` }} />
            </div>
          )}
          {job.error && <div className="error-text">{job.error.text}</div>}
        </div>
      ))}
    </div>
  );
}
