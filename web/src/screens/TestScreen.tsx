import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { askConsent, get, post, put } from '../api';
import { TestSetsDialog, type TestSet } from '../components/TestSets';
import { t, tm } from '../i18n';
import JsxPreview from '../components/JsxPreview';
import MessageMarkdown from '../components/MessageMarkdown';
import PersonaDialog, { usePersona } from '../components/PersonaDialog';
import RunLlmSelector, { type LlmOverride } from '../components/RunLlmSelector';
import type { TreeEntry, WorkInfo } from '../types';
import { replyNotes, splitReply, type ResponseRule } from '../lib/componentCalls';
import { replayInputs } from '../lib/replay';

type Context = {
  main: string | null;
  picked: { path: string; name: string; reason: string; keyword: string | null; size: number }[];
  skipped: { path: string; name: string; why: string }[];
  lorebook: { path: string; id: string | null; name: string; kind: string }[];
  components: { path: string; id: string | null; name: string }[];
  system: string;
  system_size: number;
};
type Turn = {
  role: 'user' | 'assistant';
  text: string;
  context?: Context;
  start?: boolean;
  thinking?: number;
  waiting?: string;
  error?: string;
  stopped?: boolean;
};
function flatten(entries: TreeEntry[]): TreeEntry[] {
  return entries.flatMap((e) => (e.type === 'folder' ? flatten(e.children ?? []) : [e]));
}


export default function TestScreen({ workId, openItem }: { workId: string; openItem: (path: string) => void }) {
  const info = useQuery<WorkInfo>({ queryKey: ['work', workId], queryFn: () => get(`/api/works/${workId}`) });
  const tree = useQuery<TreeEntry[]>({ queryKey: ['tree', workId], queryFn: () => get(`/api/works/${workId}/tree`) });
  const starts = flatten(tree.data ?? []).filter((e) => e.kind === 'start' && e.enabled !== false);
  const [slide, setSlide] = useState(0);
  const startEntry = slide < starts.length ? starts[slide] : null;
  const startItem = useQuery({
    queryKey: ['file', workId, startEntry?.path],
    queryFn: () => get(`/api/works/${workId}/file?path=${encodeURIComponent(startEntry!.path)}`),
    enabled: !!startEntry,
  });
  const personas = usePersona(workId);
  const persona = personas.persona;
  const [personaOpen, setPersonaOpen] = useState(false);
  const [setsOpen, setSetsOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [previousInputs, setPreviousInputs] = useState<string[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const abort = useRef<AbortController | null>(null);
  // Leaving the test screen stops the answer on its way and any resend still to come.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      abort.current?.abort();
    };
  }, []);
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  const [selected, setSelected] = useState<number | null>(null);
  const [rawShown, setRawShown] = useState<Set<number>>(new Set());
  const log = useRef<HTMLDivElement>(null);

  const started = turns.some((turn) => turn.role === 'user');
  const userName = persona?.name || '사용자';
  const startText = startEntry && startItem.data ? startItem.data.body.trim().replaceAll('{{user}}', userName) : null;
  // Before the first message the start situation is the bot's first turn; it follows the slide.
  const shown: Turn[] = started ? turns : startText ? [{ role: 'assistant', text: startText, start: true }] : [];

  const lastWithContext = [...shown.keys()].reverse().find((n) => shown[n].context);
  const focus = selected !== null && shown[selected]?.context ? selected : lastWithContext;
  const context = focus !== undefined ? shown[focus].context : undefined;
  const components = (context ?? shown.find((x) => x.context)?.context)?.components ?? flatten(tree.data ?? [])
    .filter((entry) => entry.kind === 'jsx' && entry.enabled !== false)
    .map((entry) => ({ path: entry.path, id: entry.id ?? null, name: entry.name.replace(/\.jsx$/i, '') }));
  const componentNames = components.map((c) => c.name);
  const rules = info.data?.effective.values.jsx ?? {};

  async function sendOne(message: string, history: Turn[], who: TestSet['persona'] = persona ? { name: persona.name, description: persona.description } : null) {
    const plain = history.map(({ role, text }) => ({ role, text }));
    let reply: Turn = { role: 'assistant', text: '' };
    setTurns([...history, { role: 'user', text: message }, reply]);
    const controller = new AbortController();
    abort.current = controller;
    try {
      const url = `/api/works/${workId}/chat/send`;
      const request = () =>
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ llm, history: plain, message, persona: who }),
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
          if (type === 'context') reply = { ...reply, context: JSON.parse(data) };
          if (type === 'thinking') reply = { ...reply, thinking: Number(data) };
          if (type === 'waiting') reply = { ...reply, waiting: tm(JSON.parse(data)) };
          if (type === 'delta') reply = { ...reply, text: reply.text + JSON.parse(data) };
          if (type === 'error') reply = { ...reply, error: tm(JSON.parse(data)) };
          setTurns([...history, { role: 'user', text: message }, reply]);
        }
        log.current?.scrollTo(0, log.current.scrollHeight);
      }
    } catch (err) {
      if (controller.signal.aborted) reply = { ...reply, stopped: true };
      else reply = { ...reply, error: String((err as Error).message ?? err) };
    } finally {
      abort.current = null;
    }
    reply = { ...reply, text: reply.text.trimEnd(), thinking: undefined, waiting: undefined };
    const next = [...history, { role: 'user' as const, text: message }, reply];
    setTurns(next);
    setSelected(null);
    return next;
  }

  async function send() {
    const message = input.trim();
    if (!message || busy) return;
    setInput('');
    setBusy(true);
    try {
      await sendOne(message, shown);
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    const mine = turns.filter((x) => x.role === 'user').map((x) => x.text);
    if (mine.length) setPreviousInputs(mine);
    setTurns([]);
    setSelected(null);
    setRawShown(new Set());
  }

  async function replay() {
    if (busy || !previousInputs.length) return;
    setBusy(true);
    try {
      const history: Turn[] = startText ? [{ role: 'assistant', text: startText, start: true }] : [];
      await replayInputs(previousInputs, history, sendOne, () => !alive.current);
    } finally {
      setBusy(false);
    }
  }

  // Run a saved test set (#50): a fresh conversation from its start situation and persona, every input in turn, each
  // answer written to the run record as it comes. Stopping, an error or leaving the screen ends it there.
  async function runSet(set: TestSet) {
    if (busy) return;
    if (!confirm(t('tests.run_confirm', { n: set.inputs.length, name: set.name }))) return;
    setSetsOpen(false);
    reset();
    setBusy(true);
    const recorded: { input: string; reply: string; error?: string }[] = [];
    let status: 'done' | 'stopped' | 'error' = 'done';
    let runId: string | null = null;
    try {
      const run = await post<{ id: string }>(`/api/works/${workId}/tests/runs`, { set_id: set.id, llm });
      runId = run.id;
      let history: Turn[] = [];
      if (set.start) {
        const start = await get<{ body: string }>(`/api/works/${workId}/file?path=${encodeURIComponent(set.start)}`).catch(() => null);
        const text = start?.body.trim().replaceAll('{{user}}', set.persona?.name || '사용자');
        if (text) history = [{ role: 'assistant', text, start: true }];
      }
      setTurns(history);
      for (const input of set.inputs) {
        if (!alive.current) {
          status = 'stopped';
          break;
        }
        history = await sendOne(input, history, set.persona);
        const last = history[history.length - 1];
        recorded.push({ input, reply: last.text, ...(last.error ? { error: last.error } : {}) });
        await put(`/api/works/${workId}/tests/runs/${run.id}`, { turns: recorded, status: 'running' });
        if (last.stopped || last.error) {
          status = last.stopped ? 'stopped' : 'error';
          break;
        }
      }
    } catch {
      status = 'error';
    } finally {
      if (runId) await put(`/api/works/${workId}/tests/runs/${runId}`, { turns: recorded, status }).catch(() => undefined);
      setBusy(false);
    }
  }

  // Calls inside code or in a form the rule cannot read are written in the reply but not drawn; say which.
  const focusText = focus !== undefined ? shown[focus].text.replace(/```[\s\S]*?(?:```|$)|`[^`\n]+`/g, ' ') : '';
  const called = new Set(splitReply(focusText, componentNames, rules.response).flatMap((s) => ('component' in s ? [s.component] : [])));
  const notes = focus !== undefined ? replyNotes(shown[focus].text, componentNames, rules.response) : { fenced: [], unreadable: [] };
  const picked = new Map(context?.picked.map((p) => [p.path, p]) ?? []);

  return (
    <div className="test-screen">
      <div className="test-bar">
        <strong>{t('test.title')}</strong>
        <RunLlmSelector task="chat_test" value={llm} onChange={setLlm} disabled={busy} />
        <button onClick={() => setPersonaOpen(true)} disabled={!personas.list} title={persona?.description || t('persona.none_hint')}>
          {t('persona.button', { name: persona ? persona.name || t('persona.unnamed') : t('persona.none') })} ▾
        </button>
        <button onClick={reset} disabled={busy}>
          {t('chat.new')}
        </button>
        <button onClick={replay} disabled={busy || started || !previousInputs.length} title={t('test.replay_hint')}>
          {t('test.replay', { n: previousInputs.length })}
        </button>
        <button onClick={() => setSetsOpen(true)} disabled={busy} title={t('tests.about')}>
          {t('tests.button')}
        </button>
      </div>
      {setsOpen && (
        <TestSetsDialog
          workId={workId}
          current={{
            start: startEntry?.path ?? null,
            persona: persona ? { name: persona.name, description: persona.description } : null,
            inputs: (started ? turns : []).filter((x) => x.role === 'user').map((x) => x.text).concat(started ? [] : previousInputs),
          }}
          onRun={runSet}
          onClose={() => setSetsOpen(false)}
        />
      )}
      {personaOpen && personas.list && (
        <PersonaDialog list={personas.list} selectedId={personas.selectedId} onChoose={personas.choose} onClose={() => setPersonaOpen(false)} />
      )}
      <div className="test-body">
        <div className="test-chat">
          <div className={`start-slider${started ? ' locked' : ''}`}>
            <button className="ghost" disabled={started || slide === 0} onClick={() => setSlide(slide - 1)}>
              ‹
            </button>
            <div className="grow">
              <div className="faint">
                {t('test.start')} {starts.length ? `${Math.min(slide + 1, starts.length + 1)}/${starts.length + 1}` : ''} ·{' '}
                {startEntry ? startEntry.name : t('test.no_start')}
                {started && ` · ${t('test.start_locked')}`}
              </div>
            </div>
            <button className="ghost" disabled={started || slide >= starts.length} onClick={() => setSlide(slide + 1)}>
              ›
            </button>
          </div>
          <div className="chat-log" ref={log}>
            {shown.length === 0 && <div className="empty">{t('chat.empty')}</div>}
            {shown.map((turn, n) => (
              <div
                key={n}
                className={`msg ${turn.role === 'user' ? 'user' : 'bot'}${n === focus ? ' focus' : ''}`}
                onClick={() => turn.context && setSelected(n)}
              >
                {turn.start && <div className="faint" style={{ fontSize: 11 }}>{t('test.start')}</div>}
                {turn.role === 'assistant' && !turn.text && turn.thinking !== undefined && (
                  <span className="faint">{t('test.thinking', { n: turn.thinking.toLocaleString() })}</span>
                )}
                {turn.role === 'assistant' && !turn.text && turn.thinking === undefined && !turn.error && !turn.stopped && busy && n === shown.length - 1 && (
                  <span className="faint">{turn.waiting ? t('test.waiting_gpu', { name: turn.waiting }) : t('test.waiting')}</span>
                )}
                {turn.role === 'assistant' && !rawShown.has(n) ? <Reply text={turn.text} workId={workId} components={components} rules={rules} /> : turn.text}
                {turn.error && <div className="error-text">{turn.error}</div>}
                {turn.stopped && <div className="faint">{t('test.stopped')}</div>}
                {turn.role === 'assistant' && turn.text && (
                  <div className="ctx-line">
                    <a
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const next = new Set(rawShown);
                        if (next.has(n)) next.delete(n);
                        else next.add(n);
                        setRawShown(next);
                      }}
                    >
                      {rawShown.has(n) ? t('test.rendered') : t('test.raw')}
                    </a>
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="row">
            <textarea
              className="grow"
              rows={2}
              value={input}
              placeholder={t('chat.input')}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            {busy ? (
              <button onClick={() => abort.current?.abort()}>{t('test.stop')}</button>
            ) : (
              <button className="primary" onClick={send}>
                {t('chat.send')}
              </button>
            )}
          </div>
        </div>
        <div className="test-side">
          <div className="section-title">{t('test.loaded')}</div>
          {!context && <div className="faint">{t('test.loaded_empty')}</div>}
          {context && (
            <>
              <div className="load-row on">
                ● <span className="grow">{t('kind.main')}</span>
                {context.main ? (
                  <a href="#" onClick={(e) => (e.preventDefault(), openItem(context.main!))}>
                    {context.main}
                  </a>
                ) : (
                  <span className="error-text">{t('test.no_main')}</span>
                )}
                <span className="faint">{t('test.always')}</span>
              </div>
              <div className="section-title">{t('kind.lorebook')}</div>
              {context.lorebook.map((item) => {
                const hit = picked.get(item.path);
                const skip = context.skipped.find((s) => s.path === item.path);
                return (
                  <div key={item.path} className={`load-row${hit ? ' on' : ''}`}>
                    {hit ? '●' : '○'}{' '}
                    <a href="#" className="grow" onClick={(e) => (e.preventDefault(), openItem(item.path))}>
                      {item.name}
                    </a>
                    <span className="faint">
                      {hit
                        ? hit.reason === 'always'
                          ? t('test.always')
                          : t('test.keyword', { k: hit.keyword })
                        : skip
                          ? t(`chat.skip.${skip.why}`)
                          : t('test.not_this_turn')}
                    </span>
                  </div>
                );
              })}
              {context.lorebook.length === 0 && <div className="faint">{t('chat.no_lore')}</div>}
              <div className="section-title">JSX</div>
              {context.components.map((c) => (
                <div key={c.path} className={`load-row${called.has(c.name) ? ' on' : ''}`}>
                  {called.has(c.name) ? '◆' : '◇'}{' '}
                  <a href="#" className="grow" onClick={(e) => (e.preventDefault(), openItem(c.path))}>
                    {c.name}
                  </a>
                  <span className={called.has(c.name) ? 'faint' : notes.fenced.includes(c.name) || notes.unreadable.includes(c.name) ? 'warn-text' : 'faint'}>
                    {called.has(c.name)
                      ? t('test.called')
                      : notes.fenced.includes(c.name)
                        ? t('test.called_in_code')
                        : notes.unreadable.includes(c.name)
                          ? t('test.called_unreadable')
                          : t('test.not_called')}
                  </span>
                </div>
              ))}
              {context.components.length === 0 && <div className="faint">{t('test.no_jsx')}</div>}
              <div className="faint" style={{ marginTop: 8 }}>
                {t('test.size', { size: context.system_size, n: context.picked.length })}
              </div>
              <p className="faint">{t('test.platform_note')}</p>
              <details>
                <summary>{t('chat.raw')}</summary>
                <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>
                  {context.system}
                </pre>
              </details>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

type Rules = { hooks?: string[]; globals?: { name: string; stub?: string }[]; response?: ResponseRule };

function Reply({ text, workId, components, rules }: { text: string; workId: string; components: Context['components']; rules: Rules }) {
  const names = components.map((c) => c.name);
  const notes = replyNotes(text, names, rules.response);
  return (
    <>
      <MessageMarkdown text={text} component={(raw) => {
        const segments = splitReply(raw.trim(), names, rules.response);
        if (!segments.some((segment) => 'component' in segment)) return null;
        return segments.map((segment, index) => 'component' in segment
          ? <ComponentCall key={index} workId={workId} path={components.find((c) => c.name === segment.component)!.path} name={segment.component} props={segment.attrs} rules={rules} />
          : <span key={index}>{segment.text}</span>);
      }} />
      {notes.fenced.length > 0 && <div className="warn-text small">{t('test.note_fenced', { names: notes.fenced.join(', ') })}</div>}
      {notes.unreadable.length > 0 && <div className="warn-text small">{t('test.note_unreadable', { names: notes.unreadable.join(', ') })}</div>}
    </>
  );
}

// A component call inside a reply, drawn with the work's current source in the sandboxed preview.
function ComponentCall({ workId, path, name, props, rules }: { workId: string; path: string; name: string; props: unknown; rules: Rules }) {
  const item = useQuery<{ body: string }>({
    queryKey: ['item', workId, path],
    queryFn: () => get(`/api/works/${workId}/file?path=${encodeURIComponent(path)}`),
  });
  if (!item.data) return null;
  return (
    <div className="component-call">
      <JsxPreview code={item.data.body} name={name} props={props} hooks={rules.hooks ?? []} globals={rules.globals ?? []} theme="inline" autoHeight />
    </div>
  );
}
