import { patch } from '../api';

// Merge this work on the server so another window's state cannot be overwritten by a stale read.
export async function saveWorkUiState(workId: string, changes: Record<string, unknown>) {
  await patch('/api/ui-state', { works: { [workId]: changes } });
}
