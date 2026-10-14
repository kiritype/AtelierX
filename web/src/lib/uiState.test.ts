import { beforeEach, expect, it, vi } from 'vitest';
import { get, put } from '../api';
import { saveWorkUiState } from './uiState';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn(), put: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

it('skips the write when ui-state cannot be read, then saves on a later successful attempt', async () => {
  vi.mocked(get).mockRejectedValueOnce(new Error('temporary read failure')).mockResolvedValueOnce({
    last_work: 'other-work',
    works: { 'other-work': { tabs: ['other-tab'] }, work: { pinned: ['pin'], sidebar: { future: true } } },
  });
  vi.mocked(put).mockResolvedValue(undefined);
  const changes = { tabs: ['tab'], active: 'tab', pinned: [], sidebar: { collapsed: true, width: 240, folders: {} } };

  await expect(saveWorkUiState('work', changes)).rejects.toThrow('temporary read failure');
  expect(put).not.toHaveBeenCalled();

  await saveWorkUiState('work', changes);
  expect(put).toHaveBeenCalledWith('/api/ui-state', {
    last_work: 'other-work',
    works: {
      'other-work': { tabs: ['other-tab'] },
      work: { pinned: [], tabs: ['tab'], active: 'tab', sidebar: { future: true, collapsed: true, width: 240, folders: {} } },
    },
  });
});
