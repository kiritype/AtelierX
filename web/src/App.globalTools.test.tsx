// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { get, patch } from './api';
import App from './App';

vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), get: vi.fn(), patch: vi.fn() }));
vi.mock('./screens/WorkSelect', () => ({ default: ({ onOpen, onOpenTools }: { onOpen: (id: string) => void; onOpenTools: () => void }) => <>
  <button onClick={onOpenTools}>Tools from works</button>
  <button onClick={() => onOpen('story')}>Open story</button>
</> }));
vi.mock('./screens/WorkWindow', () => ({ default: ({ active, onOpenTools }: { active: boolean; onOpenTools: () => void }) => {
  const [edits, setEdits] = useState(0);
  return <><button onClick={onOpenTools}>Tools from work</button><button onClick={() => setEdits(edits + 1)}>Edit {edits}</button><span data-work-active={active} /></>;
} }));
vi.mock('./screens/GlobalToolsWindow', () => ({ default: ({ onClose }: { onClose: () => void }) => <button onClick={onClose}>Back from Tools</button> }));

it('opens Tools from both places and preserves the mounted work editor on return', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.mocked(get).mockImplementation(async url => url === '/api/auth/status'
    ? { initialized: true, unlocked: true, language: 'ko', theme: 'light', wait: 0 }
    : {});
  vi.mocked(patch).mockResolvedValue({});
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const click = async (label: string) => {
    const button = [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === label)!;
    await act(async () => button.click());
  };
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><App /></QueryClientProvider>));
    await click('Tools from works');
    expect(host.textContent).toContain('Back from Tools');
    await click('Back from Tools');
    await click('Open story');
    await click('Edit 0');
    await click('Tools from work');
    expect(host.querySelector('[data-work-active]')?.getAttribute('data-work-active')).toBe('false');
    expect(host.querySelector('[data-work-active]')?.closest('[hidden]')).toBeTruthy();
    await click('Back from Tools');
    expect(host.querySelector('[data-work-active]')?.getAttribute('data-work-active')).toBe('true');
    expect(host.textContent).toContain('Edit 1');
  } finally {
    await act(async () => root.unmount());
    qc.clear();
    host.remove();
    vi.clearAllMocks();
  }
});
