// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useStartupUpdateCheck } from './Help';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { get, toast } = vi.hoisted(() => ({ get: vi.fn(), toast: vi.fn() }));
const openUpdate = () => {};
const localStorageDescriptor = Object.getOwnPropertyDescriptor(window, 'localStorage') ?? {
  configurable: true, enumerable: true, writable: true, value: window.localStorage,
};
vi.mock('../api', () => ({ get, post: vi.fn() }));
vi.mock('./Toasts', () => ({ useToast: () => toast }));

function Harness({ enabled = true }: { enabled?: boolean }) {
  const [available, setAvailable] = useState(false);
  useStartupUpdateCheck(enabled, setAvailable, openUpdate);
  return createElement('main', null, 'work screen', available ? createElement('button', { className: 'update' }, 'Update') : null);
}

describe('startup update notice', () => {
  let host: HTMLDivElement;
  let root: Root;

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    host?.remove();
    if (localStorageDescriptor) Object.defineProperty(window, 'localStorage', localStorageDescriptor);
    window.localStorage.clear();
    get.mockReset();
    toast.mockReset();
    vi.restoreAllMocks();
  });

  async function mount(enabled = true) {
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    await act(async () => root.render(createElement(Harness, { enabled })));
  }

  it('renders immediately while the release request is pending, then shows one badge and notice for a version', async () => {
    let resolve!: (result: unknown) => void;
    get.mockReturnValue(new Promise((done) => { resolve = done; }));
    await mount();
    await act(async () => Promise.resolve());
    expect(host.textContent).toContain('work screen');
    expect(host.querySelector('.update')).toBeNull();

    await act(async () => resolve({ current: '0.4.0', latest: '0.4.1', newer: true }));
    expect(host.querySelector('.update')).not.toBeNull();
    expect(toast).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    root = createRoot(host);
    get.mockClear();
    await act(async () => root.render(createElement(Harness)));
    expect(host.querySelector('.update')).not.toBeNull();
    expect(get).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('clears the badge when the latest version is already installed', async () => {
    window.localStorage.setItem('atelierx.update-notice.available-version', '0.4.1');
    let resolve!: (result: unknown) => void;
    get.mockReturnValue(new Promise((done) => { resolve = done; }));
    await mount();
    await act(async () => Promise.resolve());
    expect(host.querySelector('.update')).not.toBeNull();
    await act(async () => resolve({ current: '0.4.1', latest: '0.4.1', newer: false }));
    expect(host.querySelector('.update')).toBeNull();
    expect(toast).not.toHaveBeenCalled();
  });

  it('keeps the screen usable and silent when the release service is offline', async () => {
    get.mockRejectedValue(new Error('offline'));
    await mount();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.textContent).toContain('work screen');
    expect(toast).not.toHaveBeenCalled();
  });

  it('does not request releases when startup checking is disabled', async () => {
    await mount(false);
    expect(host.textContent).toContain('work screen');
    expect(get).not.toHaveBeenCalled();
  });

  it('delivers a pending result to the next screen after the first screen unmounts', async () => {
    let resolve!: (result: unknown) => void;
    get.mockReturnValue(new Promise((done) => { resolve = done; }));
    await mount();
    await act(async () => Promise.resolve());
    expect(get).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    root = createRoot(host);
    await act(async () => root.render(createElement(Harness)));
    await act(async () => resolve({ current: '0.4.0', latest: '0.4.1', newer: true }));

    expect(host.querySelector('.update')).not.toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('uses session memory to prevent repeated checks and notices when local storage is blocked', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(2_000_000_000_000);
    Object.defineProperty(window, 'localStorage', { configurable: true, get: () => { throw new Error('blocked'); } });
    get.mockResolvedValue({ current: '0.4.1', latest: '0.4.2', newer: true });
    await mount();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector('.update')).not.toBeNull();
    expect(toast).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    root = createRoot(host);
    get.mockClear();
    await act(async () => root.render(createElement(Harness)));
    expect(host.querySelector('.update')).not.toBeNull();
    expect(get).not.toHaveBeenCalled();
    expect(toast).toHaveBeenCalledTimes(1);
  });
});
