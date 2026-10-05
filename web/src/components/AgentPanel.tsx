import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, askConsent, del, get, patch, post } from '../api';
import { t, tm } from '../i18n';
import { splitAnswer } from '../lib/agentText';
import type { TreeEntry } from '../types';
import MessageMarkdown from './MessageMarkdown';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import { useToast } from './Toasts';
import { Icon } from './icons';
import { Dialog } from './ui';

// Agent panel (11-agent, decision 0021): conversations led by a mode guideline. Answers propose whole files, which go to
// the review tab as drafts; nothing here writes a file.

export type Attachment = { path: string; from?: number; to?: number; text?: string };
type Mode = { id: string; name: string; description: string; scope: 'file' | 'work'; order: number; source: string | null };
type Scope = { kind: 'file' | 'paths' | 'work'; paths: string[] };
type Proposal = {
  n: number;
  path: string;
  new: boolean;
  truncated: boolean;
  warnings: string[];
  rejected: string | null;
  lines_before: number;
  lines_after: number;
  draft_id?: string;
  draft_status?: 'pending' | 'applied' | 'discarded' | null;
};
type Turn = {
  turn: number;
  role: 'user' | 'assistant';
  text: string;
  attachments?: Attachment[];
  proposals?: Proposal[];
  finish_reason?: string | null;
  error?: { key: string; text: string };
  model?: { provider: string; name: string };
};
type Session = { id: string; mode: string; title: string; scope: Scope; turns: Turn[] };
type SessionBrief = { id: string; mode: string; title: string; turns: number; updated_at: string | null };
type GuidelineRead = { name: string; tokens: number; missing?: boolean };
type Summary = { files: number; tokens: number; budget: number; omitted: string[]; history_dropped: number; guidelines?: GuidelineRead[] };
type Live = { text: string; thinking: number; waiting?: string; context?: Summary; error?: string; done: boolean };

const lastKey = (workId: string) => `atelierx-agent-session-${workId}`;
const remember = (workId: string, sid: string | null) => {
  try {
    if (sid) localStorage.setItem(lastKey(workId), sid);
    else localStorage.removeItem(lastKey(workId));
  } catch {
    /* storage may be unavailable */
  }
};
const recall = (workId: string) => {
  try {
    return localStorage.getItem(lastKey(workId));
  } catch {
    return null;
  }
};

function flatten(entries: TreeEntry[]): TreeEntry[] {
  return entries.flatMap((e) => (e.type === 'folder' ? flatten(e.children ?? []) : e.type === 'item' ? [e] : []));
}

export default function AgentPanel({
  workId,
  activePath,
  openDraft,
  attach,
  onAttached,
}: {
  workId: string;
  activePath: string | null;
  openDraft: (draft: string) => void;
  attach: Attachment | null;
  onAttached: () => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const modes = useQuery<Mode[]>({ queryKey: ['agent-modes', workId], queryFn: () => get(`/api/works/${workId}/agent/modes`) });
  const sessions = useQuery<SessionBrief[]>({ queryKey: ['agent-sessions', workId], queryFn: () => get(`/api/works/${workId}/agent/sessions`) });
  const [sid, setSid] = useState<string | null>(() => recall(workId));
  const [picking, setPicking] = useState(false);
  const known = sessions.data?.some((s) => s.id === sid);
  const session = useQuery<Session>({
    queryKey: ['agent-session', workId, sid],
    queryFn: () => get(`/api/works/${workId}/agent/sessions/${sid}`),
    enabled: !!sid && !!known,
  });
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  const [live, setLive] = useState<Live | null>(null);
  const [preview, setPreview] = useState<Summary | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const log = useRef<HTMLDivElement>(null);

  // One answer at a time: while it streams the conversation cannot change (stop it first). Leaving the work or closing
  // the panel stops it; the server keeps what came so far as a stopped answer.
  const streaming = live !== null;
  useEffect(() => () => abort.current?.abort(), [workId]);

  const choose = (next: string | null) => {
    if (abort.current) return;
    setSid(next);
    remember(workId, next);
    setLive(null);
    setPicking(false);
  };

  // Ctrl+L in the editor sends a selection here.
  useEffect(() => {
    if (!attach) return;
    setAttachments((all) => [...all.filter((a) => !(a.path === attach.path && a.from === attach.from && a.to === attach.to)), attach]);
    onAttached();
  }, [attach]); // eslint-disable-line react-hooks/exhaustive-deps

  // What the next message would send, shortly after typing stops.
  useEffect(() => {
    if (!session.data) return;
    const timer = setTimeout(() => {
      post<Summary>(`/api/works/${workId}/agent/sessions/${session.data!.id}/preview`, { message: input, attachments, llm })
        .then(setPreview)
        .catch(() => setPreview(null));
    }, 400);
    return () => clearTimeout(timer);
  }, [session.data, input, attachments, llm, workId]);

  useEffect(() => {
    log.current?.scrollTo(0, log.current.scrollHeight);
  }, [session.data?.turns.length, live?.text]);

  async function start(mode: Mode) {
    const scope: Scope = mode.scope === 'work' || !activePath ? { kind: 'work', paths: [] } : { kind: 'file', paths: [activePath] };
    const created = await post<Session>(`/api/works/${workId}/agent/sessions`, { mode: mode.id, scope });
    qc.setQueryData(['agent-session', workId, created.id], created);
    await qc.invalidateQueries({ queryKey: ['agent-sessions', workId] });
    choose(created.id);
  }

  async function send() {
    const message = input.trim();
    if (!message || !session.data || live) return;
    const url = `/api/works/${workId}/agent/sessions/${session.data.id}/send`;
    const controller = new AbortController();
    abort.current = controller;
    let state: Live = { text: '', thinking: 0, done: false };
    setLive(state);
    setInput('');
    const sent = attachments;
    setAttachments([]);
    // Show the question at once; the stored conversation replaces it when the answer ends.
    qc.setQueryData<Session>(['agent-session', workId, session.data.id], (old) =>
      old ? { ...old, turns: [...old.turns, { turn: old.turns.length + 1, role: 'user', text: message, attachments: sent }] } : old,
    );
    try {
      const request = () =>
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, attachments: sent, llm }),
          signal: controller.signal,
        });
      let response = await request();
      if (response.status === 428) {
        const error = (await response.json()).error;
        if (!(await askConsent(error, url))) throw new Error(tm(error));
        response = await request();
      }
      if (!response.ok) {
        const error = (await response.json().catch(() => null))?.error;
        throw new Error(error ? tm(error) : response.statusText);
      }
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop()!;
        for (const raw of events) {
          const type = /event: (\w+)/.exec(raw)?.[1];
          const data = /data: (.*)/s.exec(raw)?.[1];
          if (!type || data === undefined) continue;
          if (type === 'context') state = { ...state, context: JSON.parse(data) };
          if (type === 'thinking') state = { ...state, thinking: Number(data) };
          if (type === 'waiting') state = { ...state, waiting: tm(JSON.parse(data)) };
          if (type === 'delta') state = { ...state, text: state.text + JSON.parse(data) };
          if (type === 'error') state = { ...state, error: tm(JSON.parse(data)) };
          if (type === 'end') state = { ...state, done: true };
          setLive(state);
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setInput(message);
        setAttachments(sent);
        toast({ text: String((err as Error).message ?? err), tone: 'error' });
      }
    } finally {
      await qc.invalidateQueries({ queryKey: ['agent-session', workId, session.data.id] });
      qc.invalidateQueries({ queryKey: ['agent-sessions', workId] });
      // Only the request still in charge clears the shared state.
      if (abort.current === controller) {
        abort.current = null;
        setLive(null);
      }
    }
  }

  async function review(turn: number, n: number) {
    try {
      const { draft_id } = await post<{ draft_id: string }>(`/api/works/${workId}/agent/sessions/${session.data!.id}/proposals/${turn}/${n}/review`);
      qc.invalidateQueries({ queryKey: ['agent-session', workId, session.data!.id] });
      qc.invalidateQueries({ queryKey: ['drafts', workId] });
      openDraft(draft_id);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  async function remove() {
    if (!session.data || !confirm(t('agent.delete_confirm', { title: session.data.title || t('agent.untitled') }))) return;
    await del(`/api/works/${workId}/agent/sessions/${session.data.id}`);
    await qc.invalidateQueries({ queryKey: ['agent-sessions', workId] });
    choose(null);
  }

  async function rename() {
    if (!session.data) return;
    const title = prompt(t('agent.rename_prompt'), session.data.title);
    if (title === null) return;
    qc.setQueryData(['agent-session', workId, session.data.id], await patch(`/api/works/${workId}/agent/sessions/${session.data.id}`, { title }));
    qc.invalidateQueries({ queryKey: ['agent-sessions', workId] });
  }

  async function setScope(scope: Scope) {
    if (!session.data) return;
    qc.setQueryData(['agent-session', workId, session.data.id], await patch(`/api/works/${workId}/agent/sessions/${session.data.id}`, { scope }));
    setScopeOpen(false);
  }

  const modeName = (id: string) => modes.data?.find((m) => m.id === id)?.name ?? id;
  const showPicker = picking || !sid || (sessions.data && !known);

  return (
    <div className="agent">
      <div className="row agent-head">
        <select
          className="grow"
          disabled={streaming}
          title={streaming ? t('agent.stop_to_switch') : undefined}
          value={showPicker ? '' : (sid ?? '')}
          onChange={(e) => (e.target.value ? choose(e.target.value) : setPicking(true))}
        >
          <option value="">{t('agent.new_conversation')}</option>
          {(sessions.data ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.title || t('agent.untitled')} · {modeName(s.mode)}
            </option>
          ))}
        </select>
        {!showPicker && session.data && (
          <>
            <button className="ghost icon-button" title={t('agent.rename')} aria-label={t('agent.rename')} onClick={rename}>
              <Icon name="edit" size={16} />
            </button>
            <button className="ghost icon-button" title={t('common.delete')} aria-label={t('common.delete')} disabled={streaming} onClick={remove}>
              <Icon name="trash" size={16} />
            </button>
          </>
        )}
      </div>

      {showPicker ? (
        <div className="agent-modes">
          <p className="faint small">{t('agent.pick_mode')}</p>
          {(modes.data ?? []).map((m) => (
            <button key={m.id} className="agent-mode" onClick={() => start(m)}>
              <strong>{m.name}</strong>
              {m.description && <span className="faint small">{m.description}</span>}
              <span className="badge plain">{t(m.scope === 'work' ? 'agent.scope_work' : 'agent.scope_file_short')}</span>
            </button>
          ))}
          <p className="faint small">{t('agent.modes_from_guidelines')}</p>
        </div>
      ) : session.data ? (
        <>
          <div className="row agent-scope">
            <span className="faint small">{t('agent.scope')}</span>
            <button className="chip" onClick={() => setScopeOpen(true)} disabled={!!live}>
              {session.data.scope.kind === 'work'
                ? t('agent.scope_work')
                : session.data.scope.paths.length
                  ? session.data.scope.paths.map((p) => p.split('/').pop()).join(', ')
                  : t('agent.scope_none')}
            </button>
            <span className="faint small grow" style={{ textAlign: 'right' }}>
              {modeName(session.data.mode)}
            </span>
          </div>
          <div className="agent-log" ref={log}>
            {session.data.turns.length === 0 && !live && <div className="faint small">{t('agent.first_hint')}</div>}
            {session.data.turns.map((turn) => (
              <TurnView key={turn.turn} turn={turn} onReview={(n) => review(turn.turn, n)} openDraft={openDraft} />
            ))}
            {live && (
              <div className="agent-turn assistant">
                {live.text ? <AnswerView text={live.text} proposals={null} onReview={() => undefined} openDraft={openDraft} streaming /> : null}
                {!live.text && <span className="faint small">{live.thinking ? t('test.thinking', { n: live.thinking }) : live.waiting ? t('test.waiting_gpu', { name: live.waiting }) : t('agent.waiting')}</span>}
                {live.error && <div className="error-text">{live.error}</div>}
              </div>
            )}
          </div>
          <div className="agent-input">
            {attachments.length > 0 && (
              <div className="row wrap">
                {attachments.map((a, n) => (
                  <span key={n} className="chip" title={a.text}>
                    {a.path.split('/').pop()}
                    {a.from ? `:${a.from}-${a.to}` : ''}
                    <button className="ghost" onClick={() => setAttachments(attachments.filter((_, k) => k !== n))} aria-label={t('common.delete')}>
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            {preview && (
              <div className={`small ${preview.tokens > preview.budget ? 'warn-text' : 'faint'}`}>
                {t('agent.budget', { files: preview.files, tokens: preview.tokens.toLocaleString(), budget: preview.budget.toLocaleString() })}
                {preview.omitted.length > 0 && <span className="warn-text"> · {t('agent.omitted', { n: preview.omitted.length })}</span>}
                {!!preview.guidelines?.length && (
                  <div title={t('agent.guidelines_help')}>
                    {t('agent.guidelines')}{' '}
                    {preview.guidelines.map((g, n) => (
                      <span key={g.name} className={g.missing ? 'warn-text' : undefined}>
                        {n > 0 && ' · '}
                        {g.missing ? t('agent.guideline_missing', { name: g.name }) : `${g.name} (${g.tokens.toLocaleString()})`}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
            <textarea
              rows={3}
              value={input}
              placeholder={t('agent.input_hint')}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="row">
              <button
                className="ghost small"
                onClick={() => activePath && setAttachments([...attachments.filter((a) => a.path !== activePath || a.from), { path: activePath }])}
                disabled={!activePath}
                title={t('agent.attach_file_hint')}
              >
                + {t('agent.attach_file')}
              </button>
              <span className="grow" />
              {live ? (
                <button onClick={() => abort.current?.abort()}>{t('test.stop')}</button>
              ) : (
                <button className="primary" onClick={send} disabled={!input.trim()}>
                  {t('agent.send')}
                </button>
              )}
            </div>
            <details className="agent-llm">
              <summary className="faint small">{t('agent.connection')}</summary>
              <RunLlmSelector task="agent" value={llm} onChange={setLlm} disabled={!!live} />
            </details>
          </div>
        </>
      ) : (
        <div className="faint">…</div>
      )}
      {scopeOpen && session.data && (
        <ScopeDialog workId={workId} scope={session.data.scope} activePath={activePath} onSave={setScope} onClose={() => setScopeOpen(false)} />
      )}
    </div>
  );
}

function TurnView({ turn, onReview, openDraft }: { turn: Turn; onReview: (n: number) => void; openDraft: (draft: string) => void }) {
  if (turn.role === 'user') {
    return (
      <div className="agent-turn user">
        {(turn.attachments ?? []).length > 0 && (
          <div className="faint small">
            {turn.attachments!.map((a) => `${a.path.split('/').pop()}${a.from ? `:${a.from}-${a.to}` : ''}`).join(', ')}
          </div>
        )}
        <div style={{ whiteSpace: 'pre-wrap' }}>{turn.text}</div>
      </div>
    );
  }
  return (
    <div className="agent-turn assistant">
      <AnswerView text={turn.text} proposals={turn.proposals ?? []} onReview={onReview} openDraft={openDraft} />
      {turn.finish_reason === 'length' && <div className="warn-text small">{t('agent.cut_off')}</div>}
      {turn.finish_reason === 'stopped' && <div className="faint small">{t('test.stopped')}</div>}
      {turn.error && <div className="error-text">{tm(turn.error)}</div>}
    </div>
  );
}

function AnswerView({
  text,
  proposals,
  onReview,
  openDraft,
  streaming,
}: {
  text: string;
  proposals: Proposal[] | null;
  onReview: (n: number) => void;
  openDraft: (draft: string) => void;
  streaming?: boolean;
}) {
  return (
    <>
      {splitAnswer(text).map((part, k) =>
        part.kind === 'text' ? (
          <MessageMarkdown key={k} text={part.text} />
        ) : (
          <ProposalCard
            key={k}
            path={part.path}
            text={part.text}
            closed={part.closed}
            superseded={part.superseded}
            streaming={!!streaming && !part.closed}
            info={proposals?.find((p) => p.n === part.n) ?? null}
            onReview={() => onReview(part.n)}
            openDraft={openDraft}
          />
        ),
      )}
    </>
  );
}

function ProposalCard({
  path,
  text,
  closed,
  superseded,
  streaming,
  info,
  onReview,
  openDraft,
}: {
  path: string;
  text: string;
  closed: boolean;
  superseded: boolean;
  streaming: boolean;
  info: Proposal | null;
  onReview: () => void;
  openDraft: (draft: string) => void;
}) {
  const [shown, setShown] = useState(false);
  const lines = text.split('\n').length - (text.endsWith('\n') ? 1 : 0);
  const blocked = superseded || !closed || !!info?.rejected || !!info?.truncated || !!info?.warnings.some((w) => w === 'changed_since' || w === 'deleted_since');
  return (
    <div className={`proposal-card${superseded ? ' superseded' : ''}`}>
      <div className="row">
        <strong className="grow" title={path}>
          {path}
        </strong>
        {info?.new && <span className="badge">{t('agent.new_file')}</span>}
        {info?.draft_status === 'applied' && <span className="badge plain">{t('agent.card.applied')}</span>}
        {info?.draft_status === 'discarded' && <span className="badge plain">{t('agent.card.discarded')}</span>}
      </div>
      <div className="faint small">
        {streaming
          ? t('agent.writing', { n: lines })
          : info
            ? info.new
              ? t('agent.lines_new', { n: info.lines_after })
              : t('agent.lines', { before: info.lines_before, after: info.lines_after })
            : t('agent.lines_new', { n: lines })}
      </div>
      {superseded && <div className="faint small">{t('agent.superseded')}</div>}
      {!streaming && !closed && <div className="warn-text small">{t('agent.truncated')}</div>}
      {info?.rejected && <div className="warn-text small">{t(`agent.rejected.${info.rejected}`)}</div>}
      {(info?.warnings ?? []).map((w) => (
        <div key={w} className="warn-text small">
          {t(`agent.warning.${w}`)}
        </div>
      ))}
      {!streaming && (
        <div className="row">
          {info?.draft_id ? (
            <button onClick={() => openDraft(info.draft_id!)}>{t('agent.open_review')}</button>
          ) : (
            <button className="primary" disabled={blocked || !info} onClick={onReview}>
              {t('agent.to_review')}
            </button>
          )}
          <button className="ghost" onClick={() => setShown(!shown)}>
            {t(shown ? 'agent.hide_text' : 'agent.show_text')}
          </button>
        </div>
      )}
      {shown && <pre className="proposal-text">{text}</pre>}
    </div>
  );
}

function ScopeDialog({
  workId,
  scope,
  activePath,
  onSave,
  onClose,
}: {
  workId: string;
  scope: Scope;
  activePath: string | null;
  onSave: (scope: Scope) => void;
  onClose: () => void;
}) {
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const items = flatten(tree.data ?? []);
  const [kind, setKind] = useState<Scope['kind']>(scope.kind === 'work' ? 'work' : 'paths');
  const [picked, setPicked] = useState<Set<string>>(new Set(scope.kind === 'work' ? (activePath ? [activePath] : []) : scope.paths));
  return (
    <Dialog
      title={t('agent.scope_title')}
      onClose={onClose}
      actions={
        <button className="primary" disabled={kind !== 'work' && picked.size === 0} onClick={() => onSave(kind === 'work' ? { kind: 'work', paths: [] } : { kind: 'paths', paths: [...picked] })}>
          {t('common.save')}
        </button>
      }
    >
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="radio" checked={kind === 'work'} onChange={() => setKind('work')} /> {t('agent.scope_work')}
      </label>
      <label className="row" style={{ flexDirection: 'row' }}>
        <input type="radio" checked={kind !== 'work'} onChange={() => setKind('paths')} /> {t('agent.scope_pick')}
      </label>
      {kind !== 'work' && (
        <div className="scope-list">
          {items.map((item) => (
            <label key={item.path} className="row" style={{ flexDirection: 'row' }}>
              <input
                type="checkbox"
                checked={picked.has(item.path)}
                onChange={(e) => {
                  const next = new Set(picked);
                  if (e.target.checked) next.add(item.path);
                  else next.delete(item.path);
                  setPicked(next);
                }}
              />
              <span className="grow">{item.path}</span>
              {item.id && <span className="faint mono small">{item.id}</span>}
            </label>
          ))}
        </div>
      )}
      <p className="faint small">{t('agent.scope_note')}</p>
    </Dialog>
  );
}
