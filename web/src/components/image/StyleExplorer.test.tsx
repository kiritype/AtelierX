// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, post } from '../../api';
import { t } from '../../i18n';
import { PoolEditor, StyleExplorer } from './StyleExplorer';
import type { PoolItem } from '../../imageTypes';
vi.mock('../../api', async (original) => ({ ...(await original<typeof import('../../api')>()), get: vi.fn(), post: vi.fn() }));
vi.mock('./ImageLab', () => ({ default: () => null, HANDOFF_KEY: 'atelierx-lab-handoff', hasLabHandoff: () => false }));
vi.mock('./GenSettings', () => ({ default: () => null, useCatalog: () => ({ data: { models: ['m'], loras: [] } }) }));
vi.mock('./NovelAISettings', () => ({ default: () => null }));
vi.mock('../Unsaved', () => ({ useUnsaved: vi.fn() }));
let host: HTMLDivElement, root: Root, qc: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  HTMLDialogElement.prototype.showModal = vi.fn();
  vi.mocked(get).mockImplementation(async (url) =>
    url.includes('/artists')
      ? { available: true, total: 80, items: url.includes('offset=50') ? ['second'] : ['first'] }
      : url.includes('/pools')
        ? { revision: 'r', items: [] }
        : [],
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});
async function render(child: React.ReactNode) {
  await act(async () => {
    root.render(<QueryClientProvider client={qc}>{child}</QueryClientProvider>);
    await new Promise((r) => setTimeout(r, 0));
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
}
const button = (text: string) => [...host.querySelectorAll('button')].find((x) => x.textContent === text)!;
async function click(text: string) {
  await act(async () => {
    button(text).click();
    await new Promise((r) => setTimeout(r, 10));
  });
}
it('keeps artist choices across pages and applies an independent copy without saving the global pool', async () => {
  const apply = vi.fn<(x: PoolItem[]) => void>();
  await render(
    <PoolEditor
      kind="artists"
      initial={[]}
      document={{ revision: 'r', items: [] }}
      catalogNames={[]}
      onDocument={vi.fn()}
      onApply={apply}
      onClose={vi.fn()}
    />,
  );
  await act(async () => {
    (host.querySelector('input[type=checkbox]') as HTMLInputElement).click();
  });
  await click(t('explore.next'));
  expect(host.textContent).toContain('second');
  expect(host.textContent).toContain('first');
  await act(async () => {
    ([...host.querySelectorAll('input[type=checkbox]')][0] as HTMLInputElement).click();
  });
  await click(t('explore.use_pool'));
  expect(apply.mock.calls[0][0].map((x) => x.name)).toEqual(['first', 'second']);
  expect(post).not.toHaveBeenCalled();
});
it('starts with comparison and search settings collapsed and never generates automatically', async () => {
  await render(<StyleExplorer openPresets={vi.fn()} />);
  expect(host.querySelectorAll('details')).toHaveLength(2);
  expect([...host.querySelectorAll('details')].every((x) => !x.open)).toBe(true);
  expect(host.textContent).toContain(t('explore.artists'));
  expect(host.textContent).toContain(t('explore.models'));
  expect(host.textContent).toContain(t('explore.loras'));
  expect(post).not.toHaveBeenCalled();
});
