// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get, patch, post } from './api';
import App from './App';
import type { HelpNavigation } from './components/Help';
import { t } from './i18n';
import type { GlobalToolsView } from './lib/imageNavigation';

vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), get: vi.fn(), patch: vi.fn(), post: vi.fn() }));
vi.mock('./screens/Lock', () => ({ default: ({ onDone }: { onDone: () => void }) => <button onClick={onDone}>Unlock test app</button> }));
vi.mock('./screens/WorkSelect', () => ({ default: ({ help, onOpen, onOpenTools, onBack }: {
  help: HelpNavigation;
  onOpen: (id: string) => void;
  onOpenTools: (view: GlobalToolsView) => void;
  onBack: () => void;
}) => <div data-works>
  <button onClick={() => onOpenTools('explorer')}>Tools from works</button>
  <button onClick={() => onOpenTools('single')}>Standalone image</button>
  <button onClick={() => onOpenTools('settings')}>App Settings</button>
  <button onClick={() => onOpen('story')}>Open story</button>
  <button onClick={onBack}>Back from works</button>
  {help.updateAvailable && <button onClick={help.openUpdate}>Available update in work list</button>}
</div> }));
vi.mock('./screens/WorkWindow', () => ({ default: ({ active, onOpenTools, onLeave }: { active: boolean; onOpenTools: () => void; onLeave: () => void }) => {
  const [edits, setEdits] = useState(0);
  return <>
    <button onClick={onOpenTools}>Tools from work</button>
    <button onClick={() => setEdits(edits + 1)}>Edit {edits}</button>
    <button onClick={onLeave}>Leave work</button>
    <span data-work-active={active} />
  </>;
} }));
vi.mock('./screens/GlobalToolsWindow', () => ({ default: ({ onClose, onLock, initialView, backLabel }: {
  onClose: () => void;
  onLock?: () => void;
  initialView: string;
  backLabel?: string;
}) => <>
  <button data-view={initialView} onClick={onClose}>{backLabel ?? 'Back from Tools'}</button>
  {onLock && <button onClick={onLock}>Lock from Tools</button>}
</> }));

let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
let unlocked: boolean;

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  unlocked = true;
  vi.mocked(get).mockImplementation(async url => url === '/api/auth/status'
    ? { initialized: true, unlocked, language: 'ko', theme: 'light', wait: 0 }
    : {});
  vi.mocked(patch).mockResolvedValue({});
  vi.mocked(post).mockImplementation(async url => {
    if (url === '/api/auth/lock') unlocked = false;
    return {};
  });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const mount = () => act(async () => root.render(<QueryClientProvider client={qc}><App /></QueryClientProvider>));
const button = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(item =>
  !item.closest('[hidden]') && (item.textContent?.trim() === label || item.querySelector('strong')?.textContent === label));
async function click(label: string) {
  const target = button(label);
  expect(target, label).toBeTruthy();
  await act(async () => target!.click());
}

it('starts at home and returns tools to the origin while keeping the work editor mounted', async () => {
  await mount();
  expect(host.querySelector('[data-works]')).toBeNull();
  await click(t('start.images'));
  expect(host.querySelector('[data-view]')?.getAttribute('data-view')).toBe('single');
  await click(t('start.back'));
  await click(t('works.app_settings'));
  expect(host.querySelector('[data-view]')?.getAttribute('data-view')).toBe('settings');
  expect(patch).not.toHaveBeenCalled();
  await click(t('start.back'));
  await click(t('start.works'));
  expect(button(t('start.images'))).toBeUndefined();
  await click('Standalone image');
  expect(host.querySelector('[data-view]')?.getAttribute('data-view')).toBe('single');
  await click('Back from Tools');
  await click('App Settings');
  expect(host.querySelector('[data-view]')?.getAttribute('data-view')).toBe('settings');
  await click('Back from Tools');
  await click('Tools from works');
  expect(host.querySelector('[data-view]')?.getAttribute('data-view')).toBe('explorer');
  await click('Back from Tools');
  await click('Open story');
  await click('Edit 0');
  await click('Tools from work');
  expect(host.querySelector('[data-work-active]')?.getAttribute('data-work-active')).toBe('false');
  expect(host.querySelector('[data-work-active]')?.closest('[hidden]')).toBeTruthy();
  await click('Back from Tools');
  expect(host.querySelector('[data-work-active]')?.getAttribute('data-work-active')).toBe('true');
  expect(host.textContent).toContain('Edit 1');
  await click('Leave work');
  await click('Back from works');
  expect(button(t('start.works'))).toBeTruthy();
});

it('returns to the start screen after locking and unlocking from standalone tools', async () => {
  await mount();
  await click(t('start.images'));
  await click('Lock from Tools');
  expect(post).toHaveBeenCalledWith('/api/auth/lock');
  expect(host.querySelector('[data-view]')).toBeNull();
  unlocked = true;
  await click('Unlock test app');
  expect(button(t('start.images'))).toBeTruthy();
  expect(host.querySelector('[data-works]')).toBeNull();
});

it('keeps the startup update result available after moving from home into the work list', async () => {
  const major = Number(__APP_VERSION__.split('.')[0]);
  const summary = { current: __APP_VERSION__, latest: [major + 1, 0, 0].join('.'), newer: true };
  let finishCheck!: (result: typeof summary) => void;
  const check = new Promise<typeof summary>(resolve => { finishCheck = resolve; });
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/auth/status') return { initialized: true, unlocked, language: 'ko', theme: 'light', wait: 0 };
    if (url === '/api/settings') return { update_check_on_start: true };
    if (url === '/api/update-check') return check;
    return {};
  });
  vi.mocked(post).mockImplementation(async url => {
    if (url === '/api/update/notice/begin') return { should_check: true };
    if (url === '/api/update/notice/consume') return { notice: summary };
    return {};
  });
  await mount();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  expect(get).toHaveBeenCalledWith('/api/update-check');
  await click(t('start.works'));
  await act(async () => finishCheck(summary));
  expect(vi.mocked(get).mock.calls.filter(([url]) => url === '/api/update-check')).toHaveLength(1);
  expect(button('Available update in work list')).toBeTruthy();
  await click('Available update in work list');
  expect(host.querySelector('.dialog > h3')?.textContent).toBe(t('help.check_update'));
});
