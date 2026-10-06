import { useEffect, useState } from 'react';
import { ApiError, post } from '../api';
import { t, tm } from '../i18n';
import { useToast } from './Toasts';

export type ImportFile = { name: string; path: string; text: string };
type Choice = { include?: boolean; kind?: string; id?: string; enabled?: boolean; use_table?: boolean; broken?: 'skip' | 'note' };
type Row = {
  key: string;
  name: string;
  role: 'item' | 'table' | 'skip';
  matched?: number;
  suffix?: string;
  head?: 'ok' | 'none' | 'broken';
  error?: string;
  kind?: string | null;
  kind_error?: string;
  broken?: 'skip' | 'note' | null;
  include?: boolean;
  id?: string;
  original_id?: string;
  id_changed?: boolean;
  id_error?: 'format' | 'taken';
  enabled?: boolean;
  table?: { keywords: string[]; priority: number | null; always: boolean } | null;
  use_table?: boolean;
  path?: string;
  renamed?: boolean;
  main_warning?: boolean;
};
type Preview = { rows: Row[]; blocked: string[] };

const KINDS = ['main', 'start', 'lorebook', 'character', 'note'];

// File tree → Bring in… (#115): what each file becomes before anything is written. The app never guesses a kind.
export default function ImportDialog({
  workId,
  folder,
  files,
  onClose,
  onDone,
}: {
  workId: string;
  folder: string;
  files: ImportFile[];
  onClose: () => void;
  onDone: (created: string[]) => void;
}) {
  const toast = useToast();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });

  useEffect(() => {
    let live = true;
    post<Preview>(`/api/works/${workId}/import`, { folder, files, choices })
      .then((answer) => live && setPreview(answer))
      .catch((err) => live && fail(err));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workId, folder, files, choices]);

  const choose = (key: string, change: Choice) => setChoices({ ...choices, [key]: { ...choices[key], ...change } });
  const items = preview?.rows.filter((r) => r.role === 'item') ?? [];
  const table = preview?.rows.find((r) => r.role === 'table');
  const skipped = preview?.rows.filter((r) => r.role === 'skip') ?? [];
  const blocked = preview?.blocked.length ?? 0;
  const included = items.filter((r) => r.include).length;

  async function apply() {
    setBusy(true);
    try {
      const done = await post<{ created: string[] }>(`/api/works/${workId}/import`, { folder, files, choices, apply: true });
      toast({ text: t('import.done', { n: done.created.length }) });
      onDone(done.created);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog col" style={{ width: 'min(1150px, 95vw)', maxWidth: 'none', maxHeight: '90vh', overflow: 'auto' }}>
        <h3>{t('import.title')}</h3>
        <p className="faint small">{t('import.about', { folder: folder || t('import.root') })}</p>
        {table && <div className="notice small">{t('import.table_found', { n: table.matched ?? 0 })}</div>}
        {skipped.length > 0 && <div className="faint small">{t('import.skipped', { names: skipped.map((r) => r.name).join(', ') })}</div>}

        <div className="row" style={{ flexWrap: 'wrap' }}>
          <span className="muted small">{t('import.bulk_kind', { n: picked.size })}</span>
          <select
            value=""
            disabled={!picked.size}
            onChange={(e) => {
              const next = { ...choices };
              for (const key of picked) next[key] = { ...next[key], kind: e.target.value };
              setChoices(next);
            }}
          >
            <option value="">—</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`kind.${k}`)}
              </option>
            ))}
          </select>
        </div>

        <div style={{ overflow: 'auto', maxHeight: '50vh', border: '1px solid var(--border)', borderRadius: 6 }}>
          <table className="plain import-rows">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label={t('import.pick_all')}
                    checked={!!items.length && picked.size === items.length}
                    onChange={(e) => setPicked(e.target.checked ? new Set(items.map((r) => r.key)) : new Set())}
                  />
                </th>
                <th>{t('import.bring')}</th>
                <th>{t('import.file')}</th>
                <th>{t('import.head')}</th>
                <th>{t('import.kind')}</th>
                <th>ID</th>
                <th>{t('import.enabled')}</th>
                <th>{t('import.keywords')}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => {
                const jsx = row.suffix === '.jsx';
                const needsKind = row.include && !row.kind;
                return (
                  <tr key={row.key} className={needsKind ? 'needs' : ''}>
                    <td>
                      <input
                        type="checkbox"
                        checked={picked.has(row.key)}
                        onChange={(e) => {
                          const next = new Set(picked);
                          if (e.target.checked) next.add(row.key);
                          else next.delete(row.key);
                          setPicked(next);
                        }}
                      />
                    </td>
                    <td>
                      <input type="checkbox" checked={!!row.include} onChange={(e) => choose(row.key, { include: e.target.checked })} title={t('import.bring')} />
                    </td>
                    <td className="small file">
                      <div className="mono">{row.name}</div>
                      {row.include && row.path && <div className={row.renamed ? 'warn-text' : 'faint'}>→ {row.path}</div>}
                    </td>
                    <td className="small">
                      {row.head === 'ok' && <span className="chip small ok">{t('import.head_ok')}</span>}
                      {row.head === 'none' && <span className="chip small">{t('import.head_none')}</span>}
                      {row.head === 'broken' && (
                        <div className="col" style={{ gap: 2 }}>
                          <span className="chip small warn" title={row.error}>{t('import.head_broken')}</span>
                          <select value={row.broken ?? ''} onChange={(e) => choose(row.key, { broken: (e.target.value || undefined) as Choice['broken'], include: e.target.value === 'note' })}>
                            <option value="">{t('import.broken_choose')}</option>
                            <option value="skip">{t('import.broken_skip')}</option>
                            <option value="note">{t('import.broken_note')}</option>
                          </select>
                        </div>
                      )}
                    </td>
                    <td>
                      {jsx ? (
                        <span className="small">{t('kind.jsx')}</span>
                      ) : row.head === 'broken' ? (
                        <span className="small faint">{row.kind ? t(`kind.${row.kind}`) : '—'}</span>
                      ) : (
                        <select value={row.kind ?? ''} disabled={!row.include} onChange={(e) => choose(row.key, { kind: e.target.value })} className={needsKind ? 'needs' : ''}>
                          <option value="">{t('import.choose_kind')}</option>
                          {KINDS.map((k) => (
                            <option key={k} value={k}>
                              {t(`kind.${k}`)}
                            </option>
                          ))}
                        </select>
                      )}
                      {row.kind_error && <div className="error-text small">{t('import.kind_suffix')}</div>}
                    </td>
                    <td>
                      <input
                        className="mono small"
                        style={{ width: 90 }}
                        disabled={!row.include || !row.kind}
                        placeholder={row.id || ''}
                        value={choices[row.key]?.id ?? ''}
                        onChange={(e) => choose(row.key, { id: e.target.value })}
                      />
                      {row.id_changed && <div className="faint small">{t('import.id_changed', { from: row.original_id ?? '', to: row.id ?? '' })}</div>}
                      {row.id_error && <div className="error-text small">{t(`import.id_${row.id_error}`)}</div>}
                    </td>
                    <td>
                      {row.kind !== 'note' && (
                        <input type="checkbox" disabled={!row.include} checked={!!row.enabled} onChange={(e) => choose(row.key, { enabled: e.target.checked })} />
                      )}
                      {row.main_warning && <div className="warn-text small">{t('import.main_twice')}</div>}
                    </td>
                    <td className="small keys">
                      {row.table ? (
                        <label className="row" style={{ flexDirection: 'row', gap: 4, alignItems: 'start' }}>
                          <input type="checkbox" checked={!!row.use_table} onChange={(e) => choose(row.key, { use_table: e.target.checked })} />
                          <span>
                            {t('import.from_table')}: {row.table.keywords.join(', ') || '—'}
                            {row.table.priority != null && ` · ${row.table.priority}`}
                            {row.table.always && ` · ${t('import.always')}`}
                          </span>
                        </label>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <span className="faint small">{t('import.snapshot_note')}</span>
        {table && <span className="faint small">{t('import.package_note')}</span>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          {blocked > 0 && <span className="warn-text small grow">{t('import.blocked', { n: blocked })}</span>}
          <button onClick={onClose}>{t('common.cancel')}</button>
          <button className="primary" disabled={busy || !preview || blocked > 0 || included === 0} onClick={apply}>
            {t('import.apply', { n: included })}
          </button>
        </div>
      </div>
    </div>
  );
}
