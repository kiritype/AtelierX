import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { get, post, put } from '../../api';
import { t, msgText } from '../../i18n';
import { useToast } from '../Toasts';

type Scope = { work?: string; character?: string; outfit?: string };
import type { DeployTarget as Target, DeployRow as Row, DeployPlan as Plan, DeployRun as Run, DeployHistory as History } from '../../imageTypes';

const STATUSES: Row['status'][] = ['new', 'existing', 'unchanged', 'no_code', 'clash'];
const CHIP: Record<Row['status'], string> = { new: 'ok', existing: 'accent', unchanged: '', no_code: 'warn', clash: 'warn' };

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
  const history = useQuery<History>({ queryKey: ['deploy-history', work], queryFn: () => get(`/api/works/${work}/image/deploy/history`), enabled: !!work });
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
  const [uploadPending, setUploadPending] = useState(false);
  const submitting = useRef(false);
  const [run, setRun] = useState<Run | null>(null);
  const [stage, setStage] = useState<'settings' | 'preview' | 'progress' | 'result'>('settings');
  const [planBody, setPlanBody] = useState<ReturnType<typeof body> | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const request = useRef(0);

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
    let active = true;
    let pending = false;
    const id = run.id;
    const timer = setInterval(async () => {
      if (pending) return;
      pending = true;
      try {
        const next = await get<Run>(`/api/image/deploy/runs/${id}`);
        if (active) setRun((current) => current?.id === id ? next : current);
      } catch (err) {
        if (active) fail(err);
      } finally {
        pending = false;
      }
    }, 700);
    return () => { active = false; clearInterval(timer); };
  }, [run, fail]);

  const finishedId = run && !['running', 'cancelling'].includes(run.status) ? run.id : '';
  useEffect(() => {
    if (finishedId) {
      setStage('result');
      qc.invalidateQueries({ queryKey: ['deploy-history', work] });
    }
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
  const currentBody = JSON.stringify(body());
  const freshPlan = !!plan && !!planBody && JSON.stringify(planBody) === currentBody;
  function changed() {
    request.current += 1;
    setPlan(null);
    setPlanBody(null);
    setBusy(false);
  }
  function backToSettings() {
    request.current += 1;
    setBusy(false);
    setStage('settings');
  }

  async function preview() {
    const token = ++request.current;
    const input = body();
    setBusy(true);
    try {
      const next = await post<Plan>('/api/image/deploy/plan', input);
      if (token !== request.current) return;
      setPlan(next);
      setPlanBody(input);
      setStage('preview');
    } catch (err) {
      if (token === request.current) fail(err);
    } finally {
      if (token === request.current) setBusy(false);
    }
  }

  async function upload(only?: string[]) {
    if (!planBody || !freshPlan || !plan || busy || submitting.current) return;
    submitting.current = true;
    setUploadPending(true);
    setBusy(true);
    try {
      const next = await post<Run>('/api/image/deploy/upload', { ...planBody, ...(only ? { only } : {}) });
      setRun(next);
      setStage(['running', 'cancelling'].includes(next.status) ? 'progress' : 'result');
    } catch (err) {
      fail(err);
    } finally {
      submitting.current = false;
      setUploadPending(false);
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
  const sendable = plan ? plan.rows.filter((r) => r.status === 'new' || r.status === 'existing').length : 0;
  const running = !!run && ['running', 'cancelling'].includes(run.status);
  const locked = running || uploadPending;
  const finished = !!run && !running;
  const failed = run?.results.filter((r) => !r.ok) ?? [];
  const uploaded = run?.results.filter((r) => r.ok && r.status !== 'unchanged') ?? [];
  const skipped = run?.results.filter((r) => r.status === 'unchanged') ?? [];
  const overwritten = uploaded.filter((r) => r.overwrote);
  const resultStates = new Map(run?.results.map((r) => [r.source, r.status]));
  const urls = (run?.results ?? []).filter((r) => r.ok && r.url).map((r) => r.url);

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !locked && close()}>
      <div className="dialog col deploy-dialog" role="dialog" aria-label={t('deploy.upload_title')} data-stage={stage}>
        <h3>{t('deploy.upload_title')}</h3>
        <p className="faint small">{t(`deploy.stage.${stage}`)}</p>
        {stage === 'settings' && <>
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
                <select value={target} disabled={locked} onChange={(e) => { changed(); setTarget(e.target.value); }}>
                  {list.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name} {x.ready ? '' : `(${t('deploy.no_keys')})`}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: 1, minWidth: 260 }}>
                {t('deploy.path_format')}
                <input className="mono" value={format} disabled={locked} onChange={(e) => { changed(); setFormat(e.target.value); }} />
              </label>
              <button disabled={locked} onClick={keepForWork} title={t('deploy.keep_for_work_hint')}>
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
                    disabled={locked}
                    checked={!ratings || ratings.includes(r.id)}
                    onChange={(e) => {
                      const all = (rules.data?.ratings ?? []).map((x) => x.id);
                      const now = new Set(ratings ?? all);
                      if (e.target.checked) now.add(r.id);
                      else now.delete(r.id);
                      setRatings(now.size === all.length ? null : [...now]);
                      changed();
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
              <button className="primary" disabled={busy || locked || !target || noRatings} onClick={() => { setRun(null); preview(); }}>
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
        </>}

        {(stage === 'preview' || (stage === 'result' && showPreview)) && plan && (
          <>
            {stage === 'preview' && <div className="row deploy-stage-actions">
              <button disabled={locked} onClick={backToSettings}>{t('deploy.back_settings')}</button>
              <button disabled={busy || locked} onClick={preview}>{t('deploy.preview_again')}</button>
              <span className="faint small">{STATUSES.filter((s) => plan.counts[s]).map((s) => `${t(`deploy.status.${s}`)} ${plan.counts[s]}`).join(' · ')}</span>
            </div>}
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
            <div className="deploy-preview-list">
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
                          disabled={stage !== 'preview' || locked}
                          placeholder={row.auto_path ?? t('deploy.type_path')}
                          value={paths[row.source] ?? (row.edited ? row.path ?? '' : '')}
                          onChange={(e) => { request.current += 1; setBusy(false); setPaths({ ...paths, [row.source]: e.target.value }); setPlanBody(null); }}
                          title={row.path ?? ''}
                        />
                      </td>
                      <td>
                        <span className={`chip small ${CHIP[row.status]}`}>{t(`deploy.status.${run?.current?.source === row.source ? run.current.status : resultStates.get(row.source) ?? row.status}`)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!freshPlan && stage === 'preview' && <span className="warn-text small">{t('deploy.preview_stale')}</span>}
            {Object.keys(paths).length > 0 && <span className="faint small">{t('deploy.edited_hint')}</span>}
          </>
        )}

        {(stage === 'progress' || stage === 'result') && run && (
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
            {running && run.current && <span className="small mono" style={{ overflowWrap: 'anywhere' }}>{run.current.path} · {t(`deploy.status.${run.current.status}`)}</span>}
            {finished && (
              <>
                <span className="small">{t('deploy.result', { ok: uploaded.length, failed: failed.length })} · {t('deploy.skipped', { n: skipped.length })}</span>
                {run.results.length > 0 && <div className="deploy-result-list small">
                  {run.results.map((r) => <div key={`${r.source}-${r.path}`} className="deploy-result-row">
                    <span className={`chip small ${r.ok ? 'ok' : 'warn'}`}>{t(`deploy.status.${r.status}`)}</span>
                    <span className="mono" style={{ overflowWrap: 'anywhere' }}>{r.path}</span>
                    {r.ok && r.url && <a href={r.url} target="_blank" rel="noreferrer" style={{ overflowWrap: 'anywhere' }}>{r.url}</a>}
                  </div>)}
                </div>}
                {run.results.filter((r) => r.log_error).map((r) => <span key={r.path} className="warn-text small">{t('deploy.log_failed')}: {r.path} — {msgText(r.log_error)}</span>)}
                {failed.length > 0 && (
                  <div className="col small">
                    {failed.map((r) => (
                      <span key={r.path} className="error-text">
                        <span className="mono">{r.path}</span>: {r.error ? msgText(r.error) : ''}
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

        <details>
          <summary>{t('deploy.history')}</summary>
          {history.isError && <span className="error-text">{t('deploy.history_failed')}</span>}
          {!history.isPending && !history.isError && !history.data?.records.length && <p className="faint small">{t('deploy.history_empty')}</p>}
          <div className="col small" style={{ maxHeight: 180, overflow: 'auto' }}>
            {(history.data?.records ?? []).map((r, i) => <div key={`${r.at}-${i}`}><span className="faint">{r.at} · {r.target_name}</span> · <span className="mono">{r.path}</span> · {t(`deploy.status.${r.status}`)}{r.error && <span className="error-text"> — {msgText(r.error)}</span>}</div>)}
          </div>
        </details>
        <div className="row deploy-footer" style={{ justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {stage === 'result' && urls.length > 0 && (
            <>
              <button onClick={() => navigator.clipboard.writeText(urls.join('\n')).then(() => toast({ text: t('deploy.urls_copied', { n: urls.length }) }))}>
                {t('deploy.copy_urls')}
              </button>
              <button onClick={() => saveText(`${work}-urls.txt`, urls.join('\n') + '\n')}>{t('deploy.save_urls')}</button>
            </>
          )}
          <button disabled={locked} onClick={close}>
            {t('common.close')}
          </button>
          {stage === 'preview' && <button className="primary" disabled={busy || locked || !freshPlan || sendable === 0 || noRatings} onClick={() => upload()}>
            {t('deploy.upload_candidates', { n: sendable, m: plan?.counts.existing ?? 0 })}
          </button>}
          {stage === 'result' && <>
            <button disabled={locked} onClick={() => setShowPreview((value) => !value)}>{t(showPreview ? 'deploy.hide_preview' : 'deploy.show_preview')}</button>
            <button disabled={locked} onClick={() => { setShowPreview(false); setStage('settings'); }}>{t('deploy.back_settings')}</button>
            <button className="primary" disabled={busy || locked} onClick={() => { setShowPreview(false); setRun(null); setStage('settings'); preview(); }}>{t('deploy.preview_again')}</button>
          </>}
        </div>
      </div>
    </div>
  );
}
