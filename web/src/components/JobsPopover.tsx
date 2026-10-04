import { useEffect, useRef } from 'react';
import { post } from '../api';
import { t } from '../i18n';
import type { Job } from '../types';

export default function JobsPopover({ jobs, onClose, openDraft }: { jobs: Job[]; onClose: () => void; openDraft: (d: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose();
    setTimeout(() => window.addEventListener('mousedown', close));
    return () => window.removeEventListener('mousedown', close);
  }, [onClose]);
  return (
    <div className="popover" ref={ref}>
      <div className="side-head">{t('jobs.title')}</div>
      {jobs.length === 0 && <div className="empty">{t('jobs.empty')}</div>}
      {jobs.map((job) => (
        <div key={job.id} className="list-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
          <div className="row">
            <span className="grow">{job.title}</span>
            <span className="faint">{t(`jobs.status.${job.status}`)}</span>
            {(job.status === 'queued' || job.status === 'running') && (
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
