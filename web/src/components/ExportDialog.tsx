import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { Dialog } from './ui';

export default function ExportDialog({ workId, onClose }: { workId: string; onClose: () => void }) {
  const toast = useToast();
  const [target, setTarget] = useState('');
  const [checkedTarget, setCheckedTarget] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setCheckedTarget(target.trim()), 500);
    return () => clearTimeout(timer);
  }, [target]);
  const preview = useQuery({
    queryKey: ['export-preview', workId, checkedTarget],
    queryFn: () => get(`/api/works/${workId}/export/preview${checkedTarget ? `?target=${encodeURIComponent(checkedTarget)}` : ''}`),
  });
  const state = preview.data?.target;
  const checks = useQuery({ queryKey: ['check', workId], queryFn: () => get(`/api/works/${workId}/check`) });
  const [snapshot, setSnapshot] = useState(true);
  const [release, setRelease] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [error, setError] = useState('');
  const errors = (checks.data ?? []).filter((i: any) => i.level === 'error');

  return (
    <Dialog
      title={t('export.title')}
      onClose={onClose}
      actions={
        <button
          className="primary"
          disabled={!target.trim() || !!preview.data?.clash || !!preview.data?.blocked}
          onClick={async () => {
            try {
              await post(`/api/works/${workId}/export`, { target: target.trim(), overwrite, snapshot, release: release || null });
              toast({ text: t('export.started') });
              onClose();
            } catch (err) {
              setError(err instanceof ApiError ? tm(err.msg) : String(err));
            }
          }}
        >
          {t('export.run')}
        </button>
      }
    >
      <label>
        {t('export.target')}
        <input autoFocus value={target} placeholder="C:\\…\\export" onChange={(e) => setTarget(e.target.value)} />
        <span className="faint">{t('export.target_note')}</span>
      </label>
      <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: 6 }}>
        {(preview.data?.include ?? []).map((p: string) => (
          <div key={p}>✓ {p}</div>
        ))}
        <div>✓ {preview.data?.keywords_file}</div>
        {(preview.data?.skip ?? []).map((s: any) => (
          <div key={s.path} className="faint">
            − {s.path} ({t(`export.skip.${s.reason}`)})
          </div>
        ))}
      </div>
      {preview.data?.blocked && <div className="error-text">{tm(preview.data.blocked)}</div>}
      {preview.data?.clash && <div className="error-text">{t('export.name_clash', { path: preview.data.clash })}</div>}
      {!preview.data?.blocked && state?.exists && state.files > 0 && (
        <div className="warn-text">
          {t('export.not_empty', { n: state.files })}
          {state.leftovers.length > 0 && (
            <>
              {' '}
              {t('export.leftovers', { n: state.leftovers.length })}
              <div className="mono faint" style={{ maxHeight: 100, overflow: 'auto' }}>
                {state.leftovers.map((f: string) => (
                  <div key={f}>{f}</div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
      {errors.length > 0 && <div className="error-text">{t('export.has_errors', { n: errors.length })}</div>}
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> {t('export.overwrite')}
      </label>
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="checkbox" checked={snapshot} onChange={(e) => setSnapshot(e.target.checked)} /> {t('export.snapshot')}
      </label>
      {snapshot && <input placeholder={t('export.release_hint')} value={release} onChange={(e) => setRelease(e.target.value)} />}
      {error && <div className="error-text">{error}</div>}
    </Dialog>
  );
}
