import { useQuery, useQueryClient } from '@tanstack/react-query';
import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { get, patch, setConsentHandler, setUnauthorizedHandler } from './api';
import { Toasts, ToastProvider } from './components/Toasts';
import TooltipLayer from './components/TooltipLayer';
import { setLanguage, t, tm } from './i18n';
import FirstRun from './screens/FirstRun';
import Lock from './screens/Lock';
import WorkSelect from './screens/WorkSelect';
import { Loading } from './components/ui';
import PasswordSuggest from './components/PasswordSuggest';
import { AppThemeProvider } from './AppTheme';
import type { GeneralSettings, ThemePreference } from './types';

type Status = {
  initialized: boolean;
  unlocked: boolean;
  language: string;
  theme: ThemePreference;
  wait: number;
  password_change_suggested?: boolean;
};

// The work window and everything in it are read when a work opens (#83): the lock and work list stay small.
const WorkWindow = lazy(() => import('./screens/WorkWindow'));
const GlobalToolsWindow = lazy(() => import('./screens/GlobalToolsWindow'));

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [workId, setWorkId] = useState<string | null>(null);
  const [toolsOpen, setToolsOpen] = useState(false);
  const openTools = useCallback(() => setToolsOpen(true), []);
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
    if (!value.unlocked) setToolsOpen(false);
    setSuggestPassword(!!value.unlocked && !!value.password_change_suggested);
  }, []);

  useEffect(() => {
    refresh();
    setUnauthorizedHandler(() => {
      queryClient.clear();
      setToolsOpen(false);
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

  const openWork = useCallback(async (id: string | null) => {
    setWorkId(id);
    if (id) await patch('/api/ui-state', { last_work: id });
  }, []);

  if (!status) return null;
  let screen;
  if (!status.initialized) screen = <FirstRun onDone={refresh} />;
  else if (!status.unlocked) screen = <Lock wait={status.wait} onDone={refresh} />;
  else if (!workId) screen = <WorkSelect onOpen={openWork} onOpenTools={openTools} onLock={refresh} />;
  else screen = <WorkWindow key={workId} workId={workId} active={!toolsOpen} onOpenTools={openTools} onLeave={() => setWorkId(null)} onLock={refresh} />;

  return (
    <AppThemeProvider preference={(status.unlocked ? settings.data?.theme : undefined) ?? status.theme ?? 'system'}>
      <ToastProvider>
        <div hidden={toolsOpen && status.unlocked} inert={toolsOpen && status.unlocked} style={{ display: toolsOpen && status.unlocked ? 'none' : 'contents' }} aria-hidden={toolsOpen && status.unlocked || undefined}>
          <Suspense fallback={<Loading />}>{screen}</Suspense>
        </div>
        {toolsOpen && status.unlocked && (
          <Suspense fallback={<Loading />}>
            <GlobalToolsWindow workId={workId ?? undefined} onClose={() => setToolsOpen(false)} />
          </Suspense>
        )}
        {suggestPassword && <PasswordSuggest onClose={() => setSuggestPassword(false)} />}
        <Toasts />
        <TooltipLayer />
      </ToastProvider>
    </AppThemeProvider>
  );
}
