// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import ImageQueue from './ImageQueue';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

it('shows resolved names and keeps job IDs for queue actions', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/image/queue') return { paused: false, gpu: { label: '', state_label: null, waiting: null }, jobs: [
      { id: 'job-one', status: 'queued', work_id: 'W001', character_id: 'C001', outfit_id: 'o01', expression_id: 'e01', created_at: '2026-10-18', seed: null },
      { id: 'job-two', status: 'queued', work_id: 'W001', character_id: 'C999', outfit_id: 'o01', expression_id: 'e01', created_at: '2026-10-18', seed: null },
    ] };
    if (url === '/api/works') return { works: [{ id: 'W001', name: 'Demo work' }] };
    if (url === '/api/works/W001/image/designs') return [{ id: 'C001', name: 'Mira', outfits: [{ id: 'o01', name: 'Uniform' }] }];
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.mocked(post).mockResolvedValue({});
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ImageQueue /></QueryClientProvider>); });
    for (let attempt = 0; attempt < 10 && !host.textContent?.includes('Demo work · Mira'); attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    }
    expect(host.textContent).toContain('Demo work · Mira');
    expect(host.textContent).toContain('Demo work · C999');
    expect(host.querySelector('[title="W001 · C001"]')).not.toBeNull();
    await act(async () => (host.querySelector('.queue-row button') as HTMLButtonElement).click());
    expect(post).toHaveBeenCalledWith('/api/image/jobs/job-one/cancel');
  } finally {
    await act(async () => root.unmount()); qc.clear(); host.remove();
  }
});
