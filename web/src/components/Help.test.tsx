// @vitest-environment happy-dom
import { act, createElement, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useStartupUpdateCheck } from './Help';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { get, post, toast } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), toast: vi.fn() }));
let pendingNotice: { current: string; latest: string; newer: boolean } | null = null;
let serverChecked = false;
let serverAvailable: string | null = null;
let serverNotified: string | null = null;
const openUpdate = () => {};
const localStorageDescriptor = Object.getOwnPropertyDescriptor(window, 'localStorage') ?? {
  configurable: true, enumerable: true, writable: true, value: window.localStorage,
};
vi.mock('../api', () => ({ get, post }));
vi.mock('./Toasts', () => ({ useToast: () => toast }));

function Harness({ enabled = true }: { enabled?: boolean }) {
  const [available, setAvailable] = useState(false);
  useStartupUpdateCheck(enabled, setAvailable, openUpdate);
  return createElement('main', null, 'work screen', available ? createElement('button', { className: 'update' }, 'Update') : null);
}

describe('startup update notice', () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    pendingNotice = null;
    serverChecked = false;
    serverAvailable = null;
    serverNotified = null;
    post.mockImplementation(async (url: string, body?: { latest?: string; current?: string; newer?: boolean }) => {
      if (url.endsWith('/begin')) {
        const should_check = !serverChecked;
        serverChecked = true;
        return { should_check, available_version: serverAvailable };
      }
      if (url.endsWith('/result')) {
        serverAvailable = body?.newer ? body.latest ?? null : null;
        pendingNotice = body?.newer && body.current && body.latest && body.latest !== serverNotified
          ? { current: body.current, latest: body.latest, newer: true }
          : null;
        return { available_version: body?.newer ? body.latest : null };
      }
      if (url.endsWith('/consume')) {
        const notice = pendingNotice;
        pendingNotice = null;
        if (notice) serverNotified = notice.latest;
        return { notice };
      }
      return { claimed: true };
    });
    toast.mockReset();
  });

  afterEach(async () => {
    if (root) await act(async () => root.unmount());
    host?.remove();
    if (localStorageDescriptor) Object.defineProperty(window, 'localStorage', localStorageDescriptor);
    window.localStorage.clear();
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

    await act(async () => { resolve({ current: '8.8.0', latest: '8.8.1', newer: true }); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
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

  it('restores the badge from app-root state without another release request', async () => {
    post.mockImplementation(async (url: string) => url.endsWith('/begin')
      ? { should_check: false, available_version: '8.8.1' }
      : { notice: null });
    await mount();
    expect(host.querySelector('.update')).not.toBeNull();
    expect(get).not.toHaveBeenCalled();
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
    await act(async () => { resolve({ current: '8.8.0', latest: '8.8.1', newer: true }); await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });

    expect(host.querySelector('.update')).not.toBeNull();
    expect(get).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it('does not depend on browser storage to persist notice state', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(2_000_000_000_000);
    Object.defineProperty(window, 'localStorage', { configurable: true, get: () => { throw new Error('blocked'); } });
    get.mockResolvedValue({ current: '8.8.1', latest: '8.8.2', newer: true });
    await mount();
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(host.querySelector('.update')).not.toBeNull();
    expect(toast).toHaveBeenCalledTimes(1);

    await act(async () => root.unmount());
    root = createRoot(host);
    get.mockClear();
    await act(async () => root.render(createElement(Harness)));
    expect(host.querySelector('.update')).not.toBeNull();
    expect(post).toHaveBeenCalledWith('/api/update/notice/begin');
    expect(toast).toHaveBeenCalledTimes(1);
  });
});
