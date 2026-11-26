import { useQuery, useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { ApiError, get, patch, post, setConsentHandler, setUnauthorizedHandler } from './api';
import { useHelp, useStartupUpdateCheck, useUpdateResult } from './components/Help';
import { Toasts, ToastProvider, useToast } from './components/Toasts';
import TooltipLayer from './components/TooltipLayer';
import { setLanguage, t, tm } from './i18n';
import FirstRun from './screens/FirstRun';
import Lock from './screens/Lock';
import StartScreen from './screens/StartScreen';
import WorkSelect from './screens/WorkSelect';
import { Loading } from './components/ui';
import PasswordSuggest from './components/PasswordSuggest';
import { AppThemeProvider } from './AppTheme';
import type { GlobalToolsView } from './lib/imageNavigation';
import type { GeneralSettings, ThemePreference } from './types';

type Status = {
  initialized: boolean;
  unlocked: boolean;
  language: string;
  theme: ThemePreference;
  wait: number;
  password_change_suggested?: boolean;
};

// Load the editor and image tools only when they are opened.
const WorkWindow = lazy(() => import('./screens/WorkWindow'));
const GlobalToolsWindow = lazy(() => import('./screens/GlobalToolsWindow'));

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  // Unlocked with a password shorter than new ones may be (#82): suggest changing it, once per unlock.
  const [suggestPassword, setSuggestPassword] = useState(false);
  const queryClient = useQueryClient();
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: () => get<GeneralSettings>('/api/settings'),
    enabled: status?.unlocked === true,
  });

  const refresh = useCallback(async () => {
    const value = await get<Status>('/api/auth/status');
    setLanguage(value.language);
    setStatus(value);
    setSuggestPassword(!!value.unlocked && !!value.password_change_suggested);
  }, []);

  useEffect(() => {
    refresh();
    setUnauthorizedHandler(() => {
      queryClient.clear();
      setStatus(current => current && { ...current, unlocked: false });
      refresh();
    });
    setConsentHandler(async (msg, url) => {
      const workId = /^\/api\/works\/([^/]+)/.exec(url)?.[1];
      const provider = String(msg.values?.provider ?? '');
      if (!workId || !provider || !confirm(`${tm(msg)}\n\n${t('llm.consent_question')}`)) return false;
      const work = await get(`/api/works/${workId}`);
      const consent: string[] = work.doc.llm_consent ?? [];
      await patch(`/api/works/${workId}`, { llm_consent: [...new Set([...consent, provider])] });
      queryClient.invalidateQueries({ queryKey: ['work', workId] });
      return true;
    });
  }, [refresh, queryClient]);

  if (!status) return null;
  return (
    <AppThemeProvider preference={(status.unlocked ? settings.data?.theme : undefined) ?? status.theme ?? 'system'}>
      <ToastProvider>
        {!status.initialized ? <FirstRun onDone={refresh} /> : !status.unlocked ? <Lock wait={status.wait} onDone={refresh} /> :
          <UnlockedWorkspace onLock={refresh} checkForUpdates={!!settings.data?.update_check_on_start} />}
        {suggestPassword && <PasswordSuggest onClose={() => setSuggestPassword(false)} />}
        <Toasts />
        <TooltipLayer />
      </ToastProvider>
    </AppThemeProvider>
  );
}

type Page = { type: 'home' } | { type: 'works' } | { type: 'work'; id: string };

function UnlockedWorkspace({ onLock, checkForUpdates }: { onLock: () => Promise<void>; checkForUpdates: boolean }) {
  const [page, setPage] = useState<Page>({ type: 'home' });
  const [toolsView, setToolsView] = useState<GlobalToolsView | null>(null);
  const openExplorer = useCallback(() => setToolsView('explorer'), []);
  const help = useHelp();
  const toast = useToast();
  useStartupUpdateCheck(checkForUpdates, help.setUpdateAvailable, help.openUpdate);
  useUpdateResult(help.openUpdate);

  const openWork = async (id: string) => {
    setPage({ type: 'work', id });
    await patch('/api/ui-state', { last_work: id });
  };
  const lock = async () => {
    try {
      await post('/api/auth/lock');
      await onLock();
    } catch (error) {
      toast({ text: error instanceof ApiError ? tm(error.msg) : String(error), tone: 'error' });
    }
  };

  const toolsOpen = toolsView !== null;
  const workId = page.type === 'work' ? page.id : undefined;
  return (
    <>
      <div hidden={toolsOpen} inert={toolsOpen} style={{ display: toolsOpen ? 'none' : 'contents' }} aria-hidden={toolsOpen || undefined}>
        <Suspense fallback={<Loading />}>
          {page.type === 'home' && <StartScreen help={help} onOpenWorks={() => setPage({ type: 'works' })} onOpenTools={setToolsView} onLock={lock} />}
          {page.type === 'works' && <WorkSelect help={help} onOpen={openWork} onOpenTools={setToolsView} onBack={() => setPage({ type: 'home' })} onLock={lock} />}
          {page.type === 'work' && <WorkWindow key={page.id} workId={page.id} help={help} active={!toolsOpen} onOpenTools={openExplorer} onLeave={() => setPage({ type: 'works' })} onLock={onLock} />}
        </Suspense>
      </div>
      {toolsOpen && (
        <Suspense fallback={<Loading />}>
          <GlobalToolsWindow workId={workId} initialView={toolsView} backLabel={page.type === 'home' ? t('start.back') : undefined} onClose={() => setToolsView(null)} onLock={workId ? undefined : lock} />
        </Suspense>
      )}
      {help.element}
    </>
  );
}
