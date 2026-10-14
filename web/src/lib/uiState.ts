import { get, put } from '../api';

type UiState = { works?: Record<string, Record<string, unknown>>; [key: string]: unknown };

// Preserve the rest of the app's UI state. If reading it fails, reject without replacing it with a partial document.
export async function saveWorkUiState(workId: string, changes: Record<string, unknown>) {
  const state = await get<UiState>('/api/ui-state');
  if (!state || typeof state !== 'object' || Array.isArray(state)) return;
  const savedWork = state.works?.[workId] ?? {};
  const savedSidebar = savedWork.sidebar;
  const changedSidebar = changes.sidebar;
  const nextWork = {
    ...savedWork,
    ...changes,
    ...(savedSidebar && typeof savedSidebar === 'object' && changedSidebar && typeof changedSidebar === 'object'
      ? { sidebar: { ...savedSidebar, ...changedSidebar } }
      : {}),
  };
  await put('/api/ui-state', {
    ...state,
    works: {
      ...(state.works ?? {}),
      [workId]: nextWork,
    },
  });
}
