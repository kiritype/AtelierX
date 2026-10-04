import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, post } from '../../api';
import { t } from '../../i18n';
import { useToast } from '../Toasts';

type Scope = { work?: string; character?: string; outfit?: string };

export function DeploymentExport({ scope, close, fail }: { scope: Scope; close: () => void; fail: (err: unknown) => void }) {
  const toast = useToast();
  const filters = { work: scope.work, character: scope.character, outfit: scope.outfit };
  const plan = useQuery<{ count: number; files: Record<string, string>; missing: string[]; collisions: string[] }>({
    queryKey: ['gallery-export', filters],
    queryFn: () => post('/api/image/gallery/export/plan', { filters }),
  });
  const [busy, setBusy] = useState(false);
  const [strip, setStrip] = useState(false);
  const download = async () => {
    setBusy(true);
    try {
      const response = await fetch('/api/image/gallery/export', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters, allow_partial: true, strip_metadata: strip }), credentials: 'same-origin',
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new ApiError(response.status, data?.error ?? { key: 'error.unknown', text: response.statusText });
      }
      const name = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? 'adopted.zip';
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a'); link.href = url; link.download = name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      toast({ text: t('gallery.exported', { n: plan.data?.count ?? 0 }) }); close();
    } catch (err) { fail(err); } finally { setBusy(false); }
  };
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="dialog col" style={{ width: 520 }}>
        <h3>{t('gallery.export')}</h3><p className="faint">{t('gallery.export_about')}</p>
        <label className="row" style={{ gap: 4, flexDirection: 'row' }}>
          <input type="checkbox" checked={strip} onChange={(e) => setStrip(e.target.checked)} />{t('gallery.strip_metadata')}
        </label>
        {plan.data && <>
          <div>{t('gallery.export_count', { n: plan.data.count })}</div>
          <details>
            <summary>{t('gallery.export_mapping', { n: Object.keys(plan.data.files).length })}</summary>
            <div
              className="mono small faint col"
              style={{ maxHeight: 180, overflow: 'auto', gap: 4, padding: '6px 0 6px 12px' }}
            >
              {Object.entries(plan.data.files).map(([destination, source]) => (
                <div key={`${source}\0${destination}`} style={{ overflowWrap: 'anywhere' }}>
                  {source} → {destination}
                </div>
              ))}
            </div>
          </details>
          {plan.data.missing.length > 0 && <div className="warn-text">
            {t('gallery.export_missing', { n: plan.data.missing.length })}
            <div className="mono small faint" style={{ maxHeight: 140, overflow: 'auto', whiteSpace: 'pre-line' }}>
              {plan.data.missing.join('\n')}
            </div>
          </div>}
          {plan.data.collisions.length > 0 && <div className="warn-text">{t('gallery.export_collision', { paths: plan.data.collisions.join(', ') })}</div>}
        </>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button onClick={close}>{t('common.cancel')}</button>
          <button className="primary" disabled={busy || !plan.data?.count || !!plan.data?.collisions.length} onClick={download}>{t('gallery.download_zip')}</button>
        </div>
      </div>
    </div>
  );
}
