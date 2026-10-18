// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get } from '../../api';
import ToolBatches from './ToolBatches';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn() }));

it('shows batch context and filenames while retaining target IDs', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem('atelierx.tools.batches.open', 'true');
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/image/tools/batches') return { batches: [{ id: 'opaque-batch', operation: 'tag', created_at: '2026-10-18T12:00:00', total: 2, accepted: 2, progress: 0, paused: false, cancelled: false, counts: { pending: 2, queued: 0, running: 0, cancelling: 0, done: 0, failed: 0, cancelled: 0, interrupted: 0 } }], running_count: 2, failed_count: 0 };
    if (url.startsWith('/api/image/tools/batches/')) return { items: [
      { ordinal: 0, status: 'pending', target: { id: 'opaque-image' }, display_name: 'portrait upload.png', thumbnail_url: '/thumb' },
      { ordinal: 1, status: 'pending', target: { id: 'W001/C001/images/o01/portrait.png', source: true }, display_name: 'portrait.png', thumbnail_url: '/gallery-thumb' },
    ] };
    throw new Error(`Unexpected request: ${url}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ToolBatches active fail={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
    expect(host.textContent).toContain('2026');
    await act(async () => (host.querySelector('details button') as HTMLButtonElement).click());
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
    expect(host.textContent).toContain('portrait upload.png');
    expect(host.textContent).toContain('portrait.png');
    expect(host.querySelector('[title="opaque-image"]')).not.toBeNull();
  } finally {
    await act(async () => root.unmount()); qc.clear(); host.remove(); localStorage.removeItem('atelierx.tools.batches.open');
  }
});
