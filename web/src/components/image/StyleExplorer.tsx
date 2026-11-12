import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, get, post } from '../../api';
import { msgText, t, tm } from '../../i18n';
import type { ImageView } from '../../types';
import type {
  ExplorerCapabilities,
  ExplorerConfig,
  ExplorerResult,
  ExplorerSession,
  ExplorerSummary,
} from '../../styleExplorerTypes';
import type { ImageServices } from '../ImageServiceSettings';
import type { Activity } from '../JobsPopover';
import { useUnsaved } from '../Unsaved';
import { useCatalog } from './GenSettings';
import { useNovelAIInfo } from './NovelAISettings';
import { usePixAIInfo } from './PixAISettings';
import ExplorerSetup from './ExplorerSetup';
import ExplorerCompare from './ExplorerCompare';
import {
  comfyModelOptions, effectiveRules, EXPLORER_DRAFT_KEY, findLora, loraLimit, loraWeightLimit, materialPool,
  MODEL_POOL_LIMIT, parseModelPool, readDraft, requestMaterials, resolveComfyModels, settingsKey, storedDraft,
  validWeight, type ExplorerLora,
} from './styleExplorerDraft';
import './StyleExplorer.css';
const base = '/api/image/explorer';
const running = (s: ExplorerSession) =>
  s.candidates.some((c) => ['queued', 'running', 'cancelling'].includes(c.status));
export default function StyleExplorer({
  workId,
  active = true,
  openView,
  openSettings,
}: {
  workId?: string;
  active?: boolean;
  openView: (view: ImageView) => void;
  openSettings?: () => void;
}) {
  const [draft, setDraft] = useState(() => readDraft(workId));
  const [dirty, setDirty] = useState(false),
    [storageError, setStorageError] = useState(false);
  const [id, setId] = useState(''),
    [stage, setStage] = useState<'setup' | 'compare' | 'ranking'>('setup');
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [confirm, setConfirm] = useState(false);
  const [retryCandidate, setRetryCandidate] = useState('');
  const [count, setCount] = useState(8),
    [presetNames, setPresetNames] = useState<Record<string, string>>({});
  const requests = useRef<Record<string, string>>({});
  const pairAttempt = useRef('');
  const qc = useQueryClient();
  const capabilities = useQuery({
    queryKey: ['explorer-capabilities'],
    queryFn: () => get<ExplorerCapabilities>(`${base}/capabilities`),
  });
  const services = useQuery({
    queryKey: ['image-services'],
    queryFn: () => get<ImageServices>('/api/image/services'),
  });
  const catalog = useCatalog();
  const novelai = useNovelAIInfo(),
    pixai = usePixAIInfo();
  const pool = materialPool(draft);
  const availableLoras: ExplorerLora[] | undefined =
    draft.service === 'pixai'
      ? pixai.data?.loras
      : draft.service === 'comfyui' && catalog.data?.connected
        ? catalog.data.loras
          .filter((name) => catalog.data?.families?.loras?.[name] === draft.family)
          .map((name) => ({ name }))
        : undefined;
  const modelCatalog = draft.service === 'pixai' ? pixai.data?.models
    : draft.service === 'comfyui' ? comfyModelOptions(catalog.data, draft.family)
      : undefined;
  const selectedModels = parseModelPool(draft.models);
  const models = draft.service === 'comfyui' ? resolveComfyModels(selectedModels, catalog.data) : selectedModels;
  const usesModelCatalog = draft.service === 'comfyui' || draft.service === 'pixai';
  const validModelPool = !usesModelCatalog || models.length === 0 ||
    (models.length <= MODEL_POOL_LIMIT && !!modelCatalog && models.every((model) => modelCatalog.some(({ id }) => id === model)));
  const maxLoras = loraLimit(draft.service, pixai.data?.max_loras);
  const selection = effectiveRules(pool, maxLoras);
  const sessions = useQuery({
    queryKey: ['explorer-sessions'],
    queryFn: () => get<{ sessions: ExplorerSummary[] }>(`${base}/sessions`),
    refetchInterval: active ? 5000 : false,
  });
  const query = useQuery({
    queryKey: ['explorer-session', id],
    queryFn: () => get<ExplorerSession>(`${base}/sessions/${id}`),
    enabled: !!id,
    refetchInterval: active ? 1500 : false,
  });
  const session = query.data;
  const queue = useQuery({
    queryKey: ['activity'],
    queryFn: () => get<{ items: Activity[] }>('/api/activity'),
    enabled: !!id && active,
    refetchInterval: active ? 1500 : false,
  });
  useUnsaved('style-explorer', dirty);
  useEffect(() => {
    const c = catalog.data;
    if (!c?.connected) return;
    setDraft((current) => {
      const settings = { ...current.settings };
      let changed = false;
      for (const family of ['anima', 'sdxl']) {
        const key = `comfyui:${family}`;
        if (settings[key]?.model) continue;
        const model =
          c.models.find((m) => c.families?.models?.[m] === family) ??
          c.models.find((m) => (family === 'sdxl' ? m.startsWith('checkpoint::') : !m.startsWith('checkpoint::')));
        if (!model) continue;
        settings[key] = { ...c.defaults, ...settings[key], family, model };
        changed = true;
      }
      return changed ? { ...current, settings } : current;
    });
  }, [catalog.data]);
  useEffect(() => {
    try {
      if (!dirty && !storedDraft(workId)) return;
      localStorage.setItem(EXPLORER_DRAFT_KEY, JSON.stringify(draft));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [draft, dirty, workId]);
  const requestId = (key: string) => requests.current[key] ?? (requests.current[key] = crypto.randomUUID());
  const accept = (s: ExplorerSession) => {
    qc.setQueryData(['explorer-session', s.id], s);
    void qc.invalidateQueries({ queryKey: ['explorer-sessions'] });
  };
  async function mutation(
    action: string,
    values: Record<string, unknown> = {},
    target = session,
  ): Promise<ExplorerSession | undefined> {
    if (!target || busy) return;
    setBusy(true);
    setError('');
    const key = `${target.id}:${action}:${JSON.stringify(values)}`;
    try {
      const s = await post<ExplorerSession>(`${base}/sessions/${target.id}/${action}`, {
        revision: target.revision,
        request_id: requestId(key),
        ...values,
      });
      delete requests.current[key];
      accept(s);
      return s;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        delete requests.current[key];
        await qc.invalidateQueries({
          queryKey: ['explorer-session', target.id],
        });
        setError(t('style_explorer.stale'));
      } else setError(e instanceof ApiError ? tm(e.msg) : msgText(e));
    } finally {
      setBusy(false);
    }
  }
  // Pair creation changes persisted state but never requests generation. Attempt once per observed revision and ready-image pool.
  useEffect(() => {
    if (
      !active ||
      busy ||
      !session ||
      (session.pair &&
        [session.pair.a, session.pair.b].every((id) =>
          session.candidates.some((c) => c.id === id && c.status === 'done' && c.image_url && !c.image_missing),
        )) ||
      (!session.pair && session.candidates.filter((c) => c.status === 'done' && !!c.image_url).length < 2)
    )
      return;
    const key = `${session.id}:${session.revision}:${session.candidates
      .filter((c) => c.status === 'done' && !!c.image_url)
      .map((c) => c.id)
      .join(',')}`;
    if (pairAttempt.current === key) return;
    pairAttempt.current = key;
    void mutation('pair');
  }, [session, active, busy]);
  async function start() {
    if (busy || !active || !valid || !capabilities.data || serviceUnavailable) return;
    setConfirm(false);
    setBusy(true);
    setError('');
    let created: ExplorerSession | undefined;
    try {
      const { loras: _loras, ...settings } = {
        ...(draft.service === 'novelai'
          ? novelai.data?.defaults
          : draft.service === 'pixai'
            ? pixai.data?.defaults
            : {}),
        ...draft.settings[settingsKey(draft)],
      };
      const config: Omit<ExplorerConfig, 'request_id'> = {
        name: draft.name.trim(),
        service: draft.service,
        family: draft.service === 'comfyui' ? draft.family : draft.service,
        positive: draft.positive,
        negative: draft.negative,
        seed: draft.seed,
        settings: usesModelCatalog && models.length ? { ...settings, model: models[0] } : settings,
        materials: requestMaterials(pool, availableLoras),
        models,
        rules: selection,
        budget: draft.budget,
      };
      const key = 'create:' + JSON.stringify(config);
      created = await post<ExplorerSession>(`${base}/sessions`, { ...config, request_id: requestId(key) });
      delete requests.current[key];
      accept(created);
      setId(created.id);
      setStage('compare');
      setDirty(false);
      setCount(draft.count);
      const generateKey = `${created.id}:generate:${JSON.stringify({ count: draft.count })}`;
      const generated = await post<ExplorerSession>(`${base}/sessions/${created.id}/generate`, {
        revision: created.revision,
        request_id: requestId(generateKey),
        count: draft.count,
      });
      delete requests.current[generateKey];
      accept(generated);
    } catch (e) {
      setError(e instanceof ApiError ? tm(e.msg) : msgText(e));
      if (created)
        setError(`${t('style_explorer.created_generate_failed')} ${e instanceof ApiError ? tm(e.msg) : msgText(e)}`);
    } finally {
      setBusy(false);
    }
  }
  const ready = session?.candidates.filter((c) => c.status === 'done' && !!c.image_url).length ?? 0;
  const limit = capabilities.data?.max_batch ?? 16;
  const valid =
    draft.name.trim() &&
    draft.positive.trim() &&
    Number.isInteger(draft.count) &&
    draft.count >= 2 &&
    draft.count <= limit &&
    draft.budget >= draft.count &&
    draft.budget <= (capabilities.data?.max_budget ?? 200) &&
    Number.isInteger(draft.seed) &&
    draft.seed >= -1 &&
    draft.seed <= (draft.service === 'pixai' ? 2 ** 31 - 1 : 2 ** 32 - 1) &&
    Number.isInteger(draft.budget) &&
    validModelPool &&
    pool.tags.items.length + pool.loras.items.length <= 10_000 &&
    (!pool.tags.items.length || validWeight(pool.tags, 10)) &&
    (!pool.loras.items.length || (validWeight(pool.loras, loraWeightLimit(draft.service)) &&
      pool.loras.items.every((lora) => !!findLora(lora, availableLoras)))) &&
    [selection.artist_min, selection.artist_max, selection.lora_min, selection.lora_max].every(Number.isInteger);
  const serviceUnavailable = capabilities.data?.services.find((s) => s.id === draft.service)?.enabled === false;
  const configured = services.data?.services.find((s) => s.id === draft.service);
  return (
    <div className="pad col style-explorer">
      <h3>{t('image_menu.explorer')}</h3>
      <nav className="row" aria-label={t('style_explorer.stages')}>
        {(['setup', 'compare', 'ranking'] as const).map((step) => (
          <button
            key={step}
            className={stage === step ? 'selected' : 'ghost'}
            disabled={(step !== 'setup' && !session) || (step === 'ranking' && !session?.votes.length)}
            onClick={() => setStage(step)}
          >
            {t(`style_explorer.${step}`)}
          </button>
        ))}
      </nav>
      <details>
        <summary>{t('style_explorer.sessions')}</summary>
        <div className="col">
          {sessions.data?.sessions.map((s) => (
            <button
              className="ghost"
              key={s.id}
              onClick={() => {
                setId(s.id);
                setStage('compare');
                setError('');
              }}
            >
              {s.name} · {s.service} · {s.candidate_count} / {s.vote_count}
            </button>
          ))}
          {!sessions.data?.sessions.length && <p>{t('style_explorer.no_sessions')}</p>}
        </div>
      </details>
      {(error || query.error || capabilities.error || sessions.error) && (
        <p className="warn-text" role="alert">
          {error || msgText(query.error || capabilities.error || sessions.error)}
        </p>
      )}
      {storageError && <p className="warn-text">{t('style_explorer.storage_failed')}</p>}
      {stage === 'setup' && (
        <>
          <ExplorerSetup
            draft={draft}
            setDraft={(d) => {
              setDraft(d);
              setDirty(true);
            }}
            capabilities={capabilities.data}
            loras={availableLoras}
            models={models}
            modelCatalog={modelCatalog}
            loraLimit={maxLoras}
            openSettings={openSettings}
          />
          {configured && !configured.connected && (
            <p className="warn-text">
              {t('style_explorer.service_unavailable')}{' '}
              <button onClick={openSettings}>{t('style_explorer.open_settings')}</button>
            </p>
          )}
          <button
            className="primary"
            disabled={!active || busy || !valid || !capabilities.data || serviceUnavailable}
            onClick={() => {
              setRetryCandidate('');
              setConfirm(true);
            }}
          >
            {t('style_explorer.review_generate')}
          </button>
        </>
      )}
      {stage !== 'setup' && session && (
        <>
          <h4>{session.name}</h4>
          <div className="row">
            <button onClick={() => openView('queue')}>{t('image_menu.queue')}</button>
            {queue.data?.items?.some(item => item.kind === 'image_queue' && item.paused) && <span className="warn-text">{t('queue.paused')}</span>}
          </div>
          <p>
            {t('style_explorer.progress', {
              ready,
              total: session.candidates.length,
              used: session.used,
              budget: session.budget,
            })}
          </p>
          <p className="faint">{t('style_explorer.fixed_settings')}</p>
          <div className="row">
            <label>
              {t('style_explorer.count')}{' '}
              <input
                type="number"
                min={1}
                max={Math.min(limit, session.budget - session.used)}
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
              />
            </label>
            <button
              className="primary"
              disabled={
                busy ||
                running(session) ||
                !Number.isInteger(count) ||
                count < 1 ||
                count > limit ||
                count > session.budget - session.used
              }
              onClick={() => {
                setRetryCandidate('');
                setConfirm(true);
              }}
            >
              {t('style_explorer.generate_more')}
            </button>
            <button disabled={busy || !running(session)} onClick={() => void mutation('cancel')}>
              {t('style_explorer.cancel')}
            </button>
            <button disabled={busy || !session.votes.length} onClick={() => void mutation('undo')}>
              {t('style_explorer.undo')}
            </button>
          </div>
          {!session.pair && ready >= 2 && <button disabled={busy} onClick={() => void mutation('pair')}>{t('style_explorer.compare')}</button>}
          {session.used >= session.budget && <p>{t('style_explorer.exhausted')}</p>}
          {!ready && !running(session) && <p>{t('style_explorer.no_images')}</p>}
          {stage === 'compare' && (
            <ExplorerCompare
              session={session}
              busy={busy}
              active={active && !confirm}
              vote={(result: ExplorerResult) => void mutation('vote', { pair_id: session.pair?.id, result })}
            />
          )}
          {stage === 'ranking' && (
            <>
              <p>
                {t('style_explorer.ranking_about', {
                  votes: session.votes.length,
                  seeds: new Set(session.candidates.filter((c) => c.matches > 0).map((c) => c.seed)).size,
                })}
              </p>
              {session.ranking.map((c, i) => (
                <article className="explorer-ranking row" key={c.id}>
                  {c.image_url && <img src={c.image_url} alt={`${i + 1}`} />}
                  <div className="col grow">
                    <strong>#{i + 1}</strong>
                    <span>
                      {t('style_explorer.statistics', {
                        elo: Math.round(c.elo),
                        matches: c.matches,
                        wins: c.wins,
                        draws: c.draws,
                        rejected: c.rejected,
                        seed: c.seed,
                      })}
                    </span>
                    <label>
                      {t('style_explorer.preset_name')}{' '}
                      <input
                        value={presetNames[c.id] ?? ''}
                        onChange={(e) =>
                          setPresetNames({
                            ...presetNames,
                            [c.id]: e.target.value,
                          })
                        }
                      />
                    </label>
                    <button
                      disabled={busy || !presetNames[c.id]?.trim() || !c.image_url}
                      onClick={async () => {
                        if (busy) return;
                        setBusy(true);
                        setError('');
                        const key = `preset:${c.id}:${presetNames[c.id]}`;
                        try {
                          const r = await post<{
                            session: ExplorerSession;
                            preset_id: string;
                          }>(`${base}/sessions/${session.id}/preset`, {
                            revision: session.revision,
                            request_id: requestId(key),
                            candidate_id: c.id,
                            name: presetNames[c.id].trim(),
                          });
                          delete requests.current[key];
                          accept(r.session);
                          await qc.invalidateQueries({
                            queryKey: ['image-presets'],
                          });
                        } catch (e) {
                          if (e instanceof ApiError && e.status === 409) {
                            delete requests.current[key];
                            await query.refetch();
                            setError(t('style_explorer.stale'));
                          } else setError(e instanceof ApiError ? tm(e.msg) : msgText(e));
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      {c.preset_id ? t('style_explorer.saved') : t('style_explorer.save_preset')}
                    </button>
                  </div>
                </article>
              ))}
              <button onClick={() => openView('presets')}>{t('style_explorer.open_presets')}</button>
            </>
          )}
          <details>
            <summary>{t('style_explorer.jobs')}</summary>
            {session.candidates.map((c) => (
              <div className="row" key={c.id}>
                <span>
                  #{c.index} · {t(`queue.status.${c.status}`)}
                </span>
                {!!c.error && <span className="warn-text">{msgText(c.error)}</span>}
                {['failed', 'cancelled', 'interrupted'].includes(c.status) && (
                  <button
                    disabled={busy || session.used >= session.budget}
                    onClick={() => {
                      setRetryCandidate(c.id);
                      setConfirm(true);
                    }}
                  >
                    {t('style_explorer.retry')}
                  </button>
                )}
              </div>
            ))}
          </details>
        </>
      )}
      {confirm && (
        <div className="overlay" style={{ zIndex: 200 }} onClick={e => { if (e.target === e.currentTarget) setConfirm(false); }} onKeyDown={e => {
          if (e.key === 'Escape') { e.preventDefault(); setConfirm(false); }
          if (e.key === 'Tab') {
            const buttons = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button')];
            const first = buttons[0], last = buttons[buttons.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
          }
        }}>
        <div
          className="explorer-confirm"
          role="dialog"
          aria-modal="true"
          aria-label={t('style_explorer.confirm_title')}
        >
          <h4>{t('style_explorer.confirm_title')}</h4>
          <p>
            {t('style_explorer.confirm_generate', {
              count: retryCandidate ? 1 : stage === 'setup' ? draft.count : count,
              budget: stage === 'setup' ? draft.budget : session?.budget,
            })}
          </p>
          <p>{t('style_explorer.charges')}</p>
          <div className="row">
            <button
              className="primary"
              disabled={!active || busy || (stage === 'setup' && (!valid || !capabilities.data || serviceUnavailable))}
              onClick={() => {
                if (stage === 'setup') void start();
                else {
                  setConfirm(false);
                  if (retryCandidate) void mutation('retry', { candidate_id: retryCandidate });
                  else void mutation('generate', { count });
                }
              }}
            >
              {t('style_explorer.confirm_action')}
            </button>
            <button autoFocus onClick={() => setConfirm(false)}>{t('style_explorer.back')}</button>
          </div>
        </div>
        </div>
      )}
      <button
        className="ghost"
        disabled={busy}
        onClick={() => {
          setStage('setup');
          setId('');
        }}
      >
        {t('style_explorer.new_session')}
      </button>
    </div>
  );
}


