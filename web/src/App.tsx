import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import { get, patch, put, setConsentHandler, setUnauthorizedHandler } from './api';
import { Toasts, ToastProvider } from './components/Toasts';
import { setLanguage, t, tm } from './i18n';
import FirstRun from './screens/FirstRun';
import Lock from './screens/Lock';
import WorkSelect from './screens/WorkSelect';
import WorkWindow from './screens/WorkWindow';

type Status = { initialized: boolean; unlocked: boolean; language: string; wait: number };

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [workId, setWorkId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const refresh = useCallback(async () => {
    const value = await get<Status>('/api/auth/status');
    setLanguage(value.language);
    setStatus(value);
  }, []);

  useEffect(() => {
    refresh();
    setUnauthorizedHandler(() => {
      queryClient.clear();
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
    const state = await get('/api/ui-state').catch(() => ({}));
    await put('/api/ui-state', { ...state, last_work: id ?? state.last_work });
  }, []);

  if (!status) return null;
  let screen;
  if (!status.initialized) screen = <FirstRun onDone={refresh} />;
  else if (!status.unlocked) screen = <Lock wait={status.wait} onDone={refresh} />;
  else if (!workId) screen = <WorkSelect onOpen={openWork} onLock={refresh} />;
  else screen = <WorkWindow key={workId} workId={workId} onLeave={() => setWorkId(null)} onLock={refresh} />;

  return (
    <ToastProvider>
      {screen}
      <Toasts />
    </ToastProvider>
  );
}
