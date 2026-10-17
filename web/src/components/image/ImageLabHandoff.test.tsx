// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from '../../api';
import ImageLab, { sendToLab } from './ImageLab';

vi.mock('../Toasts', () => ({ useToast: () => () => {} }));
vi.mock('./LabImport', () => ({ default: () => null }));
vi.mock('./GenSettings', async original => ({ ...await original<typeof import('./GenSettings')>(),
  default: () => null, useCatalog: () => ({ data: { connected: true, loras: [], defaults: {} } }),
}));
vi.mock('../../api', async original => ({ ...await original<typeof import('../../api')>(),
  get: vi.fn(async (url: string) => url.endsWith('/runs') ? { runs: [] } : []),
}));

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;
const render = async (active: boolean) => act(async () => root.render(
  <QueryClientProvider client={client}>
    <ImageLab key="hidden" workId="other" active={false} />
    <ImageLab key="target" workId="target" active={active} />
  </QueryClientProvider>,
));

beforeEach(() => {
  vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/runs') ? { runs: [] } as never : [] as never);
  localStorage.clear(); sessionStorage.clear();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); });

it('keeps a handoff for the lab tab that becomes active', async () => {
  await render(false);
  sendToLab({ positive: 'saved final prompt', negative: 'blur', settings: { family: 'anima', seed: 42 } });
  expect(sessionStorage.getItem('atelierx-lab-handoff')).toContain('saved final prompt');
  await render(true);
  const prompts = [...host.querySelectorAll<HTMLTextAreaElement>('textarea[rows="5"]')];
  expect(prompts).toHaveLength(2);
  expect(prompts[0].value).toBe('');
  expect(prompts[1].value).toBe('saved final prompt');
  expect(sessionStorage.getItem('atelierx-lab-handoff')).toBeNull();
});

it('shows regenerated results in the original comparison cell', async () => {
  vi.mocked(get).mockImplementation(async (url: string) => url.endsWith('/runs') ? { runs: [{
    id: 'run-1', created_at: '2026-10-17T00:00:00Z', rows: 1, columns: 1,
    cells: [{ row: 0, column: 0, seed: 11, status: 'done', image_url: '/original.png', path: '_lab/original.png',
      regenerations: [{ seed: 22, status: 'done', image_url: '/regenerated.png', path: '_lab/regenerated.png', job_id: 'retry-1' }],
    }],
  }] } as never : [] as never);
  await render(true);
  await vi.waitFor(() => expect(host.querySelector<HTMLImageElement>('.lab-regeneration img')?.getAttribute('src')).toBe('/regenerated.png'));
  const again = host.querySelector<HTMLImageElement>('.lab-regeneration img');
  expect(host.querySelector<HTMLImageElement>('.lab-cell > img')?.getAttribute('src')).toBe('/original.png');
  await act(async () => again?.click());
  expect(host.querySelector<HTMLImageElement>('.lab-figure:nth-child(2) img')?.getAttribute('src')).toBe('/regenerated.png');
});
