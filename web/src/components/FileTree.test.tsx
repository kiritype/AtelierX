// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from '../api';
import { t } from '../i18n';
import type { TreeEntry } from '../types';
import FileTree from './FileTree';

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), get: vi.fn() }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
const entries: TreeEntry[] = [{ type: 'folder', path: 'People', name: 'People', children: [
  { type: 'item', path: 'People/character.md', name: 'character.md', kind: 'character' },
] }];
const open = vi.fn();
const onCollapse = vi.fn();

function Harness() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  return <FileTree workId="work" activePath={null} collapsed={collapsed} setCollapsed={setCollapsed} onCollapse={onCollapse}
    open={open} renamePath={() => {}} closeKey={() => {}} />;
}

async function settle() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

beforeEach(async () => {
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['tree', 'work'], entries);
  vi.mocked(get).mockResolvedValue(entries);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<QueryClientProvider client={qc}><Harness /></QueryClientProvider>));
  await settle();
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});

it('collapses folders independently from the whole explorer and supports keyboard control', async () => {
  const folder = () => host.querySelector<HTMLElement>('[role="treeitem"]');
  expect(folder()?.getAttribute('aria-expanded')).toBe('true');
  const collapseAll = [...host.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.getAttribute('aria-label') === t('tree.collapse_all'));
  expect(collapseAll).toBeTruthy();
  await act(async () => collapseAll!.click());
  expect(folder()?.getAttribute('aria-expanded')).toBe('false');
  expect(host.textContent).not.toContain('character.md');

  await act(async () => folder()!.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true })));
  expect(folder()?.getAttribute('aria-expanded')).toBe('true');
  const file = [...host.querySelectorAll<HTMLElement>('[role="treeitem"]')].find((row) => row.textContent?.includes('character.md'))!;
  await act(async () => file.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })));
  expect(open).toHaveBeenCalledWith({ type: 'item', path: 'People/character.md' });

  const collapsePanel = host.querySelector<HTMLButtonElement>('[data-sidebar-collapse]');
  expect(collapsePanel?.getAttribute('aria-expanded')).toBe('true');
  await act(async () => collapsePanel!.click());
  expect(onCollapse).toHaveBeenCalledOnce();
});
