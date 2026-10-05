import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, del, get, post, q } from '../api';
import { t, tm } from '../i18n';
import RunLlmSelector, { type LlmOverride } from './RunLlmSelector';
import type { WorkInfo } from '../types';
import { findCalls, type ResponseRule } from '../lib/componentCalls';
import { createSaver } from '../lib/exampleSaver';
import CodeEditor from './CodeEditor';
import JsxPreview, { type PreviewCall } from './JsxPreview';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// An example is a call as a reply writes it (`<Name c='C001' />`); `legacy` ones were saved as JSON props, and
// `convert_error` marks an old JSON example that cannot be written as a call under the work's rule (`text` is the JSON).
type Example = { name: string; text: string; legacy?: boolean; convert_error?: boolean };

const WIDTHS = { narrow: 360, normal: 560, wide: undefined } as const;

// [미리보기·props] tab of a JSX item: live preview of the editor's current source for the calls in the preview input,
// read with the work's response rule exactly as a reply would be.
export default function JsxWorkbench({
  workId,
  jsxId,
  name,
  source,
  defaultProps,
  info,
  setDefault,
  openItem,
  onDirtyChange,
}: {
  workId: string;
  jsxId: string | undefined;
  name: string;
  source: string;
  defaultProps: string | undefined;
  info: WorkInfo;
  setDefault: (name: string) => void;
  openItem?: (path: string) => void;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const examples = useQuery<Example[]>({
    queryKey: ['jsx-props', workId, jsxId],
    queryFn: () => get(`/api/works/${workId}/jsx/${q(jsxId!)}/props`),
    enabled: !!jsxId,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [text, setText] = useState('');
  const [width, setWidth] = useState<keyof typeof WIDTHS>('normal');
  const [dark, setDark] = useState(false);
  const [calls, setCalls] = useState<PreviewCall[]>([]);
  const editing = useRef(false);
  // A save answer only ends editing when no newer edit came in meanwhile (lib/exampleSaver).
  const saver = useRef(
    createSaver(async (example, body) => {
      const response = await fetch(`/api/works/${workId}/jsx/${q(jsxId!)}/props/${q(example)}`, { method: 'PUT', body });
      if (!response.ok) throw new ApiError(response.status, (await response.json()).error);
      return response.json();
    }),
  ).current;
  const dirtyRef = useRef(onDirtyChange);
  dirtyRef.current = onDirtyChange;
  const [dialog, setDialog] = useState<'prompt' | null>(null);
  const usages = useQuery<{ path: string; elements: { raw: string; errors: string[] }[] }[]>({
    queryKey: ['jsx-usages', workId, jsxId],
    queryFn: () => get(`/api/works/${workId}/jsx/${q(jsxId!)}/usages`),
    enabled: !!jsxId,
  });

  const list = examples.data ?? [];
  const current = list.find((e) => e.name === selected) ?? list.find((e) => e.name === defaultProps) ?? list[0] ?? null;

  useEffect(() => {
    if (current && !editing.current) setText(current.text);
  }, [current?.name, current?.text]); // eslint-disable-line react-hooks/exhaustive-deps

  // Store the pending edit; true when nothing is left unsaved.
  async function flush(): Promise<boolean> {
    if (!saver.dirty) return true;
    if (!saver.job!.text.trim()) return false;
    try {
      const { saved, clean } = await saver.flush();
      if (clean) {
        editing.current = false;
        dirtyRef.current?.(false);
      }
      qc.setQueryData(['jsx-props', workId, jsxId], saved);
      return clean;
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
      return false;
    }
  }

  // Save the example shortly after the last keystroke.
  useEffect(() => {
    if (!saver.dirty) return;
    const timer = setTimeout(flush, 700);
    return () => clearTimeout(timer);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  // Leaving the tab (or the item) sends what is still unsaved.
  useEffect(
    () => () => {
      const job = saver.job;
      if (job?.text.trim()) {
        fetch(`/api/works/${workId}/jsx/${q(jsxId!)}/props/${q(job.name)}`, { method: 'PUT', body: job.text, keepalive: true });
      }
    },
    [workId, jsxId],
  );

  if (!jsxId) return <div className="pad muted">{t('jsx.need_id')}</div>;

  const rules: { hooks?: string[]; globals?: { name: string; stub?: string }[]; response?: ResponseRule } = info.effective.values.jsx ?? {};
  // An old JSON example that cannot become a call previews its JSON props until it is edited.
  const legacyProps = current?.convert_error && !editing.current ? parseJson(current.text) : undefined;
  const found = legacyProps !== undefined
    ? [{ name, raw: '', attrs: legacyProps as Record<string, unknown>, errors: [], index: 0 }]
    : findCalls(text, [name], rules.response);
  const format = rules.response?.attribute_format ?? 'json_lenient';

  async function create(base?: Example) {
    if (!(await flush())) return;
    const next = prompt(t('jsx.props_name_prompt'), base ? `${base.name}-2` : 'basic');
    if (!next) return;
    const response = await fetch(`/api/works/${workId}/jsx/${q(jsxId!)}/props/${q(next)}`, { method: 'PUT', body: base?.text ?? `<${name} />` });
    if (!response.ok) {
      toast({ text: tm((await response.json()).error), tone: 'error' });
      return;
    }
    qc.setQueryData(['jsx-props', workId, jsxId], await response.json());
    editing.current = false;
    setSelected(next);
  }

  return (
    <div className="jsx-bench">
      <div className="row jsx-bench-bar">
        <div className="seg">
          {(['narrow', 'normal', 'wide'] as const).map((w) => (
            <button key={w} className={width === w ? 'on' : ''} onClick={() => setWidth(w)}>
              {t(`jsx.width.${w}`)}
            </button>
          ))}
        </div>
        <div className="seg">
          <button className={!dark ? 'on' : ''} onClick={() => setDark(false)}>
            {t('jsx.light')}
          </button>
          <button className={dark ? 'on' : ''} onClick={() => setDark(true)}>
            {t('jsx.dark')}
          </button>
        </div>
        <span className="grow" />
        <button onClick={() => setDialog('prompt')}>{t('jsx.prompt_text')}</button>
      </div>
      <div className="jsx-bench-body">
        <div className={`jsx-stage${dark ? ' dark' : ''}`}>
          {list.length === 0 ? (
            <JsxPreview
              code={source}
              name={name}
              props={{}}
              hooks={rules.hooks ?? []}
              globals={rules.globals ?? []}
              theme={dark ? 'dark' : 'light'}
              width={WIDTHS[width]}
              onCall={(call) => setCalls((all) => [call, ...all].slice(0, 30))}
            />
          ) : found.length === 0 ? (
            <div className="empty">{t('jsx.no_calls_found', { name })}</div>
          ) : (
            // One preview per call, in order; several calls (or a whole reply) show stacked.
            found.map((call, n) => (
              <JsxPreview
                key={`${n}:${call.raw}`}
                code={source}
                name={name}
                props={call.attrs}
                hooks={rules.hooks ?? []}
                globals={rules.globals ?? []}
                theme={dark ? 'dark' : 'light'}
                width={WIDTHS[width]}
                autoHeight={found.length > 1}
                onCall={(c) => setCalls((all) => [c, ...all].slice(0, 30))}
              />
            ))
          )}
        </div>
        <div className="jsx-props">
          <div className="row">
            <strong>{t('jsx.examples')}</strong>
            <select
              value={current?.name ?? ''}
              onChange={async (e) => {
                const next = e.target.value;
                if (!(await flush())) return;
                editing.current = false;
                setSelected(next);
              }}
            >
              {list.map((e) => (
                <option key={e.name} value={e.name}>
                  {e.name}
                  {e.name === defaultProps ? ` · ${t('jsx.default')}` : ''}
                </option>
              ))}
            </select>
            <button onClick={() => create()} title={t('jsx.add')}>
              +
            </button>
            {current && (
              <>
                <button onClick={() => create(current)}>{t('jsx.duplicate')}</button>
                {current.name !== defaultProps && <button onClick={() => setDefault(current.name)}>{t('jsx.make_default')}</button>}
                <button
                  className="danger"
                  onClick={async () => {
                    if (!confirm(t('jsx.delete_confirm', { name: current.name }))) return;
                    // An edit still waiting for the deleted example must not bring it back.
                    if (saver.job?.name === current.name) {
                      saver.drop();
                      editing.current = false;
                      dirtyRef.current?.(false);
                    }
                    qc.setQueryData(['jsx-props', workId, jsxId], await del(`/api/works/${workId}/jsx/${q(jsxId)}/props/${q(current.name)}`));
                    setSelected(null);
                  }}
                >
                  {t('common.delete')}
                </button>
              </>
            )}
          </div>
          {list.length === 0 ? (
            <div className="empty">
              <p>{t('jsx.no_examples')}</p>
              <button onClick={() => create()}>{t('jsx.add')}</button>
            </div>
          ) : (
            <>
              <div className="faint small">{t('jsx.preview_input_hint', { name })}</div>
              <div className="jsx-json">
                <CodeEditor
                  key={current?.name}
                  value={text}
                  language="jsx"
                  onChange={(value) => {
                    editing.current = true;
                    saver.edit(current!.name, value);
                    dirtyRef.current?.(true);
                    setText(value);
                  }}
                />
              </div>
              {current?.legacy && (
                <div className={current.convert_error ? 'warn-text' : 'faint small'}>
                  {t(current.convert_error ? 'jsx.legacy_unconvertible' : 'jsx.legacy_example')}
                </div>
              )}
              <div className="section-title">{t('jsx.read_props', { format: t(`jsx.format.${format}`) })}</div>
              {found.length === 0 ? (
                <div className="warn-text">{t('jsx.no_calls_found', { name })}</div>
              ) : (
                found.map((call, n) => (
                  <div key={n} className="jsx-read">
                    {found.length > 1 && <div className="faint small">#{n + 1}</div>}
                    {Object.keys(call.attrs).length === 0 && <span className="faint">{t('jsx.no_props')}</span>}
                    {Object.entries(call.attrs).map(([key, value]) => (
                      <div key={key} className="mono small">
                        {key}: {JSON.stringify(value)}
                      </div>
                    ))}
                    {call.errors.map((error) => (
                      <div key={error} className="warn-text">
                        {error}
                      </div>
                    ))}
                  </div>
                ))
              )}
            </>
          )}
          <div className="section-title">{t('jsx.usages')}</div>
          {(usages.data ?? []).length === 0 ? (
            <div className="faint">{t('jsx.no_usages')}</div>
          ) : (
            (usages.data ?? []).map((u) => {
              const bad = u.elements.filter((e) => e.errors.length).length;
              return (
                <div key={u.path} className="row" style={{ gap: 4 }}>
                  <a href="#" onClick={(e) => (e.preventDefault(), openItem?.(u.path))}>
                    {u.path}
                  </a>
                  <span className={bad ? 'warn-text' : 'faint'}>
                    {t('jsx.usage_count', { n: u.elements.length })}
                    {bad ? ` · ${t('jsx.usage_bad', { n: bad })}` : ' ✓'}
                  </span>
                </div>
              );
            })
          )}
          <div className="section-title">{t('jsx.calls')}</div>
          {calls.length === 0 ? (
            <div className="faint">{t('jsx.no_calls')}</div>
          ) : (
            calls.map((c, n) => (
              <div key={n} className="mono" style={{ fontSize: 12 }}>
                {c.name}({c.args.map((a) => JSON.stringify(a)).join(', ')})
              </div>
            ))
          )}
        </div>
      </div>
      {dialog === 'prompt' && (
        <PromptTextDialog
          workId={workId}
          jsxId={jsxId}
          examples={list}
          propsOf={(example) => findCalls(example.text, [name], rules.response)[0]?.attrs ?? {}}
          initial={current?.name ?? null}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

function PromptTextDialog({
  workId,
  jsxId,
  examples,
  propsOf,
  initial,
  onClose,
}: {
  workId: string;
  jsxId: string;
  examples: Example[];
  propsOf: (example: Example) => Record<string, unknown>;
  initial: string | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const [example, setExample] = useState(initial ?? '');
  const [feedback, setFeedback] = useState('');
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  return (
    <Dialog
      title={t('jsx.prompt_text')}
      onClose={onClose}
      actions={
        <button
          className="primary"
          onClick={async () => {
            try {
              const chosen = examples.find((e) => e.name === example);
              const props = chosen ? propsOf(chosen) : {};
              await post(`/api/works/${workId}/jsx/${q(jsxId)}/prompt-text`, { props, feedback, llm });
              toast({ text: t('jsx.prompt_started') });
              onClose();
            } catch (err) {
              toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
            }
          }}
        >
          {t('jsx.prompt_run')}
        </button>
      }
    >
      <label>
        {t('jsx.prompt_example')}
        <select value={example} onChange={(e) => setExample(e.target.value)}>
          <option value="">—</option>
          {examples.map((e) => (
            <option key={e.name} value={e.name}>
              {e.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('jsx.prompt_feedback')}
        <textarea rows={3} value={feedback} placeholder={t('jsx.prompt_feedback_hint')} onChange={(e) => setFeedback(e.target.value)} />
      </label>
      <RunLlmSelector task="jsx_prompt" value={llm} onChange={setLlm} />
      <p className="faint">{t('jsx.prompt_note')}</p>
    </Dialog>
  );
}

function parseJson(text: string): unknown {
  try {
    const value = JSON.parse(text);
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}
