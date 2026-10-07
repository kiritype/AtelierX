import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { get, post, put } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';

type Scope = { work?: string; character?: string; outfit?: string };
type Target = { id: string; name: string; ready: boolean; path_format: string; public_url: string };
type Row = {
  source: string;
  thumbnail_url?: string;
  character_id: string;
  outfit_id: string;
  outfit_code: string;
  expression_id: string;
  expression_name: string;
  expression_code: string;
  rating: string;
  auto_path: string | null;
  path: string | null;
  edited: boolean;
  status: 'new' | 'overwrite' | 'unchanged' | 'no_code' | 'clash';
  url?: string;
};
type Plan = { target: string; target_name: string; public_url: string; path_format: string; rows: Row[]; counts: Record<string, number>; missing: string[] };
type Result = { path: string; url: string; ok: boolean; overwrote: boolean; error?: { key: string; text: string } };
type Run = { id: string; status: string; total: number; done: number; results: Result[] };

const STATUSES: Row['status'][] = ['new', 'overwrite', 'unchanged', 'no_code', 'clash'];
const CHIP: Record<Row['status'], string> = { new: 'ok', overwrite: 'accent', unchanged: '', no_code: 'warn', clash: 'warn' };

function saveText(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

// Gallery → Upload to a deployment target (decision 0023): preview the paths and states, upload, then the URLs.
export function DeployUpload({ scope, close, fail }: { scope: Scope; close: () => void; fail: (err: unknown) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const work = scope.work;
  const targets = useQuery<{ targets: Target[] }>({ queryKey: ['deploy-targets'], queryFn: () => get('/api/image/deploy/targets') });
  const saved = useQuery<{ target: string | null; path_format: string | null }>({
    queryKey: ['work-deploy', work],
    queryFn: () => get(`/api/works/${work}/image/deploy`),
    enabled: !!work,
  });
  const rules = useQuery<{ ratings: { id: string; name: string }[] }>({ queryKey: ['image-lib-rules'], queryFn: () => get('/api/image/library/rules') });
  const [target, setTarget] = useState('');
  const [format, setFormat] = useState('');
  const [ratings, setRatings] = useState<string[] | null>(null); // null: every rating (the default)
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<Run | null>(null);

  // The work's saved choice first, else the first target with keys.
  useEffect(() => {
    if (target || !targets.data || (work && !saved.data)) return;
    const pick = targets.data.targets.find((x) => x.id === saved.data?.target) ?? targets.data.targets.find((x) => x.ready) ?? targets.data.targets[0];
    if (pick) {
      setTarget(pick.id);
      setFormat(saved.data?.path_format ?? pick.path_format);
    }
  }, [targets.data, saved.data, target, work]);

  // Follow a running upload.
  useEffect(() => {
    if (!run || !['running', 'cancelling'].includes(run.status)) return;
    const timer = setInterval(async () => {
      try {
        setRun(await get<Run>(`/api/image/deploy/runs/${run.id}`));
      } catch (err) {
        fail(err);
      }
    }, 700);
    return () => clearInterval(timer);
  }, [run, fail]);

  // After an upload, the preview shows what the bucket holds now.
  const finishedId = run && !['running', 'cancelling'].includes(run.status) ? run.id : '';
  useEffect(() => {
    if (finishedId) preview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finishedId]);

  // The gallery's range (work, and the character or outfit chosen there) goes with every plan and upload.
  const body = () => ({
    work,
    character: scope.character,
    outfit: scope.outfit,
    target,
    path_format: format,
    ratings,
    paths: Object.fromEntries(Object.entries(paths).filter(([, v]) => v.trim())),
  });
  const noRatings = ratings !== null && ratings.length === 0;

  async function preview() {
    setBusy(true);
    try {
      setPlan(await post<Plan>('/api/image/deploy/plan', body()));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function upload(only?: string[]) {
    setBusy(true);
    try {
      setRun(await post<Run>('/api/image/deploy/upload', { ...body(), ...(only ? { only } : {}) }));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  async function keepForWork() {
    try {
      await put(`/api/works/${work}/image/deploy`, { target, path_format: format });
      qc.invalidateQueries({ queryKey: ['work-deploy', work] });
      toast({ text: t('deploy.kept_for_work') });
    } catch (err) {
      fail(err);
    }
  }

  const list = targets.data?.targets ?? [];
  const chosen = list.find((x) => x.id === target);
  const sendable = plan ? plan.rows.filter((r) => r.status === 'new' || r.status === 'overwrite').length : 0;
  const running = !!run && ['running', 'cancelling'].includes(run.status);
  const finished = !!run && !running;
  const failed = run?.results.filter((r) => !r.ok) ?? [];
  const uploaded = run?.results.filter((r) => r.ok) ?? [];
  const overwritten = uploaded.filter((r) => r.overwrote);
  const urls = (plan?.rows ?? []).filter((r) => r.url && r.status !== 'no_code' && r.status !== 'clash').map((r) => r.url!);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !running && close()}>
      <div className="dialog col" style={{ width: 'min(1100px, 94vw)', maxWidth: 'none', maxHeight: '90vh', overflow: 'auto' }}>
        <h3>{t('deploy.upload_title')}</h3>
        <p className="faint small">{t('deploy.upload_about')}</p>
        {!work ? (
          <div className="warn-text">{t('deploy.choose_work')}</div>
        ) : list.length === 0 ? (
          <div className="warn-text">{t('deploy.no_targets')}</div>
        ) : (
          <>
            <div className="row" style={{ flexWrap: 'wrap', alignItems: 'end' }}>
              <label>
                {t('settings.deploy')}
                <select value={target} disabled={running} onChange={(e) => (setTarget(e.target.value), setPlan(null))}>
                  {list.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name} {x.ready ? '' : `(${t('deploy.no_keys')})`}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: 1, minWidth: 260 }}>
                {t('deploy.path_format')}
                <input className="mono" value={format} disabled={running} onChange={(e) => (setFormat(e.target.value), setPlan(null))} />
              </label>
              <button disabled={running} onClick={keepForWork} title={t('deploy.keep_for_work_hint')}>
                {t('deploy.keep_for_work')}
              </button>
            </div>
            <span className="faint small">{t('deploy.path_format_hint')}</span>
            <div className="row" style={{ flexWrap: 'wrap' }}>
              <span className="muted small">{t('deploy.ratings')}</span>
              {(rules.data?.ratings ?? []).map((r) => (
                <label key={r.id} className="row" style={{ flexDirection: 'row', gap: 4 }}>
                  <input
                    type="checkbox"
                    disabled={running}
                    checked={!ratings || ratings.includes(r.id)}
                    onChange={(e) => {
                      const all = (rules.data?.ratings ?? []).map((x) => x.id);
                      const now = new Set(ratings ?? all);
                      if (e.target.checked) now.add(r.id);
                      else now.delete(r.id);
                      setRatings(now.size === all.length ? null : [...now]);
                      setPlan(null);
                    }}
                  />
                  {r.name}
                </label>
              ))}
            </div>
            <div className="notice col small">
              <span>{t('deploy.public_note')}</span>
              {chosen && /\.r2\.dev(\/|$)/i.test(chosen.public_url) && <span className="warn-text">{t('deploy.r2dev')}</span>}
            </div>
            <div className="row">
              <button className="primary" disabled={busy || running || !target || noRatings} onClick={preview}>
                {plan ? t('deploy.preview_again') : t('deploy.preview')}
              </button>
              {noRatings && <span className="warn-text small">{t('deploy.no_ratings')}</span>}
              {plan && (
                <span className="faint small">
                  {STATUSES.filter((s) => plan.counts[s]).map((s) => `${t(`deploy.status.${s}`)} ${plan.counts[s]}`).join(' · ')}
                </span>
              )}
            </div>
          </>
        )}

        {plan && (
          <>
            {plan.missing.length > 0 && (
              <details>
                <summary className="warn-text small">{t('gallery.export_missing', { n: plan.missing.length })}</summary>
                <div className="mono small faint" style={{ maxHeight: 120, overflow: 'auto', whiteSpace: 'pre-line' }}>
                  {plan.missing.join('\n')}
                </div>
              </details>
            )}
            {(plan.counts.no_code ?? 0) > 0 && <span className="warn-text small">{t('deploy.no_code_hint')}</span>}
            {(plan.counts.clash ?? 0) > 0 && <span className="warn-text small">{t('deploy.clash_hint')}</span>}
            <div style={{ maxHeight: '38vh', overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
              <table className="plain deploy-rows">
                <thead>
                  <tr>
                    <th />
                    <th>{t('deploy.combo')}</th>
                    <th>{t('deploy.path')}</th>
                    <th>{t('deploy.state')}</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.rows.map((row) => (
                    <tr key={row.source}>
                      <td>{row.thumbnail_url && <img src={row.thumbnail_url} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} />}</td>
                      <td className="small">
                        {row.character_id} · {row.outfit_id}
                        {row.outfit_code ? <span className="faint mono"> ({row.outfit_code})</span> : <span className="warn-text"> ({t('deploy.no_code_short')})</span>} · {row.expression_name || row.expression_id}
                        {row.expression_code ? <span className="faint mono"> ({row.expression_code})</span> : <span className="warn-text"> ({t('deploy.no_code_short')})</span>}
                      </td>
                      <td>
                        <input
                          className="mono small"
                          style={{ width: '100%', minWidth: 260 }}
                          disabled={running}
                          placeholder={row.auto_path ?? t('deploy.type_path')}
                          value={paths[row.source] ?? (row.edited ? row.path ?? '' : '')}
                          onChange={(e) => setPaths({ ...paths, [row.source]: e.target.value })}
                          title={row.path ?? ''}
                        />
                      </td>
                      <td>
                        <span className={`chip small ${CHIP[row.status]}`}>{t(`deploy.status.${row.status}`)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {Object.keys(paths).length > 0 && <span className="faint small">{t('deploy.edited_hint')}</span>}
          </>
        )}

        {run && (
          <div className="col" style={{ gap: 6 }}>
            <div className="row">
              <span className="grow">
                {t(`jobs.status.${run.status}`)} · {run.done}/{run.total}
              </span>
              {running && (
                <button onClick={async () => setRun(await post<Run>(`/api/image/deploy/runs/${run.id}/cancel`))}>{t('common.cancel')}</button>
              )}
            </div>
            <div className="progress">
              <div style={{ width: `${run.total ? (run.done * 100) / run.total : 0}%` }} />
            </div>
            {finished && (
              <>
                <span className="small">{t('deploy.result', { ok: uploaded.length, failed: failed.length })}</span>
                {failed.length > 0 && (
                  <div className="col small">
                    {failed.map((r) => (
                      <span key={r.path} className="error-text">
                        <span className="mono">{r.path}</span>: {r.error ? tm(r.error) : ''}
                      </span>
                    ))}
                    <div>
                      <button disabled={busy} onClick={() => upload(failed.map((r) => r.path))}>{t('deploy.retry_failed')}</button>
                    </div>
                  </div>
                )}
                {overwritten.length > 0 && (
                  <div className="notice col small">
                    <span>{t('deploy.cache_note')}</span>
                    <textarea readOnly rows={Math.min(6, overwritten.length)} className="mono small" value={overwritten.map((r) => r.url).join('\n')} />
                  </div>
                )}
                <span className="faint small">{t('deploy.no_delete')}</span>
              </>
            )}
          </div>
        )}

        <div className="row" style={{ justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {plan && urls.length > 0 && (
            <>
              <button onClick={() => navigator.clipboard.writeText(urls.join('\n')).then(() => toast({ text: t('deploy.urls_copied', { n: urls.length }) }))}>
                {t('deploy.copy_urls')}
              </button>
              <button onClick={() => saveText(`${work}-urls.txt`, urls.join('\n') + '\n')}>{t('deploy.save_urls')}</button>
            </>
          )}
          <button disabled={running} onClick={close}>
            {t('common.close')}
          </button>
          <button className="primary" disabled={busy || running || !plan || sendable === 0 || noRatings} onClick={() => upload()}>
            {t('deploy.upload_n', { n: sendable })}
          </button>
        </div>
      </div>
    </div>
  );
}
