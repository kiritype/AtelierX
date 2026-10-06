import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { ApiError, del, get, put, q } from '../api';
import { t, tm } from '../i18n';
import { diffLines } from '../lib/diff';
import CodeEditor from './CodeEditor';
import { Icon } from './icons';
import { useToast } from './Toasts';
import { useUnsaved } from './Unsaved';

// Settings → 지침 (11-agent): the global guidelines in collapsible groups. One guideline is open at a time; an agent mode
// gets a form for its card (name, description, default scope, order) above its Markdown body.

type Group = 'agent' | 'task' | 'image' | 'other';
type Item = {
  name: string;
  group: Group;
  source: 'default' | 'modified' | 'custom';
  title?: string;
  description?: string;
  scope?: 'file' | 'work';
  order?: number;
};
type Listing = { items: Item[]; fixed: { agent: string } };
type FileDoc = { name: string; text: string; default_text: string | null; revision: string };
type Head = { name: string; description: string; scope: 'file' | 'work'; order: string; uses: string[]; rest: string[] };

const GROUPS: Group[] = ['agent', 'task', 'image', 'other'];
const OPEN_KEY = 'atelierx-guidelines-open';

function loadOpen(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(OPEN_KEY) ?? '') ?? {};
  } catch {
    return {};
  }
}

// The front matter of an agent mode: the card keys and the guidelines it reads along (uses) become form fields; other
// lines are kept as they are.
export function splitMode(text: string): { head: Head; body: string } {
  const head: Head = { name: '', description: '', scope: 'file', order: '', uses: [], rest: [] };
  const match = /^---\n([\s\S]*?)\n---\n?/.exec(text.replace(/\r\n/g, '\n'));
  if (!match) return { head, body: text };
  for (const line of match[1].split('\n')) {
    const uses = /^uses:\s*\[?([^\]]*)\]?\s*$/.exec(line);
    if (uses) {
      head.uses = uses[1].split(',').map((name) => name.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
      continue;
    }
    const field = /^(name|description|scope|order):\s*(.*)$/.exec(line);
    if (!field) {
      if (line.trim()) head.rest.push(line);
      continue;
    }
    let value = field[2].trim();
    if (/^".*"$/.test(value)) {
      try {
        value = JSON.parse(value);
      } catch {
        /* keep as written */
      }
    } else if (/^'.*'$/.test(value)) value = value.slice(1, -1).replaceAll("''", "'");
    if (field[1] === 'scope') head.scope = value === 'work' ? 'work' : 'file';
    else head[field[1] as 'name' | 'description' | 'order'] = value;
  }
  return { head, body: text.replace(/\r\n/g, '\n').slice(match[0].length) };
}

const yamlValue = (value: string) => (/^[\w가-힣 .,()·\-/]*$/.test(value) && !/^[-\s]/.test(value) && value.trim() === value ? value : JSON.stringify(value));

export function joinMode(head: Head, body: string): string {
  const lines = [`name: ${yamlValue(head.name)}`];
  if (head.description) lines.push(`description: ${yamlValue(head.description)}`);
  lines.push(`scope: ${head.scope}`);
  if (head.order.trim()) lines.push(`order: ${Number(head.order) || 100}`);
  if (head.uses.length) lines.push(`uses: [${head.uses.join(', ')}]`);
  return `---\n${[...lines, ...head.rest].join('\n')}\n---\n${body}`;
}

const titleOf = (item: Item) => (item.group === 'agent' ? item.title || item.name.slice(6, -3) : t(`guideline.title.${item.name}`) !== `guideline.title.${item.name}` ? t(`guideline.title.${item.name}`) : item.name);
const descOf = (item: Item) => (item.group === 'agent' ? item.description ?? '' : t(`guideline.desc.${item.name}`) !== `guideline.desc.${item.name}` ? t(`guideline.desc.${item.name}`) : '');

export default function GuidelineSettings() {
  const qc = useQueryClient();
  const toast = useToast();
  const listing = useQuery<Listing>({ queryKey: ['guidelines'], queryFn: () => get('/api/guidelines') });
  const [open, setOpen] = useState<Record<string, boolean>>(() => ({ agent: true, ...loadOpen() }));
  const [search, setSearch] = useState('');
  const [onlyChanged, setOnlyChanged] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [adding, setAdding] = useState(false);

  useUnsaved('guidelines', dirty);
  useEffect(() => {
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify(open));
    } catch {
      /* storage may be unavailable */
    }
  }, [open]);

  const items = listing.data?.items ?? [];
  const needle = search.trim().toLowerCase();
  const visible = items.filter(
    (i) =>
      (!onlyChanged || i.source !== 'default') &&
      (!needle || [i.name, titleOf(i), descOf(i)].some((s) => s.toLowerCase().includes(needle))),
  );

  const pick = (name: string | null) => {
    if (name === current) name = null;
    if (dirty && !confirm(t('guidelines.discard_confirm'))) return;
    setDirty(false);
    setCurrent(name);
  };
  const refresh = () => qc.invalidateQueries({ queryKey: ['guidelines'] });

  return (
    <div className="col guidelines" style={{ maxWidth: 860 }}>
      <p className="faint small">{t('guidelines.intro')}</p>
      <div className="row">
        <input className="grow" placeholder={t('guidelines.search')} value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="row" style={{ flexDirection: 'row' }}>
          <input type="checkbox" checked={onlyChanged} onChange={(e) => setOnlyChanged(e.target.checked)} />
          {t('guidelines.only_changed')}
        </label>
      </div>
      {GROUPS.map((group) => {
        // Agent modes in card order, as the agent panel shows them.
        const members = visible
          .filter((i) => i.group === group)
          .sort((a, b) => (group === 'agent' ? (a.order ?? 100) - (b.order ?? 100) || titleOf(a).localeCompare(titleOf(b)) : 0));
        const all = items.filter((i) => i.group === group);
        if (all.length === 0 && group !== 'agent') return null;
        const changed = all.filter((i) => i.source !== 'default').length;
        const expanded = !!open[group] || !!needle;
        return (
          <section key={group} className="guideline-group">
            <button className="guideline-group-head" onClick={() => setOpen({ ...open, [group]: !open[group] })} aria-expanded={expanded}>
              <Icon name={expanded ? 'collapse' : 'expand'} size={16} />
              <strong className="grow">{t(`guidelines.group.${group}`)}</strong>
              <span className="faint small">{all.length}</span>
              {changed > 0 && <span className="badge">{t('guidelines.changed_n', { n: changed })}</span>}
            </button>
            {expanded && (
              <div className="guideline-list">
                {members.length === 0 && <div className="faint small pad">{t('guidelines.none_here')}</div>}
                {members.map((item) => (
                  <div key={item.name} className={`guideline-row${current === item.name ? ' open' : ''}`}>
                    <button className="guideline-row-head" onClick={() => pick(item.name)} aria-expanded={current === item.name}>
                      <Icon name={current === item.name ? 'collapse' : 'expand'} size={14} />
                      <span className="col grow" style={{ gap: 0, alignItems: 'flex-start' }}>
                        <span>{titleOf(item)}</span>
                        {descOf(item) && <span className="faint small">{descOf(item)}</span>}
                      </span>
                      <span className={`badge source-${item.source}`}>{t(`guidelines.source.${item.source}`)}</span>
                    </button>
                    {current === item.name && (
                      <GuidelineEditor
                        key={item.name}
                        item={item}
                        references={items.filter((other) => other.group !== 'agent' && other.name !== 'platform.md').map((other) => other.name)}
                        onDirty={setDirty}
                        onSaved={() => {
                          setDirty(false);
                          refresh();
                        }}
                        onDeleted={() => {
                          setDirty(false);
                          setCurrent(null);
                          refresh();
                        }}
                        toast={toast}
                      />
                    )}
                  </div>
                ))}
                {group === 'agent' &&
                  (adding ? (
                    <NewMode
                      modes={all}
                      onCancel={() => setAdding(false)}
                      onCreated={(name) => {
                        setAdding(false);
                        refresh();
                        setCurrent(name);
                      }}
                      toast={toast}
                    />
                  ) : (
                    <button className="ghost" onClick={() => setAdding(true)}>
                      + {t('guidelines.add_mode')}
                    </button>
                  ))}
              </div>
            )}
          </section>
        );
      })}
      <section className="guideline-group">
        <button className="guideline-group-head" onClick={() => setOpen({ ...open, fixed: !open.fixed })} aria-expanded={!!open.fixed}>
          <Icon name={open.fixed ? 'collapse' : 'expand'} size={16} />
          <strong className="grow">{t('guidelines.group.fixed')}</strong>
          <span className="badge">{t('guidelines.read_only')}</span>
        </button>
        {open.fixed && (
          <div className="guideline-list">
            <p className="faint small">{t('guidelines.fixed_note')}</p>
            <pre className="proposal-text">{listing.data?.fixed.agent}</pre>
          </div>
        )}
      </section>
    </div>
  );
}

function GuidelineEditor({
  item,
  references,
  onDirty,
  onSaved,
  onDeleted,
  toast,
}: {
  item: Item;
  references: string[];
  onDirty: (dirty: boolean) => void;
  onSaved: () => void;
  onDeleted: () => void;
  toast: ReturnType<typeof useToast>;
}) {
  const qc = useQueryClient();
  const doc = useQuery<FileDoc>({ queryKey: ['guideline', item.name], queryFn: () => get(`/api/guidelines/file?name=${q(item.name)}`) });
  const [text, setText] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [busy, setBusy] = useState(false);
  const shown = text ?? doc.data?.text ?? '';
  const dirty = text !== null && text !== doc.data?.text;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  const mode = item.group === 'agent' ? splitMode(shown) : null;
  const diff = useMemo(
    () => (compare && doc.data?.default_text != null ? diffLines(doc.data.default_text.split('\n'), shown.split('\n')) : []),
    [compare, doc.data?.default_text, shown],
  );

  if (!doc.data) return <div className="pad faint">…</div>;

  async function save() {
    setBusy(true);
    try {
      const saved = await put<FileDoc>(`/api/guidelines/file?name=${q(item.name)}`, { text: shown, base_revision: doc.data!.revision });
      qc.setQueryData(['guideline', item.name], saved);
      qc.invalidateQueries({ queryKey: ['agent-modes'] });
      setText(null);
      onSaved();
      toast({ text: t('guidelines.saved') });
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(t('guidelines.delete_confirm', { name: titleOf(item) }))) return;
    try {
      await del(`/api/guidelines/file?name=${q(item.name)}`);
      qc.invalidateQueries({ queryKey: ['agent-modes'] });
      onDeleted();
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }

  return (
    <div className="guideline-editor col">
      {mode && (
        <div className="guideline-form">
          <label>
            {t('guidelines.mode_name')}
            <input value={mode.head.name} onChange={(e) => setText(joinMode({ ...mode.head, name: e.target.value }, mode.body))} />
          </label>
          <label>
            {t('guidelines.mode_scope')}
            <select value={mode.head.scope} onChange={(e) => setText(joinMode({ ...mode.head, scope: e.target.value as 'file' | 'work' }, mode.body))}>
              <option value="file">{t('agent.scope_file_short')}</option>
              <option value="work">{t('agent.scope_work')}</option>
            </select>
          </label>
          <label>
            {t('guidelines.mode_order')}
            <input type="number" value={mode.head.order} onChange={(e) => setText(joinMode({ ...mode.head, order: e.target.value }, mode.body))} />
          </label>
          <label className="wide">
            {t('guidelines.mode_description')}
            <input value={mode.head.description} onChange={(e) => setText(joinMode({ ...mode.head, description: e.target.value }, mode.body))} />
          </label>
          <fieldset className="wide guideline-uses">
            <legend title={t('guidelines.mode_uses_help')}>{t('guidelines.mode_uses')}</legend>
            {[...new Set([...references, ...mode.head.uses])].map((name) => (
              <label key={name} className="row" style={{ gap: 4 }}>
                <input
                  type="checkbox"
                  checked={mode.head.uses.includes(name)}
                  onChange={(e) => {
                    const uses = e.target.checked ? [...mode.head.uses, name] : mode.head.uses.filter((n) => n !== name);
                    setText(joinMode({ ...mode.head, uses }, mode.body));
                  }}
                />
                <code>{name}</code>
                {!references.includes(name) && <span className="faint small">{t('guidelines.mode_uses_elsewhere')}</span>}
              </label>
            ))}
            <span className="faint small">{t('guidelines.mode_uses_help')}</span>
          </fieldset>
        </div>
      )}
      <div className="guideline-body">
        <CodeEditor
          key={doc.data.revision}
          value={mode ? mode.body : shown}
          language="markdown"
          onChange={(value) => setText(mode ? joinMode(mode.head, value) : value)}
          onSave={save}
        />
      </div>
      {compare && (
        <div className="diff-view small">
          {diff.every((d) => d.op === ' ') ? (
            <div className="faint">{t('guidelines.same_as_default')}</div>
          ) : (
            diff
              .filter((d) => d.op !== ' ')
              .map((d, n) => (
                <div key={n} className={`diff-line ${d.op === '+' ? 'add' : 'del'}`}>
                  <span className="diff-mark">{d.op}</span>
                  {d.text || ' '}
                </div>
              ))
          )}
        </div>
      )}
      <div className="row">
        {doc.data.default_text != null && (
          <>
            <button className="ghost" onClick={() => setCompare(!compare)}>
              {t(compare ? 'guidelines.hide_compare' : 'guidelines.compare')}
            </button>
            <button className="ghost" disabled={shown === doc.data.default_text} onClick={() => setText(doc.data!.default_text)}>
              {t('guidelines.reset')}
            </button>
          </>
        )}
        {item.source === 'custom' && (
          <button className="ghost danger" onClick={remove}>
            {t('common.delete')}
          </button>
        )}
        <span className="grow" />
        {dirty && <span className="faint small">{t('status.unsaved')}</span>}
        {dirty && (
          <button disabled={busy} onClick={() => setText(null)}>
            {t('guidelines.revert')}
          </button>
        )}
        <button className="primary" disabled={busy || !dirty} onClick={save}>
          {t('common.save')}
        </button>
      </div>
    </div>
  );
}

function NewMode({ modes, onCancel, onCreated, toast }: { modes: Item[]; onCancel: () => void; onCreated: (name: string) => void; toast: ReturnType<typeof useToast> }) {
  const [id, setId] = useState('');
  const [base, setBase] = useState('');
  const valid = /^[a-z0-9][a-z0-9-]{0,39}$/.test(id) && !modes.some((m) => m.name === `agent/${id}.md`);
  async function create() {
    try {
      let text = `---\nname: ${id}\ndescription: \nscope: file\norder: 100\n---\n`;
      if (base) {
        const source = await get<FileDoc>(`/api/guidelines/file?name=${q(base)}`);
        const { head, body } = splitMode(source.text);
        text = joinMode({ ...head, name: `${head.name || id} ${t('guidelines.copy_suffix')}`.trim() }, body);
      }
      const name = `agent/${id}.md`;
      await put(`/api/guidelines/file?name=${q(name)}`, { text, base_revision: '' });
      onCreated(name);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    }
  }
  return (
    <div className="guideline-new col">
      <div className="row wrap">
        <label className="grow">
          {t('guidelines.mode_id')}
          <input value={id} placeholder="tone-check" onChange={(e) => setId(e.target.value.trim().toLowerCase())} autoFocus />
        </label>
        <label className="grow">
          {t('guidelines.start_from')}
          <select value={base} onChange={(e) => setBase(e.target.value)}>
            <option value="">{t('guidelines.empty_mode')}</option>
            {modes.map((m) => (
              <option key={m.name} value={m.name}>
                {titleOf(m)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="faint small">{t('guidelines.mode_id_hint')}</div>
      <div className="row">
        <span className="grow" />
        <button onClick={onCancel}>{t('common.cancel')}</button>
        <button className="primary" disabled={!valid} onClick={create}>
          {t('guidelines.create_mode')}
        </button>
      </div>
    </div>
  );
}
