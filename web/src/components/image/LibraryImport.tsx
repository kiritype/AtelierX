import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ApiError, post } from '../../api';
import { t, tm } from '../../i18n';
import { useToast } from '../Toasts';
import { Dialog } from '../ui';

// Bringing prompt library items in from a file (#154): each item shows as new or already here, with what would change
// and the values this PC does not know; the person chooses per item and where the items go. Nothing is written until
// "Bring in".
type Kind = 'expressions' | 'compositions' | 'common' | 'outfits';
type Change = { field: string; old: unknown; new: unknown };
type Row = {
  id: string;
  name: string;
  scope: 'global' | 'work' | null;
  exists: boolean;
  here_scope: 'global' | 'work' | null;
  changes: Change[];
  unknown: { field: string; value: string }[];
  shadowed: boolean;
};
type Look = { app_version?: string; items: Row[]; skipped: number };
type Choice = 'add' | 'overwrite' | 'skip';

const show = (value: unknown) =>
  Array.isArray(value) ? value.join(', ') || '—' : value === undefined || value === null || value === '' ? '—' : String(value);

export default function LibraryImport({
  kind,
  workId,
  file,
  onClose,
  onDone,
}: {
  kind: Kind;
  workId: string;
  file: unknown;
  onClose: () => void;
  onDone: (written: string[], items: unknown) => void;
}) {
  const toast = useToast();
  // Items exported from a work go back to a work by default; anything else to the global library.
  const fileItems = Object.values(((file as { items?: Record<string, { scope?: string }> })?.items ?? {}) as Record<string, { scope?: string }>);
  const [scope, setScope] = useState<'global' | 'work'>(fileItems.length && fileItems.every((i) => i.scope === 'work') ? 'work' : 'global');
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const look = useQuery<Look>({
    queryKey: ['library-import', kind, workId, scope, file],
    queryFn: () => post('/api/image/library-share/' + kind + '/preview', { file, scope, work: workId }),
    retry: false,
    gcTime: 0,
  });
  const rows = look.data?.items ?? [];
  const choiceOf = (row: Row): Choice => choices[row.id] ?? (row.exists ? 'skip' : 'add');
  const count = rows.filter((r) => choiceOf(r) !== 'skip').length;

  async function apply() {
    setBusy(true);
    try {
      const body = Object.fromEntries(rows.map((r) => [r.id, choiceOf(r)]));
      const done = await post<{ written: string[]; items: unknown }>('/api/image/library-share/' + kind + '/import', {
        file,
        scope,
        work: workId,
        choices: body,
      });
      onDone(done.written, done.items);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={t('lib.share.import_title', { kind: t(`lib.kind.${kind}`) })}
      onClose={onClose}
      className="wide"
      actions={
        <button className="primary" disabled={busy || !count || !look.data} onClick={apply}>
          {t('lib.share.import_apply', { n: count })}
        </button>
      }
    >
      <div className="row" style={{ gap: 8 }}>
        <span className="muted">{t('lib.share.scope')}</span>
        <select value={scope} onChange={(e) => setScope(e.target.value as 'global' | 'work')}>
          <option value="global">{t('lib.scope.global')}</option>
          <option value="work">{t('lib.scope.work')}</option>
        </select>
        <span className="faint small grow">{t(`lib.share.scope_hint.${scope}`)}</span>
      </div>
      {look.isError && <p className="warn-text">{look.error instanceof ApiError ? tm(look.error.msg) : String(look.error)}</p>}
      {!!look.data?.skipped && <p className="faint small">{t('lib.share.skipped', { n: look.data.skipped })}</p>}
      <div className="col" style={{ gap: 10, maxHeight: '60vh', overflow: 'auto' }}>
        {rows.map((row) => (
          <div key={row.id} className="col gen-patch" style={{ gap: 4 }}>
            <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
              <strong>{row.name}</strong>
              <span className="faint mono small">{row.id}</span>
              {row.exists ? (
                <span className="chip small warn">{t('lib.share.exists', { scope: t(`lib.scope.${row.here_scope ?? 'global'}`) })}</span>
              ) : (
                <span className="chip small">{t('lib.share.new')}</span>
              )}
              <span className="grow" />
              <select value={choiceOf(row)} onChange={(e) => setChoices({ ...choices, [row.id]: e.target.value as Choice })}>
                {row.exists ? (
                  <>
                    <option value="skip">{t('lib.share.choice.skip')}</option>
                    <option value="overwrite">{t('lib.share.choice.overwrite')}</option>
                  </>
                ) : (
                  <>
                    <option value="add">{t('lib.share.choice.add')}</option>
                    <option value="skip">{t('lib.share.choice.skip')}</option>
                  </>
                )}
              </select>
            </div>
            {row.exists &&
              (row.changes.length ? (
                <div className="col small" style={{ gap: 2 }}>
                  {row.changes.map((c) => (
                    <span key={c.field} className="mono">
                      <span className="muted">{t(`lib.share.field.${c.field}`)}</span> <span className="faint">{show(c.old)}</span> → {show(c.new)}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="faint small">{t('lib.share.same')}</span>
              ))}
            {row.shadowed && <span className="warn-text small">{t('lib.share.shadowed')}</span>}
            {row.unknown.length > 0 && (
              <span className="warn-text small">
                {t('lib.share.unknown', { list: row.unknown.map((u) => `${t(`lib.share.field.${u.field}`)} ${u.value}`).join(', ') })}
              </span>
            )}
          </div>
        ))}
      </div>
    </Dialog>
  );
}
