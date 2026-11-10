// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from './App';
import { AppThemeProvider } from './AppTheme';
import { get } from './api';
import JsxWorkbench from './components/JsxWorkbench';
import { t } from './i18n';
import type { WorkInfo } from './types';
import { createSaver } from './lib/exampleSaver';

vi.mock('./api', async (original) => ({ ...await original<typeof import('./api')>(), get: vi.fn() }));
vi.mock('./screens/Lock', () => ({ default: () => <div>Locked</div> }));
vi.mock('./components/JsxPreview', () => ({
  default: ({ theme }: { theme: string }) => <div data-preview-theme={theme} />,
}));

let root: Root;
let host: HTMLDivElement;
let client: QueryClient;
let systemDark: boolean;
let media: EventTarget;

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  systemDark = false;
  media = new EventTarget();
  Object.defineProperty(media, 'matches', { get: () => systemDark });
  vi.stubGlobal('matchMedia', () => media);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  host.remove();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function setSystemDark(dark: boolean) {
  systemDark = dark;
  await act(async () => { media.dispatchEvent(new Event('change')); });
}

it('applies the saved theme when the lock screen first appears', async () => {
  vi.mocked(get).mockResolvedValue({ initialized: true, unlocked: false, language: 'ko', theme: 'dark', wait: 0 });
  await act(async () => root.render(<QueryClientProvider client={client}><App /></QueryClientProvider>));
  expect(host.textContent).toContain('Locked');
  expect(document.documentElement.dataset.theme).toBe('dark');
  expect(get).toHaveBeenCalledExactlyOnceWith('/api/auth/status');
});

it('follows the OS in system mode and lets the JSX preview override the app', async () => {
  vi.mocked(get).mockResolvedValue([]);
  const saver = createSaver<{ jsx: string; name: string }>(async () => {});
  const info = { effective: { values: {} } } as WorkInfo;
  const render = (preference: 'light' | 'dark' | 'system') => act(async () => root.render(
    <QueryClientProvider client={client}>
      <AppThemeProvider preference={preference}>
        <JsxWorkbench workId="work" jsxId="J001" name="Card" source="" defaultProps={undefined} info={info} setDefault={() => {}} saver={saver} />
      </AppThemeProvider>
    </QueryClientProvider>,
  ));
  const app = () => document.documentElement.dataset.theme;
  const preview = () => host.querySelector<HTMLElement>('[data-preview-theme]')?.dataset.previewTheme;
  const choose = async (label: string) => {
    const button = [...host.querySelectorAll('button')].find((entry) => entry.textContent === label)!;
    await act(async () => button.click());
    expect(button.getAttribute('aria-pressed')).toBe('true');
  };

  await render('system');
  expect([app(), preview()]).toEqual(['light', 'light']);
  await setSystemDark(true);
  expect([app(), preview()]).toEqual(['dark', 'dark']);
  await choose(t('jsx.light'));
  expect([app(), preview()]).toEqual(['dark', 'light']);

  await render('light');
  await setSystemDark(false);
  await setSystemDark(true);
  expect([app(), preview()]).toEqual(['light', 'light']);
  await choose(t('jsx.dark'));
  expect([app(), preview()]).toEqual(['light', 'dark']);
  await choose(t('jsx.app'));
  expect([app(), preview()]).toEqual(['light', 'light']);

  await render('system');
  expect([app(), preview()]).toEqual(['dark', 'dark']);
});
