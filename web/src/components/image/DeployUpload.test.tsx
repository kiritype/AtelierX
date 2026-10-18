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
  vi.mocked(get).mockImplementation(async (url) => url.includes('/runs/') ? { ...run, status: 'done', done: 1, current: null, results: [{ ...row, status: 'unchanged', ok: true, overwrote: false, url: 'https://example.com/actual.webp' }] } : { records: [] });
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
    const path = host.querySelector('.deploy-preview-list input') as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(path, 'changed.webp');
      path.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect((([...host.querySelectorAll('button')].find((b) => b.textContent?.includes('올릴 후보')) as HTMLButtonElement).disabled)).toBe(true);
    await click(t('deploy.preview_again'));
    expect(vi.mocked(post)).toHaveBeenLastCalledWith('/api/image/deploy/plan', expect.objectContaining({ paths: { 'source.png': 'changed.webp' } }));
    await click(t('deploy.upload_candidates', { n: 1, m: 1 }));
    expect(vi.mocked(post)).toHaveBeenLastCalledWith('/api/image/deploy/upload', expect.objectContaining({ paths: { 'source.png': 'changed.webp' } }));
    expect(host.querySelector('.deploy-dialog')?.getAttribute('data-stage')).toBe('progress');
    expect(host.textContent).toContain(t('deploy.status.converting'));
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(host.querySelector('.deploy-dialog')?.getAttribute('data-stage')).toBe('result');
    expect(host.querySelector('.deploy-result-list')?.textContent).toContain('https://example.com/actual.webp');
    expect(host.querySelector('.deploy-preview-list')).toBeNull();
    expect(host.textContent).toContain(t('deploy.skipped', { n: 1 }));
    expect(fail).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    qc.clear();
    host.remove();
    vi.useRealTimers();
  }
});

it('locks navigation and prevents a second submission while upload admission is pending', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['deploy-targets'], { targets: [{ id: 'main', name: 'Demo', ready: true, path_format: '{work}', public_url: '' }] });
  qc.setQueryData(['work-deploy', 'W001'], { target: 'main', path_format: '{work}' });
  qc.setQueryData(['image-lib-rules'], { ratings: [] });
  qc.setQueryData(['deploy-history', 'W001'], { records: [] });
  const row = { source: 'source.png', path: 'image.webp', status: 'new', character_id: 'C001', outfit_id: 'o01', expression_id: 'smile' };
  let admit!: (value: unknown) => void;
  const admission = new Promise((resolve) => { admit = resolve; });
  vi.mocked(post).mockImplementation(async (url) => url.endsWith('/plan')
    ? { rows: [row], counts: { new: 1 }, missing: [] } : admission);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host); const close = vi.fn();
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><DeployUpload scope={{ work: 'W001' }} close={close} fail={vi.fn()} /></QueryClientProvider>));
    await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === t('deploy.preview'))!.click());
    const upload = [...host.querySelectorAll('button')].find(b => b.textContent?.includes(t('deploy.upload_candidates', { n: 1, m: 0 }))) as HTMLButtonElement;
    await act(async () => { upload.click(); upload.click(); });
    expect(vi.mocked(post).mock.calls.filter(([url]) => url === '/api/image/deploy/upload')).toHaveLength(1);
    expect(upload.disabled).toBe(true);
    expect((host.querySelector('.deploy-preview-list input') as HTMLInputElement).disabled).toBe(true);
    expect([...host.querySelectorAll('button')].find(b => b.textContent === t('deploy.back_settings'))?.hasAttribute('disabled')).toBe(true);
    await act(async () => (host.querySelector('.overlay') as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true })));
    expect(close).not.toHaveBeenCalled();
    await act(async () => admit({ id: 'run1', status: 'running', total: 1, done: 0, results: [], current: null }));
    expect(host.querySelector('.deploy-dialog')?.getAttribute('data-stage')).toBe('progress');
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});

it('retries only failed paths and ignores a late poll from the cancelled run', async () => {
  vi.useFakeTimers();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['deploy-targets'], { targets: [{ id: 'main', name: 'Demo', ready: true, path_format: '{work}', public_url: '' }] });
  qc.setQueryData(['work-deploy', 'W001'], { target: 'main', path_format: '{work}' });
  qc.setQueryData(['image-lib-rules'], { ratings: [] });
  qc.setQueryData(['deploy-history', 'W001'], { records: [] });
  const row = { source: 'source.png', path: 'image.webp', status: 'new', character_id: 'C001', outfit_id: 'o01', expression_id: 'smile' };
  const failure = { source: 'source.png', path: 'image.webp', url: '', ok: false, overwrote: false, status: 'failed', error: 'test failure' };
  const first = { id: 'run1', status: 'running', total: 1, done: 0, results: [], current: null };
  const cancelled = { ...first, status: 'cancelled', done: 1, results: [failure] };
  const second = { ...first, id: 'run2' };
  let latePoll!: (value: unknown) => void;
  const poll = new Promise((resolve) => { latePoll = resolve; });
  vi.mocked(post).mockImplementation(async (url) => url.endsWith('/plan')
    ? { rows: [row], counts: { new: 1 }, missing: [] }
    : url.endsWith('/cancel') ? cancelled
      : vi.mocked(post).mock.calls.filter(([called]) => called === '/api/image/deploy/upload').length === 1 ? first : second);
  vi.mocked(get).mockImplementation(async (url) => url.includes('/runs/run1') ? poll : { records: [] });
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const click = async (label: string) => act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === label)!.click());
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><DeployUpload scope={{ work: 'W001' }} close={() => {}} fail={vi.fn()} /></QueryClientProvider>));
    await click(t('deploy.preview'));
    await click(t('deploy.upload_candidates', { n: 1, m: 0 }));
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    await click(t('common.cancel'));
    await click(t('deploy.retry_failed'));
    expect(vi.mocked(post)).toHaveBeenLastCalledWith('/api/image/deploy/upload', expect.objectContaining({ only: ['image.webp'], work: 'W001' }));
    await act(async () => latePoll({ ...first, status: 'done', done: 1, results: [] }));
    expect(host.querySelector('.deploy-dialog')?.getAttribute('data-stage')).toBe('progress');
    expect(host.textContent).toContain('0/1');
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); vi.useRealTimers(); }
});

it('honors returning to settings while a refreshed preview is still pending', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['deploy-targets'], { targets: [{ id: 'main', name: 'Demo', ready: true, path_format: '{work}', public_url: '' }] });
  qc.setQueryData(['work-deploy', 'W001'], { target: 'main', path_format: '{work}' });
  qc.setQueryData(['image-lib-rules'], { ratings: [] });
  qc.setQueryData(['deploy-history', 'W001'], { records: [] });
  const plan = { rows: [], counts: {}, missing: [] };
  let finishPreview!: (value: unknown) => void;
  const delayed = new Promise((resolve) => { finishPreview = resolve; });
  let previews = 0;
  vi.mocked(post).mockImplementation(async () => ++previews === 1 ? plan : delayed);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const click = async (label: string) => act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === label)!.click());
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><DeployUpload scope={{ work: 'W001' }} close={() => {}} fail={vi.fn()} /></QueryClientProvider>));
    await click(t('deploy.preview'));
    await click(t('deploy.preview_again'));
    await click(t('deploy.back_settings'));
    await act(async () => finishPreview(plan));
    expect(host.querySelector('.deploy-dialog')?.getAttribute('data-stage')).toBe('settings');
  } finally { await act(async () => root.unmount()); qc.clear(); host.remove(); }
});
