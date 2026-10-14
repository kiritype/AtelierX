import { useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { ApiError, get, post } from '../api';
import { t, tm } from '../i18n';
import {
  beginStartupUpdateCheck,
  shouldReportUpdateResult,
  startupUpdateState,
  takeStartupUpdateNotice,
  type UpdateSummary,
} from '../lib/updateNotice';
import type { MenuEntry } from './MenuBar';
import { useToast } from './Toasts';
import { Dialog } from './ui';

// Help menu (top menu bar and the work list): manual, shortcuts, update check, about.

type About = {
  version: string;
  packaged: boolean;
  built_at: string | null;
  commit: string | null;
  copyright: string;
  license: string;
  links: { repository: string; manual: string; releases: string; bug_report: string; feature_request: string; questions: string };
  notices: boolean;
  offline_manual: boolean;
  desktop: boolean;
};
type Update = { current: string; latest: string; newer: boolean; url: string; published_at: string | null; notes: string };
type HelpDialog = 'about' | 'shortcuts' | 'update' | 'notices' | null;
type UpdateState = {
  state: 'idle' | 'checking' | 'downloading' | 'verifying' | 'extracting' | 'backing_up' | 'ready' | 'failed' | 'restarting';
  packaged: boolean;
  current: string;
  version?: string;
  received?: number;
  total?: number;
  backup?: string;
  error?: { key: string; text: string; values?: Record<string, unknown> };
  last_result?: { state: 'ok' | 'failed'; detail?: string; version?: string; from?: string };
};
const PREPARING = ['checking', 'downloading', 'verifying', 'extracting', 'backing_up'];

const open = (url: string) => window.open(url, '_blank', 'noopener,noreferrer');
const browserStorage = () => {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
};

export function useHelp() {
  const [dialog, setDialog] = useState<HelpDialog>(null);
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const toast = useToast();
  const openUpdate = useCallback(() => setDialog('update'), []);
  const about = useQuery<About>({ queryKey: ['about'], queryFn: () => get('/api/about'), staleTime: Infinity });
  const entries: MenuEntry[] = [
    { label: t('help.manual'), run: () => open(about.data?.links.manual ?? 'https://atelierx.cftm.net/') },
    ...(about.data?.offline_manual ? [{ label: t('help.manual_offline'), run: () => open('/manual/index.html') }] : []),
    { label: t('help.shortcuts'), run: () => setDialog('shortcuts') },
    ...(about.data?.desktop
      ? [{
          label: t('help.open_in_browser'),
          run: () => {
            post('/api/open-in-browser', {})
              .then(() => toast({ text: t('help.open_in_browser_done') }))
              .catch((e) => toast({ text: e instanceof ApiError ? tm(e.msg) : String(e), tone: 'error' }));
          },
        }]
      : []),
    null,
    { label: t('help.check_update'), run: openUpdate },
    { label: t('help.releases'), run: () => open(about.data?.links.releases ?? 'https://github.com/kiritype/AtelierX/releases') },
    null,
    // Opened in Discussions; nothing is sent from the app.
    ...(about.data
      ? [
          { label: t('help.bug_report'), run: () => open(about.data!.links.bug_report) },
          { label: t('help.feature_request'), run: () => open(about.data!.links.feature_request) },
          { label: t('help.questions'), run: () => open(about.data!.links.questions) },
          null,
        ]
      : []),
    { label: t('help.about'), run: () => setDialog('about') },
  ];
  const close = () => setDialog(null);
  const element = (
    <>
      {dialog === 'about' && about.data && <AboutDialog about={about.data} onNotices={() => setDialog('notices')} onClose={close} />}
      {dialog === 'shortcuts' && <ShortcutsDialog onClose={close} />}
      {dialog === 'update' && <UpdateDialog onClose={close} />}
      {dialog === 'notices' && <NoticesDialog onClose={close} />}
    </>
  );
  return { entries, element, openUpdate, updateAvailable, setUpdateAvailable };
}

export function AboutContent({ about, onNotices }: { about: About; onNotices?: () => void }) {
  return (
    <div className="col about">
      <strong className="about-name">AtelierX {about.version}</strong>
      <span className="faint">{t('help.tagline')}</span>
      <dl className="kv">
        <dt>{t('help.build')}</dt>
        <dd>
          {about.packaged
            ? `${about.built_at?.slice(0, 16).replace('T', ' ') ?? '—'}${about.commit ? ` · ${about.commit.slice(0, 7)}` : ''}`
            : t('help.dev_build')}
        </dd>
        <dt>{t('help.license')}</dt>
        <dd>
          {about.copyright} · {about.license} License
        </dd>
      </dl>
      <div className="row wrap">
        <button onClick={() => open(about.links.repository)}>GitHub</button>
        <button onClick={() => open(about.links.manual)}>{t('help.manual')}</button>
        {about.notices && onNotices && <button onClick={onNotices}>{t('help.notices')}</button>}
      </div>
    </div>
  );
}

function AboutDialog({ about, onNotices, onClose }: { about: About; onNotices: () => void; onClose: () => void }) {
  return (
    <Dialog title={t('help.about')} onClose={onClose} closeLabel={t('common.close')}>
      <AboutContent about={about} onNotices={onNotices} />
    </Dialog>
  );
}

const SHORTCUTS: [string, string][] = [
  ['Ctrl+S', 'help.key.save'],
  ['Ctrl+P', 'editor.quick_open'],
  ['Ctrl+Shift+F', 'panel.search'],
  ['Ctrl+W', 'tabs.close'],
  ['Ctrl+Shift+L', 'common.lock'],
  ['F5', 'help.key.test'],
  ['Ctrl+Z / Ctrl+Y', 'help.key.undo'],
];

function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  return (
    <Dialog title={t('help.shortcuts')} onClose={onClose} closeLabel={t('common.close')}>
      <table className="plain">
        <tbody>
          {SHORTCUTS.map(([keys, label]) => (
            <tr key={keys}>
              <td className="mono">{keys}</td>
              <td>{t(label)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Dialog>
  );
}

function UpdateDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const check = useQuery<Update>({ queryKey: ['update-check'], queryFn: () => get('/api/update-check'), retry: false, staleTime: 0, gcTime: 0 });
  const update = useQuery<UpdateState>({
    queryKey: ['update-status'],
    queryFn: () => get('/api/update/status'),
    refetchInterval: (q) => (PREPARING.includes((q.state.data as UpdateState | undefined)?.state ?? '') ? 700 : false),
  });
  const fail = (err: unknown) => toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
  const u = update.data;
  async function start() {
    try {
      await post('/api/update/start');
      update.refetch();
    } catch (err) {
      fail(err);
    }
  }
  async function restart() {
    if (!confirm(t('update.restart_confirm'))) return;
    try {
      await post('/api/update/apply');
      update.refetch();
    } catch (err) {
      fail(err);
    }
  }
  const canUpdate = !!check.data?.newer && !!u?.packaged;
  const actions = !check.data?.newer ? undefined : canUpdate ? (
    u?.state === 'ready' ? (
      <button className="primary" onClick={restart}>{t('update.restart')}</button>
    ) : (
      <button className="primary" disabled={PREPARING.includes(u?.state ?? '') || u?.state === 'restarting'} onClick={start}>
        {t('update.start')}
      </button>
    )
  ) : (
    <button className="primary" onClick={() => open(check.data!.url)}>{t('help.open_release')}</button>
  );
  return (
    <Dialog title={t('help.check_update')} onClose={onClose} closeLabel={t('common.close')} actions={actions}>
      {check.isLoading && <p className="faint">{t('help.checking')}</p>}
      {check.error && <p className="error-text">{check.error instanceof ApiError ? tm(check.error.msg) : String(check.error)}</p>}
      {check.data && (
        <div className="col">
          <p>
            {check.data.newer
              ? t('help.update_available', { latest: check.data.latest, current: check.data.current })
              : t('help.up_to_date', { current: check.data.current })}
          </p>
          {check.data.notes && (
            <>
              <h4>{t('help.release_notes', { version: check.data.latest })}</h4>
              <pre className="update-notes">{check.data.notes}</pre>
            </>
          )}
          {check.data.newer && !u?.packaged && <p className="faint small">{t('help.update_how')}</p>}
          {check.data.newer && u?.packaged && u.state === 'idle' && <p className="faint small">{t('update.about')}</p>}
          {u && PREPARING.includes(u.state) && (
            <p className="faint">
              {t(`update.state.${u.state}`)}
              {u.state === 'downloading' && u.total ? ` ${Math.floor(((u.received ?? 0) / u.total) * 100)}%` : ''}
            </p>
          )}
          {u?.state === 'ready' && <p>{t('update.ready', { version: u.version ?? '', backup: u.backup ?? '' })}</p>}
          {u?.state === 'restarting' && <p>{t('update.restarting')}</p>}
          {u?.state === 'failed' && u.error && <p className="error-text">{tm(u.error)}</p>}
        </div>
      )}
    </Dialog>
  );
}

// After an update the new version says how it went, once.
export function useUpdateResult(openUpdate: () => void) {
  const toast = useToast();
  useEffect(() => {
    get<UpdateState>('/api/update/status')
      .then((status) => {
        const result = status.last_result;
        if (!result) return;
        if (!shouldReportUpdateResult(browserStorage(), result)) {
          post('/api/update/forget').catch(() => undefined);
          return;
        }
        toast(
          result.state === 'ok'
            ? { text: t('update.done', { version: result.version ?? status.current }), action: { label: t('update.view_changes'), run: openUpdate } }
            : { text: t('update.rolled_back', { detail: result.detail ?? '' }), tone: 'error' },
        );
        post('/api/update/forget').catch(() => undefined);
      })
      .catch(() => undefined);
  }, [openUpdate, toast]);
}

function NoticesDialog({ onClose }: { onClose: () => void }) {
  const notices = useQuery<string>({
    queryKey: ['about-notices'],
    queryFn: async () => (await fetch('/api/about/notices')).text(),
  });
  return (
    <Dialog title={t('help.notices')} onClose={onClose} closeLabel={t('common.close')}>
      <pre className="update-notes">{notices.data ?? '…'}</pre>
    </Dialog>
  );
}

// Checks at most once a day and keeps the last available version in browser preferences.
export function useStartupUpdateCheck(enabled: boolean, onAvailable: (available: boolean) => void, onOpenUpdate: () => void) {
  const toast = useToast();
  useEffect(() => {
    let active = true;
    if (!enabled) {
      onAvailable(false);
      return () => { active = false; };
    }
    const storage = browserStorage();
    const initial = startupUpdateState(storage);
    onAvailable(!!initial.availableVersion);
    const showNotice = (result: UpdateSummary) => {
      if (result.newer) {
        toast({ text: t('help.update_available', { latest: result.latest, current: result.current }), action: { label: t('help.check_update'), run: onOpenUpdate } });
      }
    };
    const savedNotice = takeStartupUpdateNotice(storage);
    if (savedNotice) showNotice(savedNotice);
    const check = beginStartupUpdateCheck(storage, () => get<Update>('/api/update-check'));
    if (!check) return () => { active = false; };
    check
      .then((result) => {
        if (!active) return;
        onAvailable(result.newer);
        const notice = takeStartupUpdateNotice(storage);
        if (notice) showNotice(notice);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [enabled, onAvailable, onOpenUpdate, toast]);
}
