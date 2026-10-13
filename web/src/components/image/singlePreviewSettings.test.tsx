// @vitest-environment happy-dom
import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from '../../api';
import { t } from '../../i18n';
import GenSettings from './GenSettings';
import NovelAISettings from './NovelAISettings';
import PixAISettings from './PixAISettings';
import { COMFY_PREVIEW_CATALOG, COMFY_PREVIEW_DEFAULTS, NOVELAI_PREVIEW_DEFAULTS, NOVELAI_PREVIEW_INFO, PIXAI_PREVIEW_DEFAULTS, PIXAI_PREVIEW_INFO } from './singlePreviewSettings';

vi.mock('../../api', async (original) => ({ ...await original<typeof import('../../api')>(), get: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
let qc: QueryClient;
function Panels({ preview = true }: { preview?: boolean }) {
  const [comfy, setComfy] = useState(COMFY_PREVIEW_DEFAULTS);
  const [nai, setNai] = useState(NOVELAI_PREVIEW_DEFAULTS);
  const [pixai, setPixai] = useState(PIXAI_PREVIEW_DEFAULTS);
  return <>
    <section id="comfy"><GenSettings preview={preview} value={comfy} onChange={setComfy} /></section>
    <section id="nai"><NovelAISettings preview={preview} value={nai} onChange={setNai} /></section>
    <section id="pixai"><PixAISettings preview={preview} value={pixai} onChange={setPixai} /></section>
  </>;
}
const render = (preview = true) => act(async () => root.render(<QueryClientProvider client={qc}><Panels preview={preview} /></QueryClientProvider>));
async function click(section: string, label: string) {
  const button = [...host.querySelectorAll(`${section} button`)].find((el) => el.textContent?.trim() === label);
  expect(button).toBeTruthy();
  await act(async () => (button as HTMLButtonElement).click());
}
beforeEach(() => {
  vi.clearAllMocks();
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  qc.clear();
  host.remove();
});

it('keeps preview interactive and network-free, including forced query refreshes, without changing live caches', async () => {
  const live = { private: 'real cached content' };
  qc.setQueryData(['image-catalog'], live);
  qc.setQueryData(['image-service-info', 'novelai'], live);
  qc.setQueryData(['image-service-info', 'pixai'], live);
  qc.setQueryData(['image-service-account', 'novelai'], live);
  vi.mocked(get).mockRejectedValue(new Error('Preview must never use an API'));
  await render();
  expect(host.textContent).toContain('demo-anima.safetensors');
  expect(host.textContent).toContain('Demo model');
  expect(host.textContent).toContain('Demo SDXL');
  await click('#comfy', t('gen.add_lora'));
  expect((host.querySelector('#comfy select') as HTMLSelectElement).value).toBe('demo-anima.safetensors');
  expect(host.textContent).toContain('demo-lora.safetensors');
  await click('#comfy', 'SDXL·IL');
  expect((host.querySelector('#comfy select') as HTMLSelectElement).value).toBe('checkpoint::demo-sdxl.safetensors');
  await click('#nai', t('nai.size_portrait'));
  expect((host.querySelector('#nai input[type="number"]') as HTMLInputElement).value).toBe('832');
  const label = [...host.querySelectorAll('#pixai label')].find((el) => el.textContent?.includes('Demo LoRA'))!;
  const lora = label.querySelector('input') as HTMLInputElement;
  await act(async () => lora.click());
  expect(host.querySelector('#pixai input[aria-label="' + t('pixai.lora_weight') + '"]')).not.toBeNull();
  for (const query of qc.getQueryCache().findAll({ queryKey: ['image-single-preview'] })) {
    // fetch() also exercises the disabled account query: enabled:false alone is insufficient protection.
    await act(async () => { await query.fetch(); });
  }
  expect(get).not.toHaveBeenCalled();
  expect(qc.getQueryData(['image-catalog'])).toBe(live);
  expect(qc.getQueryData(['image-service-info', 'novelai'])).toBe(live);
  expect(qc.getQueryData(['image-service-info', 'pixai'])).toBe(live);
  expect(qc.getQueryData(['image-service-account', 'novelai'])).toBe(live);
  expect(host.textContent).not.toContain(t('nai.account_refresh'));
  expect(host.textContent).not.toContain(t('nai.account_loading'));
  expect(host.textContent).not.toContain(t('pixai.cost_unknown'));
});

it('retains API queries when preview is off', async () => {
  vi.mocked(get).mockImplementation(async (url) => {
    if (url === '/api/image/catalog') return COMFY_PREVIEW_CATALOG;
    if (url === '/api/image/services/novelai/info') return NOVELAI_PREVIEW_INFO;
    if (url === '/api/image/services/pixai/info') return PIXAI_PREVIEW_INFO;
    return { tier: null, active: null, anlas: null, opus: false };
  });
  await render(false);
  expect(get).toHaveBeenCalledWith('/api/image/catalog');
  expect(get).toHaveBeenCalledWith('/api/image/services/novelai/info');
  expect(get).toHaveBeenCalledWith('/api/image/services/novelai/account');
  expect(get).toHaveBeenCalledWith('/api/image/services/pixai/info');
});
