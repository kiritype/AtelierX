import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { ApiError, del, get, put } from '../../api';
import { t, tm } from '../../i18n';
import TagInput from '../TagInput';
import { useToast } from '../Toasts';
import { byGroup, targetNames, type Target } from '../../lib/fragments';
import { useUnsaved } from '../Unsaved';
import { afterSave, followSelection } from '../../lib/libraryDraft';
import LibraryImport from './LibraryImport';

type Kind = 'expressions' | 'compositions' | 'common' | 'outfits' | 'targets';
const KINDS: Kind[] = ['expressions', 'compositions', 'common', 'outfits', 'targets'];
type Item = {
  id: string;
  name: string;
  prompt: string[];
  negative?: string[];
  scope?: 'global' | 'work';
  overrides?: boolean;
  rating?: string;
  code?: string;
  composition?: string;
  suggest_slots?: string[];
  hide_outfit?: boolean;
  target?: 'positive' | 'negative';
  default?: boolean;
  slot?: string;
  group?: string;
  targets?: string[];
};
type Rules = { slots: { id: string; name: string }[]; ratings: { id: string; name: string }[]; targets: Target[] };

// Image menu → Prompt library: global items and this work's own (a work item with the same id overrides).
export default function ImageLibrary({ workId }: { workId: string }) {
  const [kind, setKind] = useState<Kind>('expressions');
  // Whether the open editor has unsaved changes: switching the kind would drop them (#167).
  const [dirty, setDirty] = useState(false);
  function chooseKind(next: Kind) {
    if (next === kind || (dirty && !confirm(t('lib.discard_confirm')))) return;
    setDirty(false);
    setKind(next);
  }
  return (
    <div className="image-lib">
      <div className="image-lib-kinds">
        {KINDS.map((k) => (
          <div key={k} className={`tree-row${kind === k ? ' sel' : ''}`} onClick={() => chooseKind(k)}>
            {t(`lib.kind.${k}`)}
          </div>
        ))}
      </div>
      {kind === 'targets' ? (
        <Targets onDirty={setDirty} />
      ) : (
        <Items key={kind} workId={workId} kind={kind} onDirty={setDirty} />
      )}
    </div>
  );
}

function useFail() {
  const toast = useToast();
  return (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
}

function Items({ workId, kind, onDirty }: { workId: string; kind: Exclude<Kind, 'targets'>; onDirty: (dirty: boolean) => void }) {
  const qc = useQueryClient();
  const fail = useFail();
  const toast = useToast();
  const key = ['image-lib', kind, workId];
  const items = useQuery<Record<string, Item>>({ queryKey: key, queryFn: () => get(`/api/image/library/${kind}?work=${workId}`) });
  const rules = useQuery<Rules>({ queryKey: ['image-lib-rules'], queryFn: () => get('/api/image/library/rules') });
  const compositions = useQuery<Record<string, Item>>({
    queryKey: ['image-lib', 'compositions', workId],
    queryFn: () => get(`/api/image/library/compositions?work=${workId}`),
    enabled: kind === 'expressions',
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState<(Item & { scope: 'global' | 'work' }) | null>(null);
  const [filter, setFilter] = useState('');
  // Items checked for export (#154); none checked exports the whole list.
  const [checked, setChecked] = useState<string[]>([]);
  const [importing, setImporting] = useState<unknown>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const list = Object.values(items.data ?? {}).filter((i) => !filter || `${i.id} ${i.name} ${i.group ?? ''}`.toLowerCase().includes(filter.toLowerCase()));
  const groups = [...new Set(Object.values(items.data ?? {}).map((i) => i.group ?? '').filter(Boolean))];
  const targets = rules.data?.targets ?? [];

  // The draft follows the selection. A list fetched again (focus, another save) does not replace an edit in progress;
  // only the first load of the selected item fills an empty editor (#167).
  useEffect(() => {
    const item = selected ? items.data?.[selected] : null;
    setDraft((current) => followSelection(current, selected, item ? { ...item, scope: item.scope ?? 'global' } : null));
  }, [selected, items.data]);
  // The item being edited differs from what is stored (a new one always does) until it is saved.
  const stored = draft ? items.data?.[draft.id] : undefined;
  // Deployment codes may repeat (decision 0023); the editor names the other expressions with the same code.
  const sameCode =
    kind === 'expressions' && draft?.code?.trim()
      ? Object.values(items.data ?? {})
          .filter((i) => i.id !== draft.id && (i.code ?? '').trim() === draft.code!.trim())
          .map((i) => `${i.name} (${i.id})`)
      : [];
  const dirty = !!draft && (!stored || JSON.stringify({ ...stored, scope: stored.scope ?? 'global' }) !== JSON.stringify(draft));
  useUnsaved(`library-${kind}`, dirty);
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  // A work item saved as global moves there (the work copy is removed, #147); global saved as work overrides it here.
  const movingToGlobal = stored?.scope === 'work' && draft?.scope === 'global';
  const overridingGlobal = stored?.scope === 'global' && draft?.scope === 'work';

  function pick(id: string) {
    if (id === selected && draft?.id === id) return;
    if (dirty && !confirm(t('lib.discard_confirm'))) return;
    const item = items.data?.[id];
    setSelected(id);
    setDraft(item ? { ...item, scope: item.scope ?? 'global' } : null);
  }

  async function save() {
    if (!draft) return;
    const sent = draft;
    const sentSelection = selected;
    const { id, scope, ...item } = sent;
    if (movingToGlobal && stored?.overrides && !confirm(t('lib.replace_global_confirm', { id }))) return;
    try {
      const result = await put<Record<string, Item>>(`/api/image/library/${kind}/${id}`, {
        scope,
        work: workId,
        item,
        ...(movingToGlobal ? { from_scope: 'work' } : {}),
      });
      qc.setQueryData(key, result);
      const saved = result[id];
      // Typing on, or opening another item, while the save was on its way wins over the answer.
      setSelected((current) => (current === sentSelection ? id : current));
      setDraft((current) => afterSave(current, sent, saved ? { ...saved, scope: saved.scope ?? 'global' } : null));
    } catch (err) {
      fail(err);
    }
  }

  function create() {
    if (dirty && !confirm(t('lib.discard_confirm'))) return;
    const ident = prompt(t('lib.new_id'))?.trim();
    if (!ident) return;
    // An id in use would silently overwrite or override that item (#147).
    if (items.data?.[ident]) {
      alert(t('lib.id_taken', { id: ident }));
      return;
    }
    const blank: Item & { scope: 'global' | 'work' } = {
      id: ident,
      name: ident,
      prompt: [],
      negative: [],
      scope: 'work',
      ...(kind === 'expressions' ? { rating: rules.data?.ratings[0]?.id } : {}),
      ...(kind === 'common' ? { target: 'positive' as const, default: true } : {}),
      ...(kind === 'outfits' ? { slot: rules.data?.slots[0]?.id } : {}),
    };
    setSelected(ident);
    setDraft(blank);
  }

  return (
    <>
      <div className="image-lib-list">
        <div className="row pad" style={{ paddingBottom: 4 }}>
          <input className="grow" placeholder={t('lib.filter')} value={filter} onChange={(e) => setFilter(e.target.value)} />
          <button onClick={create}>+</button>
        </div>
        <div className="row pad small" style={{ paddingTop: 0, paddingBottom: 4, gap: 6 }}>
          <a
            className={`button small${Object.keys(items.data ?? {}).length ? '' : ' disabled'}`}
            href={
              Object.keys(items.data ?? {}).length
                ? `/api/image/library-share/${kind}/export?work=${workId}${checked.length ? `&ids=${checked.join(',')}` : ''}`
                : undefined
            }
            title={t('lib.share.export_hint')}
          >
            {checked.length ? t('lib.share.export_checked', { n: checked.length }) : t('lib.share.export_all')}
          </a>
          <button className="small" onClick={() => fileInput.current?.click()}>
            {t('lib.share.import')}
          </button>
          {checked.length > 0 && (
            <button className="small" onClick={() => setChecked([])}>
              {t('lib.share.uncheck')}
            </button>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={async (e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (!file) return;
              try {
                setImporting(JSON.parse(await file.text()));
              } catch {
                toast({ text: t('lib.share.not_json'), tone: 'error' });
              }
            }}
          />
        </div>
        {byGroup(list).map(({ group, items: grouped }) => (
          <div key={group || '-'}>
            {(group || groups.length > 0) && <div className="lib-group-title">{group || t('lib.no_group')}</div>}
            {grouped.map((item) => (
              <div key={item.id} className={`list-row${selected === item.id ? ' sel' : ''}`} onClick={() => pick(item.id)}>
                <input
                  type="checkbox"
                  checked={checked.includes(item.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setChecked(e.target.checked ? [...checked, item.id] : checked.filter((i) => i !== item.id))}
                  aria-label={t('lib.share.check')}
                />
                <span className="grow">
                  {item.name} <span className="faint mono">{item.id}</span>
                  {kind === 'expressions' && item.code && <span className="chip small mono" title={t('lib.code')}>{item.code}</span>}
                  {kind === 'compositions' && item.hide_outfit && <span className="chip small" title={t('lib.hide_outfit_hint')}>{t('lib.hide_outfit')}</span>}
                  {!!item.targets?.length && <span className="faint small"> · {targetNames(item.targets, targets)}</span>}
                </span>
                <span className={`chip scope-${item.scope}`}>{t(`lib.scope.${item.scope}`)}</span>
              </div>
            ))}
          </div>
        ))}
        {list.length === 0 && <div className="empty">{t('lib.empty')}</div>}
        {importing !== null && (
          <LibraryImport
            kind={kind}
            workId={workId}
            file={importing}
            onClose={() => setImporting(null)}
            onDone={(written, result) => {
              qc.setQueryData(key, result);
              setImporting(null);
              toast({ text: t('lib.share.imported', { n: written.length }) });
            }}
          />
        )}
      </div>
      <div className="image-lib-edit pad col">
        {!draft ? (
          <p className="faint">{t(`lib.about.${kind}`)}</p>
        ) : (
          <>
            <div className="row">
              <strong className="grow">
                {draft.id}
                {draft.overrides && <span className="faint"> · {t('lib.overrides')}</span>}
              </strong>
              <select value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value as 'global' | 'work' })}>
                <option value="work">{t('lib.scope.work')}</option>
                <option value="global">{t('lib.scope.global')}</option>
              </select>
            </div>
            {overridingGlobal && <span className="faint small">{t('lib.scope_override_hint')}</span>}
            {movingToGlobal && <span className="faint small">{t('lib.scope_move_hint')}</span>}
            <label className="col" style={{ gap: 2 }}>
              <span className="muted">{t('lib.name')}</span>
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </label>
            <label className="col" style={{ gap: 2 }}>
              <span className="muted">{kind === 'common' && draft.target === 'negative' ? t('lib.negative_tags') : t('lib.prompt')}</span>
              <TagInput values={draft.prompt} onChange={(prompt) => setDraft({ ...draft, prompt })} placeholder={t('lib.tag_hint')} />
            </label>
            {kind !== 'common' && (
              <label className="col" style={{ gap: 2 }}>
                <span className="muted">{t('lib.negative')}</span>
                <TagInput values={draft.negative ?? []} onChange={(negative) => setDraft({ ...draft, negative })} />
              </label>
            )}
            {kind === 'expressions' && (
              <label className="col" style={{ gap: 2 }}>
                <span className="muted">{t('lib.code')}</span>
                <input className="mono" style={{ width: 160 }} value={draft.code ?? ''} onChange={(e) => setDraft({ ...draft, code: e.target.value })} />
                <span className="faint small">{t('lib.code_hint')}</span>
                {sameCode.length > 0 && <span className="warn-text small">{t('lib.code_same', { names: sameCode.join(', ') })}</span>}
              </label>
            )}
            {kind === 'expressions' && (
              <div className="row">
                <label className="col" style={{ gap: 2 }}>
                  <span className="muted">{t('lib.rating')}</span>
                  <select value={draft.rating} onChange={(e) => setDraft({ ...draft, rating: e.target.value })}>
                    {rules.data?.ratings.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="col" style={{ gap: 2 }}>
                  <span className="muted">{t('lib.composition')}</span>
                  <select value={draft.composition ?? ''} onChange={(e) => setDraft({ ...draft, composition: e.target.value || undefined })}>
                    <option value="">—</option>
                    {Object.values(compositions.data ?? {}).map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
            {kind === 'compositions' && (
              <div className="col" style={{ gap: 2 }}>
                <span className="muted">{t('lib.suggest_slots')}</span>
                <label className="row" style={{ gap: 4 }} title={t('lib.hide_outfit_hint')}>
                  <input type="checkbox" checked={!!draft.hide_outfit} onChange={(e) => setDraft({ ...draft, hide_outfit: e.target.checked })} />
                  {t('lib.hide_outfit')}
                </label>
                {draft.hide_outfit && <span className="faint small">{t('lib.hide_outfit_hint')}</span>}
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  {rules.data?.slots.map((slot) => (
                    <label key={slot.id} className="row" style={{ gap: 4 }}>
                      <input
                        type="checkbox"
                        disabled={!!draft.hide_outfit}
                        checked={(draft.suggest_slots ?? []).includes(slot.id)}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            suggest_slots: e.target.checked ? [...(draft.suggest_slots ?? []), slot.id] : (draft.suggest_slots ?? []).filter((s) => s !== slot.id),
                          })
                        }
                      />
                      {slot.name}
                    </label>
                  ))}
                </div>
              </div>
            )}
            {kind === 'common' && (
              <div className="row">
                <select value={draft.target} onChange={(e) => setDraft({ ...draft, target: e.target.value as 'positive' | 'negative' })}>
                  <option value="positive">{t('lib.target.positive')}</option>
                  <option value="negative">{t('lib.target.negative')}</option>
                </select>
                <label className="row" style={{ gap: 4 }}>
                  <input type="checkbox" checked={draft.default !== false} onChange={(e) => setDraft({ ...draft, default: e.target.checked })} />
                  {t('lib.default_on')}
                </label>
              </div>
            )}
            {kind === 'outfits' && (
              <label className="col" style={{ gap: 2 }}>
                <span className="muted">{t('lib.slot')}</span>
                <select value={draft.slot} onChange={(e) => setDraft({ ...draft, slot: e.target.value })}>
                  {rules.data?.slots.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="col" style={{ gap: 2 }}>
              <span className="muted">{t('lib.group')}</span>
              <input list={`lib-groups-${kind}`} value={draft.group ?? ''} placeholder={t('lib.group_hint')} onChange={(e) => setDraft({ ...draft, group: e.target.value })} />
              <datalist id={`lib-groups-${kind}`}>
                {groups.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
            </label>
            <div className="col" style={{ gap: 2 }}>
              <span className="muted">{t('lib.targets')}</span>
              <div className="row" style={{ flexWrap: 'wrap' }}>
                {targets.map((target) => (
                  <label key={target.id} className="row" style={{ gap: 4 }}>
                    <input
                      type="checkbox"
                      checked={(draft.targets ?? []).includes(target.id)}
                      onChange={(e) =>
                        setDraft({ ...draft, targets: e.target.checked ? [...(draft.targets ?? []), target.id] : (draft.targets ?? []).filter((x) => x !== target.id) })
                      }
                    />
                    {target.name}
                  </label>
                ))}
              </div>
              <span className="faint small">{t('lib.targets_all')}</span>
            </div>
            <div className="row">
              <button className="primary" onClick={save}>
                {t('common.save')}
              </button>
              {draft.scope && items.data?.[draft.id]?.scope === draft.scope && (
                <button
                  className="danger"
                  onClick={async () => {
                    if (!confirm(t('lib.delete_confirm', { id: draft.id }))) return;
                    try {
                      qc.setQueryData(key, await del(`/api/image/library/${kind}/${draft.id}?scope=${draft.scope}&work=${workId}`));
                      setSelected(null);
                    } catch (err) {
                      fail(err);
                    }
                  }}
                >
                  {t('common.delete')}
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </>
  );
}

// Image menu → Prompt library → Targets (#80): the model families and image services fragments are written for.
function Targets({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const qc = useQueryClient();
  const fail = useFail();
  const rules = useQuery<Rules>({ queryKey: ['image-lib-rules'], queryFn: () => get('/api/image/library/rules') });
  const [list, setList] = useState<Target[] | null>(null);
  useEffect(() => setList(rules.data?.targets ?? null), [rules.data]);
  const changed = !!list && JSON.stringify(list) !== JSON.stringify(rules.data?.targets);
  useUnsaved('library-targets', changed);
  useEffect(() => onDirty(changed), [changed, onDirty]);
  if (!list) return null;

  async function save() {
    try {
      qc.setQueryData(['image-lib-rules'], await put('/api/image/library/rules/targets', { targets: list }));
      qc.invalidateQueries({ queryKey: ['image-lib'] });
    } catch (err) {
      fail(err);
    }
  }

  return (
    <div className="image-lib-edit pad col" style={{ gridColumn: 'span 2', maxWidth: 560 }}>
      <p className="faint">{t('lib.targets_about')}</p>
      {list.map((target, n) => (
        <div key={n} className="row">
          <input className="mono" style={{ width: 120 }} placeholder={t('lib.target_id')} value={target.id} onChange={(e) => setList(list.map((x, i) => (i === n ? { ...x, id: e.target.value } : x)))} />
          <input className="grow" placeholder={t('lib.target_name')} value={target.name} onChange={(e) => setList(list.map((x, i) => (i === n ? { ...x, name: e.target.value } : x)))} />
          <button className="ghost" title={t('common.delete')} disabled={list.length <= 1} onClick={() => setList(list.filter((_, i) => i !== n))}>
            ×
          </button>
        </div>
      ))}
      <div className="row">
        <button onClick={() => setList([...list, { id: '', name: '' }])}>{t('lib.target_add')}</button>
        <span className="grow" />
        <button className="primary" disabled={!changed} onClick={save}>
          {t('common.save')}
        </button>
      </div>
    </div>
  );
}
