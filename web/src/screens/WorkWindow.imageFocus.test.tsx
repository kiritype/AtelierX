// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { expect, it, vi } from 'vitest';
import { get } from '../api';
import { t } from '../i18n';
import WorkWindow from './WorkWindow';

vi.mock('./TestScreen', () => ({ default: () => null }));
vi.mock('../events', () => ({ useServerEvents: vi.fn() }));
vi.mock('../api', async original => ({ ...await original<typeof import('../api')>(), get: vi.fn(), patch: vi.fn() }));

it('keeps the original workspace and live generation form mounted during image focus', async () => {
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.mocked(get).mockImplementation(async url => {
    if (url === '/api/works/focus') return { name: 'Focus', doc: {}, effective: { linked: [], values: {} }, presets: [] };
    if (url === '/api/ui-state') return { works: { focus: {
      tabs: [{ type: 'image', view: 'single' }, { type: 'image', view: 'generate' }], active: 'image:single', sidebar: { collapsed: false, width: 286 },
    } } };
    if (url === '/api/image/catalog') return { connected: true, models: [], text_encoders: [], vaes: [], loras: [],
      samplers: ['er_sde'], schedulers: ['simple'], defaults: { sampler: 'er_sde', scheduler: 'simple' } };
    if (url === '/api/image/services') return { services: [] };
    if (url.endsWith('/image/designs')) return [{ id: 'c1', name: 'Character', path: 'c1.md', has_design: true,
      outfits: [{ id: 'o1', name: 'Suit' }, { id: 'o2', name: 'Coat' }] }];
    if (url.includes('/library/expressions?')) return {
      e1: { id: 'e1', name: 'Smile', rating: 'general' }, e2: { id: 'e2', name: 'Frown', rating: 'general' },
    };
    if (url.endsWith('/library/rules')) return { ratings: [{ id: 'general', name: 'General' }] };
    if (url.endsWith('/single/runs')) return { runs: [{ id: 'running', status: 'running', created_at: '2026-11-10', service: 'comfyui', seed: 8 }] };
    return [];
  });
  const toggle = () => host.querySelector<HTMLButtonElement>('.image-focus-toggle')!;
  try {
    await act(async () => root.render(<QueryClientProvider client={qc}><WorkWindow workId="focus" onLeave={vi.fn()} onLock={vi.fn()} /></QueryClientProvider>));
    for (let attempt = 0; attempt < 40 && !host.querySelector('.generation-details'); attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    }
    expect(host.querySelector('.generation-details')).toBeTruthy();

    const main = host.querySelector<HTMLElement>('.main')!;
    const side = host.querySelector('#work-side-panel')!.firstElementChild;
    const aux = host.querySelector<HTMLElement>('.aux')!;
    const prompt = host.querySelector<HTMLTextAreaElement>('textarea[id$="-positive"]')!;
    const advanced = host.querySelector<HTMLDetailsElement>('.generation-details')!;
    const runStatus = () => host.querySelector('.single-result-head [role="status"]')?.textContent;
    expect(advanced.open).toBe(false);
    expect(advanced.querySelector('summary')?.textContent).toContain('er_sde · simple');
    expect(host.querySelector('.generation-resolution')?.textContent).toContain('1536 × 1536');

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(prompt, 'A quiet lake');
      prompt.dispatchEvent(new Event('input', { bubbles: true }));
      advanced.open = true;
      toggle().focus();
      toggle().click();
    });

    expect(toggle().getAttribute('aria-pressed')).toBe('true');
    expect(document.activeElement).toBe(toggle());
    expect(main.classList.contains('image-focus')).toBe(true);
    expect(aux.style.display).toBe('none');
    expect(runStatus()).toBe(t('single.state.running'));
    expect(host.querySelector('.tab .dirty')).toBeTruthy();

    await act(async () => toggle().click());
    expect(main.classList.contains('image-focus')).toBe(false);
    expect(main.style.getPropertyValue('--side')).toBe('286px');
    expect(host.querySelector('#work-side-panel')!.firstElementChild).toBe(side);
    expect(aux.style.display).toBe('flex');
    expect(host.querySelector('textarea[id$="-positive"]')).toBe(prompt);
    expect(prompt.value).toBe('A quiet lake');
    expect(advanced.open).toBe(true);
    expect(runStatus()).toBe(t('single.state.running'));

    const batchTab = [...host.querySelectorAll<HTMLElement>('.tab')].find(tab => tab.querySelector('.tab-title')?.textContent === t('image_menu.generate'))!;
    const batch = host.querySelector<HTMLElement>('.generation-page:not(.single-image)')!;
    await act(async () => batchTab.click());
    const outfits = batch.querySelector<HTMLInputElement>(`input[aria-label="${t('gen.table.all')}"]`)!;
    const expressions = batch.querySelector<HTMLInputElement>('.image-gen-pick input[type="checkbox"]')!;
    const count = batch.querySelector<HTMLInputElement>('footer input[type="number"]')!;
    const batchToggle = batch.parentElement!.previousElementSibling!.querySelector<HTMLButtonElement>('.image-focus-toggle')!;
    await act(async () => {
      outfits.click();
      expressions.click();
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(count, '3');
      count.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const expectedTotal = t('gen.bar_total', { targets: 4, count: 3, n: 12 });
    expect(batch.querySelector('footer')?.textContent).toContain(expectedTotal);
    await act(async () => batchToggle.click());
    expect(main.classList.contains('image-focus')).toBe(true);
    expect(batch.querySelector('footer')?.textContent).toContain(expectedTotal);
    expect(outfits.checked && expressions.checked).toBe(true);
    expect(count.value).toBe('3');
    await act(async () => batchToggle.click());
    expect(main.classList.contains('image-focus')).toBe(false);
  } finally {
    await act(async () => root.unmount());
    qc.clear();
    host.remove();
    localStorage.clear();
  }
});
