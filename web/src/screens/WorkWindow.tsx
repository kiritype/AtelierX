import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, get, post, put } from '../api';
import AppSettings from '../components/AppSettings';
import AuxPanel, { type AuxTab } from '../components/AuxPanel';
import type { Attachment } from '../components/AgentPanel';
import CompareTab from '../components/CompareTab';
import ExportDialog from '../components/ExportDialog';
import AuthoringDialog from '../components/AuthoringDialog';
import GlossaryTab from '../components/GlossaryTab';
import MenuBar, { type Menu } from '../components/MenuBar';
import RenameDialog from '../components/RenameDialog';
import ItemEditor, { type EditorStatus } from '../components/ItemEditor';
import JobsPopover from '../components/JobsPopover';
import Panels, { type PanelKey } from '../components/Panels';
import QuickOpen from '../components/QuickOpen';
import RelationsTab from '../components/RelationsTab';
import ReviewTab from '../components/ReviewTab';
import { useToast } from '../components/Toasts';
import { ContextMenu, Dialog, ErrorBoundary, formatBytes, type MenuItem } from '../components/ui';
import { AppMark } from '../components/AppMark';
import { Icon, type IconName } from '../components/icons';
import { useHelp, useStartupUpdateCheck } from '../components/Help';
import WorkSettings from '../components/WorkSettings';
import ImageScreen from './ImageScreen';
import TestScreen from './TestScreen';
import RunLlmSelector, { type LlmOverride } from '../components/RunLlmSelector';
import { bulkCloseKeys, nextActiveKey, tracksFormChanges } from './tabActions';
import { useServerEvents } from '../events';
import { t, tm } from '../i18n';
import { tabKey, type ImageView, type Job, type Tab, type WorkInfo } from '../types';

// Side panels: one is selected at a time. Below a divider, relations and glossary are launchers that open their editor
// tab; they never show a selected state, so the activity bar always marks exactly the panel that is open.
const PANELS: { key: PanelKey; icon: IconName }[] = [
  { key: 'files', icon: 'files' },
  { key: 'search', icon: 'search' },
  { key: 'image', icon: 'image' },
  { key: 'drafts', icon: 'drafts' },
  { key: 'history', icon: 'history' },
  { key: 'trash', icon: 'trash' },
];
const LAUNCHERS: { tab: 'relations' | 'glossary'; icon: IconName }[] = [
  { tab: 'relations', icon: 'relations' },
  { tab: 'glossary', icon: 'glossary' },
];

export default function WorkWindow({ workId, onLeave, onLock }: { workId: string; onLeave: () => void; onLock: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const info = useQuery<WorkInfo>({ queryKey: ['work', workId], queryFn: () => get(`/api/works/${workId}`) });
  const drafts = useQuery({ queryKey: ['drafts', workId], queryFn: () => get(`/api/works/${workId}/drafts?status=pending`) });
  const [llmJob, setLlmJob] = useState<{ url: string; message: string } | null>(null);
  const [llm, setLlm] = useState<LlmOverride | undefined>();
  const [llmBusy, setLlmBusy] = useState(false);
  const jobs = useQuery<Job[]>({ queryKey: ['jobs'], queryFn: () => get('/api/jobs') });
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [pinned, setPinned] = useState<string[]>([]);
  const [formDirty, setFormDirty] = useState<string[]>([]);
  const [tabMenu, setTabMenu] = useState<{ key: string; x: number; y: number } | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [panel, setPanel] = useState<PanelKey | null>('files');
  const [aux, setAux] = useState<AuxTab | null>('check');
  const [agentAttach, setAgentAttach] = useState<Attachment | null>(null);
  useEffect(() => {
    const onAttach = (event: Event) => {
      setAgentAttach((event as CustomEvent<Attachment>).detail);
      setAux('agent');
    };
    window.addEventListener('atelierx:agent-attach', onAttach);
    return () => window.removeEventListener('atelierx:agent-attach', onAttach);
  }, []);
  const [testing, setTesting] = useState(false);
  const [status, setStatus] = useState<Record<string, EditorStatus>>({});
  const [showJobs, setShowJobs] = useState(false);
  const [quickOpen, setQuickOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [authoring, setAuthoring] = useState(false);
  const [restored, setRestored] = useState(false);
  const help = useHelp();
  const appSettings = useQuery<{ update_check_on_start?: boolean }>({ queryKey: ['settings'], queryFn: () => get('/api/settings') });
  useStartupUpdateCheck(!!appSettings.data?.update_check_on_start);
  // Leaving the work or locking waits here while tabs have unsaved changes (the server cannot keep what only the page has).
  const [pending, setPending] = useState<{ run: () => Promise<void> } | null>(null);
  const [savingAll, setSavingAll] = useState(false);

  // Restore open tabs from the last session of this work.
  useEffect(() => {
    get('/api/ui-state').then((state) => {
      const saved = state?.works?.[workId];
      if (saved?.tabs) {
        setTabs(saved.tabs);
        setPinned(Array.isArray(saved.pinned) ? saved.pinned : []);
        setActive(saved.active ?? null);
      }
      setRestored(true);
    });
  }, [workId]);
  useEffect(() => {
    if (!restored) return;
    const timer = setTimeout(async () => {
      const state = (await get('/api/ui-state').catch(() => ({}))) ?? {};
      await put('/api/ui-state', { ...state, works: { ...(state.works ?? {}), [workId]: { tabs, active, pinned } } });
    }, 500);
    return () => clearTimeout(timer);
  }, [tabs, active, pinned, workId, restored]);

  const open = useCallback((tab: Tab) => {
    const key = tabKey(tab);
    setTabs((list) => (list.some((x) => tabKey(x) === key) ? list : [...list, tab]));
    setActive(key);
    setTesting(false);
  }, []);

  const confirmClose = useCallback((keys: string[]) => {
    const dirtyEditors = keys.some((key) => status[key]?.dirty);
    const dirtyForms = tabs.filter((tab) => keys.includes(tabKey(tab)) && tab.type !== 'item' && formDirty.includes(tabKey(tab)));
    const warnings = [
      ...(dirtyEditors ? [t('editor.close_unsaved')] : []),
      ...(dirtyForms.length ? [t('tabs.close_forms_warning', { names: dirtyForms.map(tabTitle).join(', ') })] : []),
    ];
    return !warnings.length || confirm(warnings.join('\n'));
  }, [formDirty, status, tabs]);

  const close = useCallback(
    (key: string) => {
      if (!confirmClose([key])) return;
      const closing = new Set([key]);
      const keys = tabs.map(tabKey);
      setTabs(tabs.filter((tab) => tabKey(tab) !== key));
      setPinned((pins) => pins.filter((p) => p !== key));
      setStatus((all) => Object.fromEntries(Object.entries(all).filter(([statusKey]) => statusKey !== key)));
      setFormDirty((dirty) => dirty.filter((x) => x !== key));
      if (active === key) setActive(nextActiveKey(keys, closing, active));
    },
    [active, confirmClose, tabs],
  );

  const closeMany = useCallback((keys: string[]) => {
    const closing = new Set(keys);
    if (!closing.size) return;
    if (!confirmClose([...closing])) return;
    const remaining = tabs.filter((tab) => !closing.has(tabKey(tab)));
    setTabs(remaining);
    setPinned((pins) => pins.filter((key) => !closing.has(key)));
    setStatus((all) => Object.fromEntries(Object.entries(all).filter(([key]) => !closing.has(key))));
    setFormDirty((dirty) => dirty.filter((key) => !closing.has(key)));
    if (active && closing.has(active)) setActive(nextActiveKey(tabs.map(tabKey), closing, active));
  }, [active, confirmClose, tabs]);

  const tabMenuItems = (key: string): MenuItem[] => {
    const keys = tabs.map(tabKey);
    const closeableOthers = bulkCloseKeys(keys, key, pinned, 'others');
    const closeableRight = bulkCloseKeys(keys, key, pinned, 'right');
    return [
      { label: t(pinned.includes(key) ? 'tabs.unpin' : 'tabs.pin'), run: () => setPinned((pins) => pinned.includes(key) ? pins.filter((x) => x !== key) : [...pins, key]) },
      null,
      { label: t('tabs.close'), run: () => close(key) },
      { label: t('tabs.close_others'), run: () => closeMany(closeableOthers) },
      { label: t('tabs.close_right'), run: () => closeMany(closeableRight) },
    ];
  };

  const renamePath = useCallback((from: string, to: string) => {
    const remapKey = (key: string) => {
      if (!key.startsWith('item:')) return key;
      const path = key.slice('item:'.length);
      if (path === from) return `item:${to}`;
      if (path.startsWith(`${from}/`)) return `item:${to}${path.slice(from.length)}`;
      return key;
    };
    setTabs((list) =>
      list.map((tab) => {
        if (tab.type !== 'item') return tab;
        if (tab.path === from) return { ...tab, path: to };
        if (tab.path.startsWith(`${from}/`)) return { ...tab, path: to + tab.path.slice(from.length) };
        return tab;
      }),
    );
    setPinned((keys) => [...new Set(keys.map(remapKey))]);
    setActive((key) => (key ? remapKey(key) : null));
    setStatus((all) => Object.fromEntries(Object.entries(all).map(([key, value]) => [remapKey(key), value])));
    setFormDirty((keys) => [...new Set(keys.map(remapKey))]);
  }, []);

  useServerEvents(true, (event) => {
    if (event.type === 'job') {
      qc.setQueryData<Job[]>(['jobs'], (list = []) => {
        const others = list.filter((j) => j.id !== event.data.id);
        return [event.data, ...others];
      });
      if (event.data.status === 'failed') toast({ text: `${event.data.title}: ${event.data.error?.text ?? ''}`, tone: 'error' });
    } else if (event.type === 'notice') {
      const draft = event.data.result?.draft;
      toast({
        text: event.data.text,
        action: draft ? { label: t('review.open'), run: () => open({ type: 'review', draft }) } : undefined,
      });
    } else if (event.type === 'draft') {
      qc.invalidateQueries({ queryKey: ['drafts', workId] });
      qc.invalidateQueries({ queryKey: ['drafts-all', workId] });
    } else if (event.type === 'lock') {
      onLock();
    }
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        setQuickOpen(true);
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'l') {
        e.preventDefault();
        lock();
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'f') {
        e.preventDefault();
        setPanel('search');
      } else if (e.ctrlKey && e.key.toLowerCase() === 'w' && active) {
        e.preventDefault();
        close(active);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const unsavedTabs = tabs.filter((tab) => status[tabKey(tab)]?.dirty || formDirty.includes(tabKey(tab)));
  // Only item text and form can be saved from here; image designs and settings tabs keep their own save buttons.
  const savable = (tab: Tab) => tab.type === 'item' && !!status[tabKey(tab)]?.save && status[tabKey(tab)]?.textOnly !== false && !formDirty.includes(tabKey(tab));
  const guarded = (run: () => Promise<void>) => () => (unsavedTabs.length ? setPending({ run }) : run());

  async function saveAllAndContinue() {
    if (!pending) return;
    setSavingAll(true);
    try {
      for (const tab of unsavedTabs) {
        if (!(await status[tabKey(tab)]!.save!())) {
          setActive(tabKey(tab));
          toast({ text: t('leave.save_failed', { name: tabTitle(tab) ?? '' }), tone: 'error' });
          return;
        }
      }
      const run = pending.run;
      setPending(null);
      await run();
    } finally {
      setSavingAll(false);
    }
  }

  // Closing a work keeps a save point of what changed since the last snapshot (09-snapshots).
  const leave = guarded(async () => {
    await post(`/api/works/${workId}/snapshots/save-point`).catch(() => undefined);
    onLeave();
  });

  const lock = guarded(async () => {
    await post(`/api/works/${workId}/snapshots/save-point`).catch(() => undefined);
    await post('/api/auth/lock');
    onLock();
  });

  const current = tabs.find((tab) => tabKey(tab) === active) ?? null;
  const currentStatus = active ? status[active] : undefined;
  const effective = info.data?.effective;
  const limits = effective?.values?.limits ?? {};
  const running = (jobs.data ?? []).filter((j) => j.status === 'queued' || j.status === 'running');
  const pendingDrafts = drafts.data?.length ?? 0;

  const sizeLimit = useMemo(() => {
    if (!currentStatus) return null;
    const key = currentStatus.kind === 'main' ? 'main' : 'lorebook_entry';
    return limits?.[key]?.max ?? null;
  }, [currentStatus, limits]);

  if (!info.data) return null;

  const image = (view: ImageView) => () => {
    setTesting(false);
    open({ type: 'image', view });
  };
  const startJob = (url: string, message: string) => () => {
    setLlm(undefined);
    setLlmJob({ url, message });
  };
  const runLlmJob = async () => {
    if (!llmJob || llmBusy) return;
    setLlmBusy(true);
    try {
      await post(llmJob.url, { llm });
      toast({ text: llmJob.message });
      setLlmJob(null);
    } catch (err) {
      toast({ text: err instanceof ApiError ? tm(err.msg) : String(err), tone: 'error' });
    } finally { setLlmBusy(false); }
  };
  const menus: Menu[] = [
    {
      label: t('menu.work'),
      items: [
        { label: t('window.work_settings'), run: () => open({ type: 'work-settings' }) },
        { label: t('window.export'), run: () => setExporting(true) },
        {
          label: t('history.manual'),
          run: async () => {
            await post(`/api/works/${workId}/snapshots`, { reason: 'manual' });
            qc.invalidateQueries({ queryKey: ['snapshots', workId] });
            toast({ text: t('history.created') });
          },
        },
        null,
        { label: t('window.back_to_works'), run: leave },
        { label: t('common.lock'), shortcut: 'Ctrl+Shift+L', run: lock },
      ],
    },
    {
      label: t('menu.edit'),
      items: [
        { label: t('editor.quick_open'), shortcut: 'Ctrl+P', run: () => setQuickOpen(true) },
        { label: t('panel.search'), shortcut: 'Ctrl+Shift+F', run: () => setPanel('search') },
        { label: t('rename.title'), run: () => setRenaming(true) },
      ],
    },
    {
      label: t('menu.tools'),
      items: [
        { label: t('authoring.title'), run: () => setAuthoring(true) },
        { label: t('panel.relations'), run: () => open({ type: 'relations' }) },
        { label: t('panel.glossary'), run: () => open({ type: 'glossary' }) },
        null,
        { label: t('relations.extract'), run: startJob(`/api/works/${workId}/relations/extract`, t('relations.extract_started')) },
        { label: t('consistency.run'), run: startJob(`/api/works/${workId}/consistency`, t('consistency.started')) },
      ],
    },
    {
      label: t('menu.image'),
      items: [
        { label: t('image_menu.library'), run: image('library') },
        { label: t('image_menu.board'), run: image('board') },
        null,
        { label: t('image_menu.generate'), run: image('generate') },
        { label: t('image_menu.queue'), run: image('queue') },
        { label: t('image_menu.lab'), run: image('lab') },
        null,
        { label: t('image_menu.gallery'), run: image('gallery') },
        { label: t('image_menu.tools'), run: image('tools') },
        { label: t('image_menu.lora'), run: image('lora') },
      ],
    },
    { label: t('menu.help'), items: help.entries },
  ];

  return (
    <div className="window">
      <div className="topbar" style={{ position: 'relative' }}>
        <span className="topbar-mark" title="AtelierX">
          <AppMark size={20} />
        </span>
        <span className="title" onClick={leave} title={t('window.back_to_works')}>
          {info.data.name} <Icon name="menu" size={14} />
        </span>
        <MenuBar menus={menus} />
        <button className={testing ? 'primary' : 'ghost'} onClick={() => setTesting(!testing)}>
          {testing ? t('test.back') : t('test.open')}
        </button>
        <span className="grow" />
        <button className="ghost icon-button" onClick={() => setQuickOpen(true)} title={`${t('editor.quick_open')} (Ctrl+P)`} aria-label={t('editor.quick_open')}>
          <Icon name="search" size={18} />
        </button>
        <button className="ghost icon-button" onClick={() => setShowJobs((v) => !v)} title={t('jobs.title')} aria-label={t('jobs.title')}>
          <Icon name="jobs" size={18} />
          {running.length > 0 && <span className="count">{running.length}</span>}
        </button>
        <button className="ghost icon-button" onClick={() => open({ type: 'settings' })} title={t('window.settings')} aria-label={t('window.settings')}>
          <Icon name="settings" size={18} />
        </button>
        <button className="ghost icon-button" onClick={lock} title={`${t('common.lock')} (Ctrl+Shift+L)`} aria-label={t('common.lock')}>
          <Icon name="lock" size={18} />
        </button>
        {showJobs && (
          <JobsPopover jobs={jobs.data ?? []} onClose={() => setShowJobs(false)} openDraft={(draft) => open({ type: 'review', draft })} />
        )}
      </div>
      <div style={{ display: testing ? 'contents' : 'none' }}>
        <ErrorBoundary label={t('test.title')}>
          <TestScreen
            workId={workId}
            openItem={(path) => {
              setTesting(false);
              open({ type: 'item', path });
            }}
          />
        </ErrorBoundary>
      </div>
      <div
        className={`main${aux ? '' : ' no-aux'}`}
        style={{ ['--side' as string]: panel ? '240px' : '0px', display: testing ? 'none' : undefined }}
      >
        <div className="activity">
          {PANELS.map((a) => (
            <button
              key={a.key}
              className={panel === a.key ? 'on' : ''}
              title={t(`panel.${a.key}`)}
              onClick={() => setPanel(panel === a.key ? null : a.key)}
            >
              <Icon name={a.icon} size={20} />
              <span className="label">{t(`panel.${a.key}`)}</span>
              {a.key === 'drafts' && pendingDrafts > 0 && <span className="dot">{pendingDrafts}</span>}
            </button>
          ))}
          <div className="activity-divider" />
          {LAUNCHERS.map((a) => (
            <button key={a.tab} className="launcher" title={t('activity.open_tab', { name: t(`panel.${a.tab}`) })} onClick={() => open({ type: a.tab })}>
              <Icon name={a.icon} size={20} />
              <span className="label">{t(`panel.${a.tab}`)}</span>
            </button>
          ))}
          <span className="grow" />
          <button className={aux ? 'on' : ''} title={t('aux.toggle')} onClick={() => setAux(aux ? null : 'check')}>
            <Icon name="aux" size={20} />
            <span className="label">{t('aux.toggle')}</span>
          </button>
        </div>
        <div className="side">
          {panel && (
            <Panels
              panel={panel}
              workId={workId}
              info={info.data}
              activePath={current?.type === 'item' ? current.path : null}
              open={open}
              closeKey={close}
              renamePath={renamePath}
            />
          )}
        </div>
        <div className="editor-area">
          <div className="tabs">
            {tabs.map((tab) => {
              const key = tabKey(tab);
              return (
                <div
                  key={key}
                  className={`tab${key === active ? ' on' : ''}`}
                  onClick={() => setActive(key)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setTabMenu({ key, x: e.clientX, y: e.clientY });
                  }}
                >
                  {pinned.includes(key) && <span className="pin" title={t('tabs.pin')}><Icon name="pin" size={13} /></span>}
                  <span className="tab-title">{tabTitle(tab)}</span>
                  {status[key]?.dirty && <span className="dirty" title={t('status.unsaved')}>●</span>}
                  <button
                    className="x"
                    aria-label={t('tabs.close')}
                    onClick={(e) => {
                      e.stopPropagation();
                      close(key);
                    }}
                  >
                    <Icon name="close" size={14} />
                  </button>
                </div>
              );
            })}
          </div>
          {tabMenu && <ContextMenu x={tabMenu.x} y={tabMenu.y} items={tabMenuItems(tabMenu.key)} onClose={() => setTabMenu(null)} />}
          <div className="tab-body">
            {tabs.length === 0 && <EmptyEditor onQuickOpen={() => setQuickOpen(true)} />}
            {tabs.map((tab) => {
              const key = tabKey(tab);
              return (
                <div
                  key={key}
                  style={{ display: key === active ? 'contents' : 'none' }}
                  onChangeCapture={(event) => {
                    if (!tracksFormChanges(tab)) return;
                    const target = event.target;
                    if (target instanceof HTMLElement && target.matches('input, textarea, select, [contenteditable="true"]')) {
                      setFormDirty((dirty) => dirty.includes(key) ? dirty : [...dirty, key]);
                    }
                  }}
                >
                  <ErrorBoundary label={tabTitle(tab)}>
                    {tab.type === 'item' && (
                      <ItemEditor
                        workId={workId}
                        path={tab.path}
                        info={info.data!}
                        onStatus={(s) => setStatus((all) => ({ ...all, [key]: s }))}
                        onReview={(draft) => open({ type: 'review', draft })}
                        onRenamed={renamePath}
                        onOpen={(path) => open({ type: 'item', path })}
                        onImage={(view: ImageView, characterId?: string, outfitId?: string) => open({ type: 'image', view, characterId, outfitId })}
                      />
                    )}
                    {tab.type === 'work-settings' && <WorkSettings workId={workId} info={info.data!} />}
                      {tab.type === 'settings' && <AppSettings onDirtyChange={(dirty) => {
                        setFormDirty((keys) => dirty ? (keys.includes(key) ? keys : [...keys, key]) : keys.filter((k) => k !== key));
                      }} />}
                    {tab.type === 'review' && <ReviewTab workId={workId} draftId={tab.draft} onDone={() => close(key)} openItem={(path) => open({ type: 'item', path })} />}
                    {tab.type === 'compare' && <CompareTab workId={workId} snapshot={tab.snapshot} />}
                    {tab.type === 'relations' && <RelationsTab workId={workId} openItem={(path) => open({ type: 'item', path })} />}
                    {tab.type === 'glossary' && <GlossaryTab workId={workId} />}
                    {tab.type === 'image' && (
                      <ImageScreen
                        workId={workId}
                        view={tab.view}
                        characterId={tab.characterId}
                        outfitId={tab.outfitId}
                        openView={(view) => open({ type: 'image', view, characterId: tab.characterId, outfitId: tab.outfitId })}
                        openImage={(view, characterId, outfitId) => open({ type: 'image', view, characterId, outfitId })}
                        openItem={(path) => open({ type: 'item', path })}
                      />
                    )}
                  </ErrorBoundary>
                </div>
              );
            })}
          </div>
        </div>
        <div className="aux" style={{ display: aux ? 'flex' : 'none' }}>
          {aux && (
            <AuxPanel
              tab={aux}
              setTab={setAux}
              workId={workId}
              activePath={current?.type === 'item' ? current.path : null}
              openItem={(path) => open({ type: 'item', path })}
              openDraft={(draft) => open({ type: 'review', draft })}
              pendingDrafts={pendingDrafts}
              attach={agentAttach}
              onAttached={() => setAgentAttach(null)}
            />
          )}
        </div>
      </div>
      <div className="statusbar">
        <span>{currentStatus ? (currentStatus.dirty ? t('status.unsaved') : t('status.saved')) : ''}</span>
        {currentStatus && (
          <span
            className={
              sizeLimit && currentStatus.size > sizeLimit ? 'err' : sizeLimit && currentStatus.size > sizeLimit * 0.9 ? 'warn' : ''
            }
          >
            {formatAmount(currentStatus.size, currentStatus.unit, currentStatus.estimated)}
            {sizeLimit ? ` / ${formatAmount(sizeLimit, currentStatus.unit, false)}` : ''}
          </span>
        )}
        <span>{t('status.preset', { name: effective?.linked?.join(', ') || 'generic' })}</span>
        <span className="grow" />
        {running[0] && (
          <span className="row" style={{ gap: 4 }}>
            <Icon name="jobs" size={13} /> {running[0].title} {running[0].progress}%
          </span>
        )}
      </div>
      {quickOpen && <QuickOpen workId={workId} onClose={() => setQuickOpen(false)} onOpen={(path) => open({ type: 'item', path })} />}
      {exporting && <ExportDialog workId={workId} onClose={() => setExporting(false)} openItem={(path) => open({ type: 'item', path })} />}
      {renaming && <RenameDialog workId={workId} renamePath={renamePath} onClose={() => setRenaming(false)} />}
      {llmJob && <Dialog title={t('llm_tools.title')} onClose={() => !llmBusy && setLlmJob(null)} actions={<button className="primary" disabled={llmBusy} onClick={runLlmJob}>{t('llm_tools.run')}</button>}>
        <RunLlmSelector task="consistency" value={llm} onChange={setLlm} disabled={llmBusy} />
      </Dialog>}
      {authoring && <AuthoringDialog workId={workId} onClose={() => setAuthoring(false)} />}
      {help.element}
      {pending && (
        <Dialog
          title={t('leave.title')}
          onClose={() => !savingAll && setPending(null)}
          actions={
            <>
              <button
                className="danger"
                disabled={savingAll}
                onClick={() => {
                  const run = pending.run;
                  setPending(null);
                  run();
                }}
              >
                {t('leave.discard')}
              </button>
              <button className="primary" disabled={savingAll || !unsavedTabs.every(savable)} onClick={saveAllAndContinue}>
                {t('leave.save_all')}
              </button>
            </>
          }
        >
          <p>{t('leave.body')}</p>
          <ul className="col" style={{ gap: 2, margin: 0 }}>
            {unsavedTabs.map((tab) => (
              <li key={tabKey(tab)}>
                {tabTitle(tab)}
                {!savable(tab) && <span className="faint"> — {t('leave.save_there')}</span>}
              </li>
            ))}
          </ul>
        </Dialog>
      )}
    </div>
  );
}

function formatAmount(n: number, unit: EditorStatus['unit'], estimated: boolean) {
  if (unit === 'chars') return t('status.chars', { n: n.toLocaleString() });
  if (unit === 'tokens') return t(estimated ? 'status.tokens_estimated' : 'status.tokens', { n: n.toLocaleString() });
  return formatBytes(n);
}

function tabTitle(tab: Tab) {
  switch (tab.type) {
    case 'item':
      return tab.path.split('/').pop();
    case 'work-settings':
      return t('window.work_settings');
    case 'settings':
      return t('window.settings');
    case 'review':
      return t('review.tab');
    case 'compare':
      return t('history.compare_tab');
    case 'relations':
      return t('panel.relations');
    case 'glossary':
      return t('panel.glossary');
    case 'image':
      return [t(`image_menu.${tab.view}`), tab.characterId, tab.outfitId].filter(Boolean).join(' · ');
    default:
      return '';
  }
}

function EmptyEditor({ onQuickOpen }: { onQuickOpen: () => void }) {
  return (
    <div className="empty">
      <p>{t('editor.empty')}</p>
      <p className="faint">
        Ctrl+P {t('editor.quick_open')} · Ctrl+Shift+F {t('panel.search')} · Ctrl+Shift+L {t('common.lock')}
      </p>
      <button onClick={onQuickOpen}>{t('editor.quick_open')}</button>
    </div>
  );
}
