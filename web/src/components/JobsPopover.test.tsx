// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import JobsPopover from './JobsPopover';

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;

beforeEach(() => {
  vi.useFakeTimers();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  qc.setQueryData(['activity'], { items: [{ kind: 'image_queue', status: 'running', counts: { running: 1 } }] });
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.useRealTimers();
});

it('removes delayed outside-click listeners when the popover closes before registration', async () => {
  const onClose = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <JobsPopover jobs={[]} onClose={onClose} openDraft={() => {}} openView={() => {}} />
  </QueryClientProvider>));
  await act(async () => root.render(<QueryClientProvider client={qc}><div>Closed</div></QueryClientProvider>));
  await act(async () => vi.advanceTimersByTime(1));
  document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  expect(onClose).not.toHaveBeenCalled();
});

it('opens the queue through a real pointer event sequence and closes the popover', async () => {
  const onClose = vi.fn();
  const openView = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <JobsPopover jobs={[]} onClose={onClose} openDraft={() => {}} openView={openView} />
  </QueryClientProvider>));
  await act(async () => vi.advanceTimersByTime(1));
  const button = host.querySelector<HTMLButtonElement>('.popover button')!;
  await act(async () => {
    button.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    button.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
  expect(openView).toHaveBeenCalledWith('queue', undefined);
  expect(onClose).toHaveBeenCalledTimes(1);
});

it('keeps the other activity destinations and supports button activation by keyboard', async () => {
  qc.setQueryData(['activity'], { items: [
    { kind: 'install', status: 'running', section: 'comfyui' },
    { kind: 'lora', status: 'running', title: 'Training', character_id: 'C001' },
    { kind: 'convert', status: 'running', done: 1, total: 2 },
    { kind: 'deploy', status: 'running', title: 'Upload', done: 1, total: 2 },
  ] });
  const openView = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={qc}>
    <JobsPopover jobs={[]} onClose={() => {}} openDraft={() => {}} openView={openView} />
  </QueryClientProvider>));
  const buttons = host.querySelectorAll<HTMLButtonElement>('.popover button');
  for (const button of buttons) {
    button.focus();
    await act(async () => button.click());
  }
  expect(openView.mock.calls).toEqual([
    ['settings', undefined], ['lora', 'C001'], ['tools', undefined], ['gallery', undefined],
  ]);
});
