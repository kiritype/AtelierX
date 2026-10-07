import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, get, post } from '../../api';
import { msgText, t, tm } from '../../i18n';
import { useToast } from '../Toasts';

// Image menu → Models → Get (#161): read a Civitai address, choose a version and file, and queue it; or put a file
// downloaded with a browser into the right folder. Downloads run one at a time and resume after a break.
type CivFile = { id: number; name: string; size: number; type: string; primary: boolean; sha256: string; url: string; kind: string };
type Version = { id: number; name: string; base_model: string; family: string | null; trained_words: string[]; files: CivFile[] };
type Read = {
  model: { id: number; name: string; type: string; nsfw: boolean; creator: string; license: Record<string, unknown>; url: string };
  versions: Version[];
  chosen_version: number | null;
  has_key: boolean;
};
type Job = {
  id: string;
  status: 'queued' | 'running' | 'paused' | 'done' | 'failed' | 'cancelled';
  name: string;
  kind: string;
  target: string;
  size: number;
  received: number;
  error?: { key: string; text: string } | string | null;
  model?: { name?: string };
  version?: { name?: string };
};
type Inspected = { path: string; name: string; size: number; sha256: string; info: Record<string, any> | null; kind: string | null; family: string | null };
const KINDS = ['checkpoints', 'diffusion_models', 'loras', 'text_encoders', 'vae', 'embeddings', 'upscale_models'];
const mb = (n: number) => (n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2)} GB` : `${Math.max(1, Math.round(n / 1024 ** 2))} MB`);

export default function ModelGet({ openSettings }: { openSettings?: (section?: 'image' | 'install') => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const [address, setAddress] = useState('');
  const [read, setRead] = useState<Read | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [subfolder, setSubfolder] = useState('');
  const [busy, setBusy] = useState(false);
  const jobs = useQuery<{ jobs: Job[]; has_key: boolean }>({
    queryKey: ['model-downloads'],
    queryFn: () => get('/api/image/models/downloads'),
    refetchInterval: (q) => ((q.state.data?.jobs ?? []).some((j) => j.status === 'running' || j.status === 'queued') ? 1500 : false),
  });
  const version = read?.versions.find((v) => v.id === versionId) ?? read?.versions[0];

  async function readAddress() {
    setBusy(true);
    try {
      const found = await post<Read>('/api/image/models/read', { address });
      setRead(found);
      setVersionId(found.chosen_version ?? found.versions[0]?.id ?? null);
      setSubfolder('');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }
  async function queue(file: CivFile) {
    if (!read || !version) return;
    try {
      qc.setQueryData(['model-downloads'], await post('/api/image/models/downloads', { model: read.model, version, file, subfolder: subfolder || undefined }));
      toast({ text: t('models.get.queued', { name: file.name }) });
    } catch (err) {
      fail(err);
    }
  }
  async function act(job: Job, action: string) {
    try {
      qc.setQueryData(['model-downloads'], await post(`/api/image/models/downloads/${job.id}/${action}`));
      if (action === 'remove') qc.invalidateQueries({ queryKey: ['image-models'] });
    } catch (err) {
      fail(err);
    }
  }

  return (
    <div className="col pad" style={{ gap: 14, maxWidth: 980 }}>
      {!jobs.data?.has_key && (
        <div className="warn-text small row" style={{ gap: 6 }}>
          {t('models.get.no_key')}
          {openSettings && (
            <button className="ghost small" onClick={() => openSettings('image')}>
              {t('gen.open_settings')}
            </button>
          )}
        </div>
      )}
      <section className="col" style={{ gap: 6 }}>
        <div className="section-title">{t('models.get.from_civitai')}</div>
        <div className="row">
          <input className="grow" value={address} placeholder={t('models.get.address_hint')} onChange={(e) => setAddress(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && address.trim() && readAddress()} />
          <button className="primary" disabled={!address.trim() || busy} onClick={readAddress}>
            {busy ? t('models.get.reading') : t('models.get.read')}
          </button>
        </div>
        {read && version && (
          <div className="col gen-patch" style={{ gap: 6 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <strong>{read.model.name}</strong>
              <span className="chip small">{read.model.type}</span>
              {read.model.nsfw && <span className="chip small warn">NSFW</span>}
              <span className="faint small">{read.model.creator}</span>
              <span className="faint small mono">{read.model.url}</span>
            </div>
            <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
              <label className="row small" style={{ gap: 4 }}>
                <span className="muted">{t('models.get.version')}</span>
                <select value={version.id} onChange={(e) => setVersionId(Number(e.target.value))}>
                  {read.versions.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name} · {v.base_model}
                    </option>
                  ))}
                </select>
              </label>
              <label className="row small" style={{ gap: 4 }} title={t('models.get.subfolder_hint')}>
                <span className="muted">{t('models.get.subfolder')}</span>
                <input style={{ width: 120 }} value={subfolder} placeholder={version.family ?? ''} onChange={(e) => setSubfolder(e.target.value)} />
              </label>
            </div>
            {version.trained_words.length > 0 && (
              <div className="small">
                <span className="muted">{t('models.trained_words')}: </span>
                <span className="mono">{version.trained_words.join(', ')}</span>
              </div>
            )}
            {Object.keys(read.model.license).length > 0 && (
              <div className="small">
                <span className="muted">{t('models.license')}: </span>
                {Object.entries(read.model.license)
                  .map(([k, v]) => `${t(`models.license_key.${k}`)} ${Array.isArray(v) ? v.join(', ') || '—' : v ? t('models.yes') : t('models.no')}`)
                  .join(' · ')}
              </div>
            )}
            <table className="gen-table small">
              <tbody>
                {version.files.map((f) => (
                  <tr key={f.id}>
                    <td className="mono">{f.name}</td>
                    <td>{f.type}</td>
                    <td>{mb(f.size)}</td>
                    <td>{t(`models.get.kind.${f.kind}`)}</td>
                    <td>
                      <button className={f.primary ? 'primary small' : 'small'} onClick={() => queue(f)}>
                        {t('models.get.get')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <span className="faint small">{t('models.get.check_license')}</span>
          </div>
        )}
      </section>

      <section className="col" style={{ gap: 6 }}>
        <div className="section-title">{t('models.get.list')}</div>
        {(jobs.data?.jobs ?? []).length === 0 && <span className="faint small">{t('models.get.none')}</span>}
        {(jobs.data?.jobs ?? []).map((job) => (
          <div key={job.id} className="row small" style={{ gap: 8, flexWrap: 'wrap' }}>
            <span className={`chip small${job.status === 'failed' ? ' warn' : ''}`}>{t(`models.get.status.${job.status}`)}</span>
            <span className="mono grow">{job.name}</span>
            {(job.status === 'running' || job.status === 'paused') && job.size > 0 && (
              <span className="faint">
                {Math.floor((job.received * 100) / job.size)}% · {mb(job.received)} / {mb(job.size)}
              </span>
            )}
            {job.error && <span className="warn-text">{typeof job.error === 'string' ? job.error : msgText(job.error)}</span>}
            {['queued', 'running', 'paused'].includes(job.status) && (
              <button className="ghost small" onClick={() => act(job, 'cancel')}>
                {t('common.cancel')}
              </button>
            )}
            {['paused', 'failed'].includes(job.status) && (
              <button className="small" onClick={() => act(job, 'resume')}>
                {t('models.get.resume')}
              </button>
            )}
            {!['queued', 'running'].includes(job.status) && (
              <button className="ghost small" onClick={() => act(job, 'remove')} title={t('models.get.remove_hint')}>
                ×
              </button>
            )}
          </div>
        ))}
      </section>

      <PlaceFile />
    </div>
  );
}

// A file downloaded with a browser: hash it, ask Civitai what it is, and move it to the folder for its kind.
function PlaceFile() {
  const qc = useQueryClient();
  const toast = useToast();
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const [folder, setFolder] = useState('');
  const [open, setOpen] = useState(false);
  const listing = useQuery<{ folder: string; files: { path: string; name: string; size: number }[] }>({
    queryKey: ['model-downloaded', folder],
    queryFn: () => get(`/api/image/models/downloaded?folder=${encodeURIComponent(folder)}`),
    enabled: open,
    retry: false,
  });
  const [checked, setChecked] = useState<Inspected | null>(null);
  const [kind, setKind] = useState('loras');
  const [sub, setSub] = useState('');
  const [busy, setBusy] = useState<string | null>(null);

  async function inspect(path: string) {
    setBusy(path);
    try {
      const found = await post<Inspected>('/api/image/models/downloaded/inspect', { path });
      setChecked(found);
      setKind(found.kind ?? 'loras');
      setSub(found.family ?? '');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }
  async function place() {
    if (!checked) return;
    try {
      const done = await post<{ target: string }>('/api/image/models/downloaded/place', { path: checked.path, kind, subfolder: sub, sha256: checked.sha256, info: checked.info });
      toast({ text: t('models.place.done', { target: done.target }) });
      setChecked(null);
      qc.invalidateQueries({ queryKey: ['model-downloaded'] });
      qc.invalidateQueries({ queryKey: ['image-models'] });
    } catch (err) {
      fail(err);
    }
  }

  return (
    <section className="col" style={{ gap: 6 }}>
      <button className="ghost row" style={{ gap: 6, justifyContent: 'flex-start' }} onClick={() => setOpen(!open)}>
        <span>{open ? '▾' : '▸'}</span>
        <strong>{t('models.place.title')}</strong>
      </button>
      {open && (
        <>
          <span className="faint small">{t('models.place.about')}</span>
          <div className="row">
            <input className="mono grow" value={folder} placeholder={listing.data?.folder ?? t('models.place.folder_hint')} onChange={(e) => setFolder(e.target.value)} />
          </div>
          {listing.isError && <span className="warn-text small">{listing.error instanceof ApiError ? tm(listing.error.msg) : ''}</span>}
          {(listing.data?.files ?? []).length === 0 && listing.data && <span className="faint small">{t('models.place.none')}</span>}
          {(listing.data?.files ?? []).map((f) => (
            <div key={f.path} className="row small" style={{ gap: 8 }}>
              <span className="mono grow">{f.name}</span>
              <span className="faint">{mb(f.size)}</span>
              <button className="small" disabled={busy !== null} onClick={() => inspect(f.path)}>
                {busy === f.path ? t('models.looking_up') : t('models.place.check')}
              </button>
            </div>
          ))}
          {checked && (
            <div className="col gen-patch" style={{ gap: 6 }}>
              <strong className="mono">{checked.name}</strong>
              <span className="small">{checked.info ? t('models.place.found', { name: `${checked.info.model_name} ${checked.info.version_name}`, base: checked.info.base_model }) : t('models.lookup_none')}</span>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                <label className="row small" style={{ gap: 4 }}>
                  <span className="muted">{t('models.facet.kind')}</span>
                  <select value={kind} onChange={(e) => setKind(e.target.value)}>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {t(`models.get.kind.${k}`)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="row small" style={{ gap: 4 }}>
                  <span className="muted">{t('models.get.subfolder')}</span>
                  <input style={{ width: 120 }} value={sub} onChange={(e) => setSub(e.target.value)} />
                </label>
                <button className="primary small" onClick={place}>
                  {t('models.place.move')}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
