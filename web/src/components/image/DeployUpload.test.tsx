// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import { DeployUpload } from './DeployUpload';

vi.mock('../../api', () => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));

it('shows deferred candidates, per-file progress, skipped totals and durable history', async () => {
  vi.useFakeTimers();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['deploy-targets'], { targets: [{ id: 'main', name: 'Demo', ready: true, path_format: '{work}', public_url: '' }] });
  qc.setQueryData(['work-deploy', 'W001'], { target: 'main', path_format: '{work}' });
  qc.setQueryData(['image-lib-rules'], { ratings: [] });
  qc.setQueryData(['deploy-history', 'W001'], { records: [{ at: '2026-10-13', target_name: 'Old target', path: 'old.webp', status: 'uploaded' }] });
  const row = { source: 'source.png', path: 'image.webp', status: 'existing', character_id: 'C001', outfit_id: 'o01', expression_id: 'smile' };
  const plan = { rows: [row], counts: { existing: 1 }, missing: [] };
  const run = { id: 'r1', status: 'running', total: 1, done: 0, results: [], current: { source: row.source, path: row.path, status: 'converting' } };
  vi.mocked(post).mockImplementation(async (url) => url.endsWith('/plan') ? plan : run);
  vi.mocked(get).mockImplementation(async (url) => url.includes('/runs/') ? { ...run, status: 'done', done: 1, current: null, results: [{ ...row, status: 'unchanged', ok: true, overwrote: false }] } : { records: [] });
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const fail = vi.fn();
  const click = async (text: string) => {
    const button = [...host.querySelectorAll('button')].find((b) => b.textContent === text)!;
    expect(button).toBeTruthy();
    await act(async () => button.click());
  };
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><DeployUpload scope={{ work: 'W001' }} close={() => {}} fail={fail} /></QueryClientProvider>));
    expect(host.textContent).toContain('old.webp');
    await click(t('deploy.preview'));
    expect(host.textContent).toContain(t('deploy.status.existing'));
    await click(t('deploy.upload_candidates', { n: 1, m: 1 }));
    expect(host.querySelector('tbody')?.textContent).toContain(t('deploy.status.converting'));
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(host.querySelector('tbody')?.textContent).toContain(t('deploy.status.unchanged'));
    expect(host.textContent).toContain(t('deploy.skipped', { n: 1 }));
    expect(fail).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    qc.clear();
    host.remove();
    vi.useRealTimers();
  }
});
