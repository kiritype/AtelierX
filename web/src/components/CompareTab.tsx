import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { get, post } from '../api';
import { t } from '../i18n';
import { useToast } from './Toasts';
import { diffLines } from '../lib/diff';
import { snapshotTime } from '../types';

export default function CompareTab({ workId, snapshot }: { workId: string; snapshot: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [against, setAgainst] = useState('current');
  const [path, setPath] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(true);
  const snaps = useQuery({ queryKey: ['snapshots', workId], queryFn: () => get(`/api/works/${workId}/snapshots`) });
  const info = (snaps.data ?? []).find((s: any) => s.id === snapshot);
  const changes = useQuery({
    queryKey: ['diff', workId, snapshot, against],
    queryFn: () => get(`/api/works/${workId}/snapshots/${snapshot}/diff?against=${against}`),
  });
  const file = useQuery({
    queryKey: ['snapfile', workId, snapshot, path],
    queryFn: () => get(`/api/works/${workId}/snapshots/${snapshot}/file?path=${encodeURIComponent(path!)}`),
    enabled: !!path,
  });

  async function restore(paths?: string[]) {
    if (!confirm(paths ? t('history.restore_file_confirm') : t('history.restore_all_confirm'))) return;
    const changed = await post<string[]>(`/api/works/${workId}/snapshots/${snapshot}/restore`, { paths });
    for (const key of ['tree', 'snapshots', 'check', 'item', 'diff', 'snapfile']) qc.invalidateQueries({ queryKey: [key, workId] });
    toast({ text: changed.length ? t('history.restored_n', { n: changed.length }) : t('history.nothing_to_restore') });
  }

  const lines =
    file.data && showDiff
      ? against === 'current'
        ? diffLines((file.data.snapshot ?? '').split('\n'), (file.data.current ?? '').split('\n'))
        : null
      : null;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', height: '100%' }}>
      <div style={{ borderRight: '1px solid var(--border)', overflow: 'auto' }}>
        <div className="pad col" style={{ gap: 6 }}>
          <strong title={snapshot}>
            {snapshotTime(snapshot)}
            {info && ` · ${t(`reason.${info.reason}`)}`}
          </strong>
          {info?.label && <div className="muted">{info.label}</div>}
          <select value={against} onChange={(e) => setAgainst(e.target.value)}>
            <option value="current">{t('history.vs_current')}</option>
            <option value="parent">{t('history.vs_parent')}</option>
          </select>
          <button onClick={() => restore()}>{t('history.restore_all')}</button>
        </div>
        {(changes.data ?? []).length === 0 && <div className="empty">{t('history.no_changes')}</div>}
        {(changes.data ?? []).map((c: any) => (
          <div key={c.path} className={`tree-row${c.path === path ? ' sel' : ''}`} onClick={() => setPath(c.path)}>
            <span style={{ width: 14 }}>{{ added: '+', deleted: '−', modified: '~' }[c.change as string]}</span>
            <span className="grow">{c.path}</span>
          </div>
        ))}
      </div>
      <div style={{ overflow: 'auto' }}>
        {path && (
          <div className="row pad" style={{ borderBottom: '1px solid var(--border)' }}>
            <strong className="grow">{path}</strong>
            {against === 'current' && (
              <label className="row faint">
                <input type="checkbox" checked={showDiff} onChange={(e) => setShowDiff(e.target.checked)} /> {t('history.show_diff')}
              </label>
            )}
            <button onClick={() => restore([path])}>{t('history.restore_file')}</button>
          </div>
        )}
        <pre className="mono" style={{ margin: 0, padding: 12, whiteSpace: 'pre-wrap' }}>
          {lines
            ? lines.map((l, i) => (
                <div key={i} style={{ background: l.op === '-' ? 'var(--danger-bg)' : l.op === '+' ? 'var(--success-bg)' : undefined }}>
                  {l.op} {l.text}
                </div>
              ))
            : file.data?.snapshot}
        </pre>
      </div>
    </div>
  );
}
