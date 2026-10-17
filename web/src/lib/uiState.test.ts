import { beforeEach, expect, it, vi } from 'vitest';
import { patch } from '../api';
import { saveWorkUiState } from './uiState';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), patch: vi.fn() }));

beforeEach(() => vi.clearAllMocks());

it('sends only the selected work state for an atomic server merge', async () => {
  vi.mocked(patch).mockResolvedValue({});
  const changes = { tabs: ['tab'], active: 'tab', sidebar: { collapsed: true } };
  await saveWorkUiState('work', changes);
  expect(patch).toHaveBeenCalledWith('/api/ui-state', { works: { work: changes } });
});
