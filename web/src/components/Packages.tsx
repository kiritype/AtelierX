import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';
import { Dialog, formatBytes } from './ui';

// Work and settings packages (#46, #47): one ZIP to move works or settings to another PC, or to keep as a backup.
// Not the platform export (작품 → 내보내기), which writes the chatbot's files for a platform.

type WorkPlan = { works: { id: string; name: string; files: number; bytes: number; images: number; loras: number }[]; files: number; bytes: number };
type Inspected = {
  token: string;
  kind: 'works' | 'settings';
  app_version?: string;
  created_at?: string;
  works?: { index: number; id: string; name: string; files: number; bytes: number; images: number; loras: number; id_taken: boolean; name_taken: boolean }[];
  areas?: { area: string; exists: boolean }[];
};

export const SETTING_AREAS = ['settings', 'platforms', 'guidelines', 'providers', 'personas', 'image_library', 'image_presets', 'image_review', 'image_tags'] as const;

async function apiError(response: Response) {
  const data = await response.json().catch(() => null);
  return new ApiError(response.status, data?.error ?? { key: 'error.unknown', text: response.statusText });
}

// POST, then save the ZIP the server answers with under the name it gives.
async function downloadPost(url: string, body: unknown, fallback: string) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'same-origin',
  });
  if (!response.ok) throw await apiError(response);
  const name = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? fallback;
  const href = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = href;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 10000);
}

export function PackageExportDialog({ ids, onClose }: { ids: string[]; onClose: () => void }) {
  const toast = useToast();
  const [images, setImages] = useState<'adopted' | 'all' | 'none'>('adopted');
  const [history, setHistory] = useState(false);
  const [lora, setLora] = useState(false);
  const [busy, setBusy] = useState(false);
  const options = { images, history, lora };
  const plan = useQuery<WorkPlan>({ queryKey: ['package-plan', ids, images, history, lora], queryFn: () => post('/api/packages/works/plan', { ids, options }) });
  async function run() {
    setBusy(true);
    try {
      await downloadPost('/api/packages/works/export', { ids, options }, 'AtelierX-works.zip');
      toast({ text: t('package.exported') });
      onClose();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={ids.length > 1 ? t('package.backup_title', { n: ids.length }) : t('package.export_title')}
      onClose={onClose}
      actions={
        <button className="primary" disabled={busy || !plan.data} onClick={run}>
          {busy ? t('package.packing') : t('package.download')}
        </button>
      }
    >
      <p className="faint">{t('package.export_about')}</p>
      <label className="col" style={{ gap: 2 }}>
        <span className="muted">{t('package.images')}</span>
        <select value={images} onChange={(e) => setImages(e.target.value as typeof images)}>
          {(['adopted', 'all', 'none'] as const).map((k) => (
            <option key={k} value={k}>
              {t(`package.images_${k}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /> {t('package.history')}
      </label>
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="checkbox" checked={lora} onChange={(e) => setLora(e.target.checked)} /> {t('package.lora')}
      </label>
      {plan.data && (
        <div className="col small" style={{ gap: 2 }}>
          {plan.data.works.map((w) => (
            <div key={w.id}>
              <strong>{w.name}</strong> <span className="faint mono">{w.id}</span> · {t('package.work_counts', { files: w.files, images: w.images, loras: w.loras, size: formatBytes(w.bytes) })}
            </div>
          ))}
          <div className="muted">{t('package.total', { files: plan.data.files, size: formatBytes(plan.data.bytes) })}</div>
        </div>
      )}
      <p className="faint small">{t('package.no_credentials')}</p>
    </Dialog>
  );
}

// Choose a package file, see what is in it, and bring in works or settings.
export function PackageImportDialog({ onClose, onImported }: { onClose: () => void; onImported?: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const file = useRef<HTMLInputElement>(null);
  const [seen, setSeen] = useState<Inspected | null>(null);
  const [picked, setPicked] = useState<Set<number | string>>(new Set());
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  async function upload(chosen: File) {
    setBusy(true);
    try {
      const response = await fetch('/api/packages/upload', { method: 'POST', body: chosen, credentials: 'same-origin', headers: { 'Content-Type': 'application/zip' } });
      if (!response.ok) throw await apiError(response);
      const data: Inspected = await response.json();
      setSeen(data);
      const keys: (number | string)[] = data.kind === 'works' ? (data.works ?? []).map((w) => w.index) : (data.areas ?? []).filter((a) => a.area !== 'vault').map((a) => a.area);
      setPicked(new Set(keys));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function bring() {
    if (!seen) return;
    setBusy(true);
    try {
      if (seen.kind === 'works') {
        const result = await post<{ imported: { id: string; name: string; renumbered: boolean }[]; skipped_loras: string[] }>('/api/packages/works/import', {
          token: seen.token,
          works: [...picked].map((index) => ({ index })),
        });
        toast({
          text: [
            t('package.imported_works', { names: result.imported.map((w) => `${w.name} (${w.id})`).join(', ') }),
            result.skipped_loras.length ? t('package.skipped_loras', { n: result.skipped_loras.length }) : '',
          ]
            .filter(Boolean)
            .join(' '),
        });
        qc.invalidateQueries({ queryKey: ['works'] });
      } else {
        const result = await post<{ applied: string[]; backup: string | null }>('/api/packages/settings/import', {
          token: seen.token,
          areas: [...picked],
          vault_password: picked.has('vault') ? password : undefined,
        });
        toast({ text: t('package.imported_settings', { areas: result.applied.map((a) => t(`package.area.${a}`)).join(', ') }) });
        qc.invalidateQueries();
      }
      onImported?.();
      onClose();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  const toggle = (key: number | string, on: boolean) => setPicked((all) => (on ? new Set([...all, key]) : new Set([...all].filter((x) => x !== key))));
  return (
    <Dialog
      title={t('package.import_title')}
      onClose={onClose}
      actions={
        seen && (
          <button className="primary" disabled={busy || picked.size === 0 || (picked.has('vault') && !password)} onClick={bring}>
            {t('package.import_run')}
          </button>
        )
      }
    >
      {!seen && (
        <>
          <p className="faint">{t('package.import_about')}</p>
          <input ref={file} type="file" accept=".zip,application/zip" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          {busy && <span className="faint">{t('package.reading')}</span>}
        </>
      )}
      {seen && (
        <div className="col" style={{ gap: 6 }}>
          <span className="faint small">{t('package.made_by', { version: seen.app_version ?? '?', at: seen.created_at ? new Date(seen.created_at).toLocaleString() : '?' })}</span>
          {seen.kind === 'works' &&
            (seen.works ?? []).map((w) => (
              <label key={w.index} className="row" style={{ flexDirection: 'row', alignItems: 'flex-start' }}>
                <input type="checkbox" checked={picked.has(w.index)} onChange={(e) => toggle(w.index, e.target.checked)} />
                <span className="col" style={{ gap: 0 }}>
                  <span>
                    <strong>{w.name}</strong> <span className="faint mono">{w.id}</span>
                  </span>
                  <span className="faint small">{t('package.work_counts', { files: w.files, images: w.images, loras: w.loras, size: formatBytes(w.bytes) })}</span>
                  {w.id_taken && <span className="warn-text small">{t('package.id_taken')}</span>}
                  {!w.id_taken && w.name_taken && <span className="warn-text small">{t('package.name_taken')}</span>}
                </span>
              </label>
            ))}
          {seen.kind === 'settings' && (
            <>
              {(seen.areas ?? []).map((a) => (
                <label key={a.area} className="row" style={{ flexDirection: 'row' }}>
                  <input type="checkbox" checked={picked.has(a.area)} onChange={(e) => toggle(a.area, e.target.checked)} />
                  {t(`package.area.${a.area}`)}
                  {a.exists && a.area !== 'vault' && <span className="faint small">{t('package.replaces')}</span>}
                </label>
              ))}
              {picked.has('vault') && (
                <label className="col" style={{ gap: 2 }}>
                  <span className="muted">{t('package.vault_password')}</span>
                  <input type="password" autoComplete="off" value={password} onChange={(e) => setPassword(e.target.value)} />
                </label>
              )}
              <p className="faint small">{t('package.settings_backup_note')}</p>
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}

// Settings → 꾸러미: pack the chosen settings areas, or bring a package in.
export function SettingsPackages() {
  const toast = useToast();
  const [areas, setAreas] = useState<Set<string>>(new Set(SETTING_AREAS));
  const [vault, setVault] = useState(false);
  const [importing, setImporting] = useState(false);
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      await downloadPost('/api/packages/settings/export', { areas: [...areas, ...(vault ? ['vault'] : [])] }, 'AtelierX-settings.zip');
      toast({ text: t('package.exported') });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="col" style={{ maxWidth: 640 }}>
      <p className="faint">{t('package.settings_about')}</p>
      <div className="section-title">{t('package.settings_export')}</div>
      {SETTING_AREAS.map((area) => (
        <label key={area} className="row" style={{ gap: 4 }}>
          <input type="checkbox" checked={areas.has(area)} onChange={(e) => setAreas((all) => (e.target.checked ? new Set([...all, area]) : new Set([...all].filter((x) => x !== area))))} />
          {t(`package.area.${area}`)}
        </label>
      ))}
      <label className="row" style={{ gap: 4 }}>
        <input type="checkbox" checked={vault} onChange={(e) => setVault(e.target.checked)} />
        {t('package.area.vault')}
      </label>
      {vault && <p className="warn-text small">{t('package.vault_warning')}</p>}
      <p className="faint small">{t('package.machine_only')}</p>
      <div className="row">
        <button className="primary" disabled={busy || (areas.size === 0 && !vault)} onClick={run}>
          {busy ? t('package.packing') : t('package.download')}
        </button>
        <button onClick={() => setImporting(true)}>{t('package.import_title')}</button>
      </div>
      {importing && <PackageImportDialog onClose={() => setImporting(false)} />}
    </div>
  );
}
