// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import ToolBatches from './ToolBatches';

vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(), get: vi.fn(), post: vi.fn() }));

it('starts with a compact status, opens a submitted job, and clears only completed history', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.removeItem('atelierx.tools.batches.open');
  const counts = (pending: number, done: number) => ({ pending, queued: 0, running: 0, cancelling: 0, done, failed: 0, cancelled: 0, interrupted: 0 });
  const running = { id: 'running-id', operation: 'tag', total: 2, accepted: 2, progress: 0.5, created_at: '', counts: counts(1, 1), paused: false, cancelled: false };
  const complete = { ...running, id: 'complete-id', counts: counts(0, 2), progress: 1 };
  let cleared = false;
  vi.mocked(get).mockImplementation(async url => url.includes('/batches/') ? { items: [] } : { batches: cleared ? [running] : [complete, running] });
  vi.mocked(post).mockImplementation(async () => { cleared = true; return { cleared: 1 }; });
  const confirmBefore = window.confirm;
  window.confirm = vi.fn(() => true);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const host = document.createElement('div'); document.body.append(host); const root = createRoot(host);
  try {
    await act(async () => { root.render(<QueryClientProvider client={qc}><ToolBatches active fail={() => {}} /></QueryClientProvider>); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 10)); });
    const sections = host.querySelectorAll('details');
    expect(sections).toHaveLength(2);
    expect(sections[0].open).toBe(false);
    expect(sections[0].querySelector('summary')?.getAttribute('aria-expanded')).toBe('false');
    expect(sections[0].textContent).toContain('1');
    await act(async () => window.dispatchEvent(new CustomEvent('tool-batch-focus', { detail: complete.id })));
    expect(sections[1].open).toBe(true);
    expect(sections[1].querySelector('summary')?.getAttribute('aria-expanded')).toBe('true');
    await act(async () => window.dispatchEvent(new CustomEvent('tool-batch-focus', { detail: running.id })));
    expect(sections[0].open).toBe(true);
    expect(sections[0].querySelector('summary')?.getAttribute('aria-expanded')).toBe('true');
    const clearButton = [...sections[1].querySelectorAll('button')].find(button => button.textContent?.includes('Clear') || button.textContent?.includes('비우기'))!;
    await act(async () => { clearButton.click(); await new Promise(resolve => setTimeout(resolve, 10)); });
    expect(vi.mocked(post)).toHaveBeenCalledWith('/api/image/tools/batches/clear-completed', {});
    expect(host.querySelectorAll('details')).toHaveLength(1);
  } finally {
    window.confirm = confirmBefore;
    await act(async () => root.unmount()); qc.clear(); host.remove();
  }
});
